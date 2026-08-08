"""Single-owner asyncio thread used by the Android bridge.

Android enters Python on a short-lived bridge executor.  The dispatcher moves
all Runtime work onto one persistent asyncio loop so synchronous callbacks,
asynchronous callback continuations, rendering, and commit creation never
mutate the Runtime concurrently.
"""

from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import Callable
from concurrent.futures import Future
from queue import Empty, SimpleQueue
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
        self._queue: SimpleQueue[Any] = SimpleQueue()
        self._reader, self._writer = os.pipe()
        os.set_blocking(self._reader, False)
        os.set_blocking(self._writer, False)
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
        self._require_loop()
        future: Future[Any] = Future()
        self._queue.put((function, settle, future))
        self._wake()
        return future

    def close(self) -> None:
        """Stop the owner loop after the Runtime has been disposed."""
        loop = self._loop
        if loop is None:
            return
        if self._thread is current_thread():
            loop.call_soon(loop.stop)
            return
        self._queue.put(None)
        self._wake()
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
        loop.add_reader(self._reader, self._drain_queue)
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.remove_reader(self._reader)
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.close()
            os.close(self._reader)
            os.close(self._writer)
            self._loop = None

    def _wake(self) -> None:
        try:
            os.write(self._writer, b"\0")
        except BlockingIOError:
            # A queued wake byte already guarantees the reader will run.
            pass

    def _drain_queue(self) -> None:
        try:
            while os.read(self._reader, 4096):
                pass
        except BlockingIOError:
            pass

        while True:
            try:
                item = self._queue.get_nowait()
            except Empty:
                return
            if item is None:
                self._require_loop().stop()
                return
            function, settle, future = item
            task = self._require_loop().create_task(
                self._invoke(function, settle)
            )

            def finished(
                completed: asyncio.Task[Any],
                target: Future[Any] = future,
            ) -> None:
                if target.cancelled():
                    return
                try:
                    target.set_result(completed.result())
                except BaseException as error:
                    target.set_exception(error)

            task.add_done_callback(finished)

    @staticmethod
    async def _invoke(function: Callable[[], Any], settle: Any | None) -> Any:
        result = function()
        if inspect.isawaitable(result):
            result = await result
        if settle is not None:
            await settle._settle_async_callbacks()
        return result
