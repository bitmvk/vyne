"""Focused tests for the shared batch transaction executor.

The Runtime consolidates the native-event and external-callback pipelines
into one ``_run_batch_transaction`` executor.  These tests pin the
intentional policy differences (handler order, rollback atomicity, and the
origin event recorded for returned awaitables) so the shared path cannot
silently change either pipeline.
"""

from __future__ import annotations

import asyncio

from vyne import Text, state
from vyne.events import Event
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport

from tests.support.runtime_helpers import native_listener_event


def mounted_runtime():
    cells = {}

    def App():
        value = state(0)
        cells["value"] = value
        return Text(text=f"Value: {value.value}")

    transport = MemoryTransport()
    runtime = Runtime(App, transport=transport)
    runtime.mount()
    return runtime, transport, cells



def test_native_batch_preserves_handler_order() -> None:
    """One batch runs handlers in delivery order and renders once."""
    calls: list[int] = []

    def App():
        value = state(0)

        def on_click(event) -> None:
            next_value = calls[-1] + 1 if calls else 1
            value.set(next_value)
            calls.append(next_value)

        return Text(text=str(value.value), on_click=on_click)

    transport = MemoryTransport()
    runtime = Runtime(App, transport=transport)
    runtime.mount()
    event = native_listener_event(transport, sequence=1)
    prior_commits = len(transport.messages)

    runtime.dispatch_native_events([event, event, event])

    assert calls == [1, 2, 3]
    assert len(transport.messages) == prior_commits + 1


def test_external_batch_preserves_handler_order() -> None:
    """External callbacks run in batch order and produce one commit."""
    runtime, transport, cells = mounted_runtime()
    subscription = runtime.subscribe_external_callback(
        lambda payload: cells["value"].set(payload)
    )
    prior_commits = len(transport.messages)

    runtime.dispatch_external_callbacks(
        [(subscription, 1), (subscription, 2), (subscription, 3)],
    )

    assert cells["value"].value == 3
    assert len(transport.messages) == prior_commits + 1


def test_native_batch_failure_rolls_back_all_mutations() -> None:
    """A failing handler rolls back every mutation in the same batch."""
    cells = {}

    def App():
        value = state(0)
        cells["value"] = value
        return Text(
            text=str(value.value),
            on_click=lambda event: _raise(),
        )

    def _raise():
        cells["value"].set(9)
        raise ValueError("boom")

    transport = MemoryTransport()
    runtime = Runtime(App, transport=transport)
    runtime.mount()
    event = native_listener_event(transport, sequence=1)

    runtime.dispatch_native_events([event, event])

    assert cells["value"].value == 0
    assert "boom" in (runtime._last_error or "")


def test_external_batch_failure_rolls_back_all_mutations() -> None:
    """A failing external callback rolls back earlier writes in the batch."""
    runtime, _, cells = mounted_runtime()
    subscription = runtime.subscribe_external_callback(
        lambda payload: _boom(payload, cells["value"])
    )
    runtime.dispatch_external_callbacks(
        [(subscription, 1), (subscription, 2)],
    )

    assert cells["value"].value == 0
    assert "external boom" in (runtime._last_error or "")


def _boom(payload, cell):
    cell.set(payload)
    if payload == 2:
        raise ValueError("external boom")


def test_external_async_callback_has_no_event_origin() -> None:
    """External callback awaitables carry no origin event sequence."""

    async def scenario() -> None:
        release = asyncio.Event()
        cells = {}

        async def on_value(payload) -> None:
            cells["value"].set(payload)
            await release.wait()
            cells["value"].set(payload + 1)

        def App():
            value = state(0)
            cells["value"] = value
            return Text(text=str(value.value))

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()
        subscription = runtime.subscribe_external_callback(on_value)
        prior = len(transport.messages)

        runtime.dispatch_external_callbacks([(subscription, 7)])
        await runtime._settle_async_callbacks()
        # External callbacks have no native event origin; the commit must
        # not carry an origin_event_seq for this async continuation.
        assert "origin_event_seq" not in transport.latest
        release.set()
        await runtime._settle_async_callbacks()
        assert "origin_event_seq" not in transport.latest
        assert len(transport.messages) == prior + 2

    asyncio.run(scenario())


def test_native_batch_origin_is_last_dispatched_event_not_last_item() -> None:
    """A trailing event with no handler must not become the flush origin.

    The flush origin is the last event that actually dispatched (it set
    ``_batched_origin_event``), not merely the last item in the batch.
    """
    sequences: list[int] = []

    def App():
        value = state(0)

        def on_click(event) -> None:
            value.set(value.value + 1)
            sequences.append(event.sequence)

        return Text(text=str(value.value), on_click=on_click)

    transport = MemoryTransport()
    runtime = Runtime(App, transport=transport)
    runtime.mount()
    real = native_listener_event(transport, sequence=7)
    stale = Event(
        name="click",
        target=9999,  # no node with this target: no handler is dispatched
        handler=1,
        payload={},
        sequence=99,
    )

    runtime.dispatch_native_events([real, stale])

    assert sequences == [7]
    assert transport.latest["origin_event_seq"] == 7


def test_nested_external_batch_keeps_outer_flush_origin() -> None:
    """An external batch dispatched inside a native handler does not steal
    the outer batch's flush origin or emit a second commit."""
    cells = {}

    def on_click(event) -> None:
        cells["value"].set(1)
        # Inner external batch runs nested inside the outer native batch.
        runtime.dispatch_external_callbacks(
            [(subscription, 2), (subscription, 3)]
        )
        cells["value"].set(4)

    def App():
        value = state(0)
        cells["value"] = value
        return Text(text=str(value.value), on_click=on_click)

    transport = MemoryTransport()
    runtime = Runtime(App, transport=transport)
    runtime.mount()
    subscription = runtime.subscribe_external_callback(
        lambda payload: cells["value"].set(payload)
    )
    event = native_listener_event(transport, sequence=21)
    prior = len(transport.messages)

    runtime.dispatch_native_events([event])

    assert cells["value"].value == 4
    assert len(transport.messages) == prior + 1
    assert transport.latest["origin_event_seq"] == 21
