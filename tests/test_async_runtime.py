from __future__ import annotations

import asyncio
from threading import current_thread

import pytest

from vyne.async_runtime import AsyncRuntimeDispatcher


def test_dispatcher_runs_sync_async_and_settle_on_owner_thread() -> None:
    owner_threads: list[str] = []

    class Runtime:
        async def _settle_async_callbacks(self) -> None:
            owner_threads.append(current_thread().name)

    async def work() -> int:
        await asyncio.sleep(0)
        owner_threads.append(current_thread().name)
        return 42

    dispatcher = AsyncRuntimeDispatcher()
    try:
        assert dispatcher.call(lambda: work(), settle=Runtime()) == 42
    finally:
        dispatcher.close()

    assert owner_threads == ["vyne-async-runtime", "vyne-async-runtime"]
    with pytest.raises(RuntimeError, match="closed"):
        dispatcher.submit(lambda: None)
