from __future__ import annotations

import asyncio

from vyne import Text, state
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport

from tests.support.runtime_helpers import SilentTransport, native_listener_event



def test_async_event_flushes_before_and_after_await_separately() -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        cells = {}

        async def on_click(event) -> None:
            cells["loading"].set(True)
            await release.wait()
            cells["value"].set("loaded")
            cells["loading"].set(False)

        def App():
            loading = state(False)
            value = state("empty")
            cells.update(loading=loading, value=value)
            return Text(
                text=f"{loading.value}:{value.value}",
                on_click=on_click,
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()
        initial_commits = len(transport.messages)

        runtime.dispatch_native_events([native_listener_event(transport, sequence=10)])
        await runtime._settle_async_callbacks()

        assert cells["loading"].value is True
        assert cells["value"].value == "empty"
        assert len(transport.messages) == initial_commits + 1
        assert transport.latest["origin_event_seq"] == 10

        release.set()
        await runtime._settle_async_callbacks()

        assert cells["loading"].value is False
        assert cells["value"].value == "loaded"
        assert len(transport.messages) == initial_commits + 2
        assert transport.latest["origin_event_seq"] == 10

    asyncio.run(scenario())


def test_other_callback_commits_while_async_callback_is_waiting() -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        cells = {}

        async def wait_for_result(event) -> None:
            cells["status"].set("waiting")
            await release.wait()
            cells["status"].set("finished")

        def App():
            status = state("idle")
            other = state(0)
            cells.update(status=status, other=other)
            return Text(text=status.value, on_click=wait_for_result)

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()
        runtime.dispatch_native_events([native_listener_event(transport, sequence=1)])
        await runtime._settle_async_callbacks()

        subscription = runtime.subscribe_external_callback(
            lambda value: cells["other"].set(value)
        )
        runtime.dispatch_external_callbacks([(subscription, 7)])

        assert cells["status"].value == "waiting"
        assert cells["other"].value == 7

        release.set()
        await runtime._settle_async_callbacks()
        assert cells["status"].value == "finished"

    asyncio.run(scenario())


def test_async_continuation_waits_behind_in_flight_commit() -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        cells = {}

        async def on_click(event) -> None:
            cells["value"].set(1)
            await release.wait()
            cells["value"].set(2)

        def App():
            value = state(0)
            cells["value"] = value
            return Text(text=str(value.value), on_click=on_click)

        transport = SilentTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()
        runtime.acknowledge_native_apply(1)

        runtime.dispatch_native_events([native_listener_event(transport, sequence=5)])
        await runtime._settle_async_callbacks()
        assert transport.latest["revision"] == 2

        release.set()
        await runtime._settle_async_callbacks()
        assert cells["value"].value == 2
        assert transport.latest["revision"] == 2

        runtime.acknowledge_native_apply(2)
        assert transport.latest["revision"] == 3
        assert transport.latest["origin_event_seq"] == 5

    asyncio.run(scenario())


def test_async_external_callback_is_supported_without_a_wrapper() -> None:
    async def scenario() -> None:
        cells = {}

        def App():
            value = state(0)
            cells["value"] = value
            return Text(text=str(value.value))

        async def callback(payload) -> None:
            await asyncio.sleep(0)
            cells["value"].set(payload)

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()
        subscription = runtime.subscribe_external_callback(callback)

        runtime.dispatch_external_callbacks([(subscription, 9)])
        await runtime._settle_async_callbacks()

        assert cells["value"].value == 9

    asyncio.run(scenario())


def test_async_callback_failure_rolls_back_current_turn() -> None:
    async def scenario() -> None:
        cells = {}

        async def fail(event) -> None:
            cells["value"].set(4)
            raise ValueError("async callback failed")

        def App():
            value = state(0)
            cells["value"] = value
            return Text(text=str(value.value), on_click=fail)

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()
        runtime.dispatch_native_events([native_listener_event(transport, sequence=2)])
        await runtime._settle_async_callbacks()

        assert cells["value"].value == 0
        assert runtime._last_error == "async callback failed"

    asyncio.run(scenario())


def test_sync_dispatch_entry_point_still_runs_async_callback() -> None:
    cells = {}

    async def on_click(event) -> None:
        await asyncio.sleep(0)
        cells["value"].set(3)

    def App():
        value = state(0)
        cells["value"] = value
        return Text(text=str(value.value), on_click=on_click)

    transport = MemoryTransport()
    runtime = Runtime(App, transport=transport)
    runtime.mount()
    runtime.dispatch_native_events([native_listener_event(transport, sequence=8)])

    assert runtime.wait_for_async_callbacks(timeout=1)
    assert cells["value"].value == 3
    runtime.dispose()
