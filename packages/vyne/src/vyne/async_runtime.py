"""Single-owner asyncio thread used by the Android bridge.

Android enters Python on a short-lived bridge executor.  The dispatcher moves
all Runtime work onto one persistent asyncio loop so synchronous callbacks,
asynchronous callback continuations, rendering, and commit creation never
mutate the Runtime concurrently.

Cross-thread scheduling uses the stdlib primitives: ``run_coroutine_threadsafe``
submits a coroutine to the owner loop and returns a concurrent Future, and
``call_soon_threadsafe`` wakes the loop for shutdown — no custom pipe/queue.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from concurrent.futures import Future
from threading import Event, Thread, current_thread
from typing import Any


class AsyncRuntimeDispatcher:
    """Run framework work on one dedicated asyncio event-loop thread."""

    def __init__(
        self,
        *,
        thread_setup: Callable[[], None] | None = None,
    ) -> None:
        """
        *thread_setup* runs once on the dispatcher thread before the loop
        starts. Multi-session hosts use it to bind the thread to a session
        (e.g. a thread-local) so session-aware APIs resolve correctly.
        """
        self._thread_setup = thread_setup
        self._ready = Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = Thread(
            target=self._run,
            name="vyne-async-runtime",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait()

    def call(
        self,
        function: Callable[[], Any],
        *,
        settle: Any | None = None,
    ) -> Any:
        """Run *function* on the owner loop and wait for its short turn."""
        future = self.submit(function, settle=settle)
        return future.result()

    def submit(
        self,
        function: Callable[[], Any],
        *,
        settle: Any | None = None,
    ) -> Future[Any]:
        """Schedule framework work without transferring Runtime ownership."""
        loop = self._require_loop()
        return asyncio.run_coroutine_threadsafe(
            self._invoke(function, settle), loop
        )

    def close(self) -> None:
        """Stop the owner loop after the Runtime has been disposed."""
        loop = self._loop
        if loop is None:
            return
        if self._thread is current_thread():
            loop.call_soon(loop.stop)
            return
        loop.call_soon_threadsafe(loop.stop)
        self._thread.join(timeout=5)

    def _require_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is None:
            raise RuntimeError("Async Runtime dispatcher is closed")
        return loop

    def _run(self) -> None:
        if self._thread_setup is not None:
            self._thread_setup()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.close()
            self._loop = None

    @staticmethod
    async def _invoke(function: Callable[[], Any], settle: Any | None) -> Any:
        result = function()
        if inspect.isawaitable(result):
            result = await result
        if settle is not None:
            await settle._settle_async_callbacks()
        return result
