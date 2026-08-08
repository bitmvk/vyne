from __future__ import annotations

import asyncio
import threading
import unittest

from vyne import Text, latest, state
from vyne.events import Event
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport


class SilentTransport:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def send(self, message: dict) -> None:
        self.messages.append(message)

    @property
    def latest(self) -> dict:
        return self.messages[-1]


def listener(transport, sequence: int = 1) -> Event:
    operation = next(
        op for op in transport.latest["ops"] if op["op"].startswith("listen")
    )
    return Event(
        name=operation["event"],
        target=operation["id"],
        handler=operation["handler"],
        payload={},
        sequence=sequence,
    )


class AsyncCallbackMatrixTests(unittest.IsolatedAsyncioTestCase):
    async def test_zero_argument_async_event_handler(self):
        cells = {}

        async def handler():
            await asyncio.sleep(0)
            cells["value"].set(1)

        runtime, transport = self.mount(cells, handler)
        runtime.dispatch_native_events([listener(transport)])
        await runtime._settle_async_callbacks()
        self.assertEqual(cells["value"].value, 1)

    async def test_event_argument_reaches_async_handler(self):
        cells = {}
        seen = []

        async def handler(event):
            await asyncio.sleep(0)
            seen.append((event.name, event.sequence))

        runtime, transport = self.mount(cells, handler)
        runtime.dispatch_native_events([listener(transport, sequence=44)])
        await runtime._settle_async_callbacks()
        self.assertEqual(seen, [("click", 44)])

    async def test_sync_function_returning_awaitable_is_supported(self):
        cells = {}

        async def work():
            await asyncio.sleep(0)
            cells["value"].set(2)

        def handler(event):
            return work()

        runtime, transport = self.mount(cells, handler)
        runtime.dispatch_native_events([listener(transport)])
        await runtime._settle_async_callbacks()
        self.assertEqual(cells["value"].value, 2)

    async def test_async_handler_with_no_state_change_emits_no_commit(self):
        cells = {}

        async def handler(event):
            await asyncio.sleep(0)

        runtime, transport = self.mount(cells, handler)
        baseline = len(transport.messages)
        runtime.dispatch_native_events([listener(transport)])
        await runtime._settle_async_callbacks()
        self.assertEqual(len(transport.messages), baseline)

    async def test_equal_state_write_after_await_emits_no_commit(self):
        cells = {}

        async def handler(event):
            await asyncio.sleep(0)
            cells["value"].set(0)

        runtime, transport = self.mount(cells, handler)
        baseline = len(transport.messages)
        runtime.dispatch_native_events([listener(transport)])
        await runtime._settle_async_callbacks()
        self.assertEqual(len(transport.messages), baseline)

    async def test_multiple_writes_before_await_are_one_commit(self):
        gate = asyncio.Event()
        cells = {}

        async def handler(event):
            cells["value"].set(1)
            cells["value"].set(2)
            cells["value"].set(3)
            await gate.wait()

        runtime, transport = self.mount(cells, handler)
        baseline = len(transport.messages)
        runtime.dispatch_native_events([listener(transport)])
        await runtime._settle_async_callbacks()
        self.assertEqual(cells["value"].value, 3)
        self.assertEqual(len(transport.messages), baseline + 1)
        gate.set()

    async def test_multiple_writes_after_await_are_one_commit(self):
        gate = asyncio.Event()
        cells = {}

        async def handler(event):
            await gate.wait()
            cells["value"].set(4)
            cells["value"].set(5)
            cells["value"].set(6)

        runtime, transport = self.mount(cells, handler)
        baseline = len(transport.messages)
        runtime.dispatch_native_events([listener(transport)])
        await runtime._settle_async_callbacks()
        self.assertEqual(len(transport.messages), baseline)
        gate.set()
        await runtime._settle_async_callbacks()
        self.assertEqual(cells["value"].value, 6)
        self.assertEqual(len(transport.messages), baseline + 1)

    async def test_two_callbacks_can_complete_in_reverse_order(self):
        cells = {}
        gates = [asyncio.Event(), asyncio.Event()]
        invoked = 0

        async def handler(event):
            nonlocal invoked
            index = invoked
            invoked += 1
            await gates[index].wait()
            cells["value"].set(index + 1)

        runtime, transport = self.mount(cells, handler)
        event = listener(transport)
        runtime.dispatch_native_events([event])
        runtime.dispatch_native_events([event])
        await runtime._settle_async_callbacks()

        gates[1].set()
        await runtime._settle_async_callbacks()
        self.assertEqual(cells["value"].value, 2)
        gates[0].set()
        await runtime._settle_async_callbacks()
        self.assertEqual(cells["value"].value, 1)

    async def test_sync_and_async_external_callbacks_share_ordered_commits(self):
        cells = {}
        runtime, transport = self.mount(cells, lambda event: None)
        sync = runtime.subscribe_external_callback(
            lambda value: cells["value"].set(value)
        )

        async def async_callback(value):
            await asyncio.sleep(0)
            cells["value"].set(value)

        asynchronous = runtime.subscribe_external_callback(async_callback)
        runtime.dispatch_external_callbacks(
            [(sync, 1), (asynchronous, 2)]
        )
        self.assertEqual(cells["value"].value, 1)
        await runtime._settle_async_callbacks()
        self.assertEqual(cells["value"].value, 2)
        self.assertEqual(transport.latest["revision"], runtime.revision)

    async def test_async_external_callback_failure_rolls_back_turn(self):
        cells = {}
        runtime, _ = self.mount(cells, lambda event: None)

        async def callback(value):
            await asyncio.sleep(0)
            cells["value"].set(value)
            raise RuntimeError("external async failure")

        subscription = runtime.subscribe_external_callback(callback)
        runtime.dispatch_external_callbacks([(subscription, 8)])
        await runtime._settle_async_callbacks()
        self.assertEqual(cells["value"].value, 0)
        self.assertEqual(runtime._last_error, "external async failure")

    async def test_latest_decorator_accepts_async_handler(self):
        cells = {}
        calls = []

        async def handler(event):
            await asyncio.sleep(0)
            calls.append(event.sequence)

        runtime, transport = self.mount(cells, latest(handler))
        operation = next(
            op for op in transport.latest["ops"] if op["op"] == "listen_latest"
        )
        runtime.dispatch_native_events(
            [
                Event(
                    name=operation["event"],
                    target=operation["id"],
                    handler=operation["handler"],
                    payload={},
                    sequence=3,
                )
            ]
        )
        await runtime._settle_async_callbacks()
        self.assertEqual(calls, [3])

    async def test_callback_continuation_keeps_runtime_context(self):
        cells = {}
        phases = []

        async def handler(event):
            phases.append(runtime._phase)
            await asyncio.sleep(0)
            phases.append(runtime._phase)
            cells["value"].set(1)

        runtime, transport = self.mount(cells, handler)
        runtime.dispatch_native_events([listener(transport)])
        await runtime._settle_async_callbacks()
        self.assertEqual(phases, ["event", "event"])

    async def test_callback_continuation_stays_on_owner_thread(self):
        cells = {}
        thread_ids = []

        async def handler(event):
            thread_ids.append(threading.get_ident())
            await asyncio.sleep(0)
            thread_ids.append(threading.get_ident())

        runtime, transport = self.mount(cells, handler)
        runtime.dispatch_native_events([listener(transport)])
        await runtime._settle_async_callbacks()
        self.assertEqual(len(set(thread_ids)), 1)

    async def test_dispose_cancels_waiting_callback(self):
        cells = {}
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def handler(event):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        runtime, transport = self.mount(cells, handler)
        runtime.dispatch_native_events([listener(transport)])
        await started.wait()
        runtime.dispose()
        await asyncio.sleep(0)
        await asyncio.wait_for(cancelled.wait(), timeout=1)

    async def test_known_rejection_resubmits_newer_continuation(self):
        gate = asyncio.Event()
        cells = {}

        async def handler(event):
            cells["value"].set(1)
            await gate.wait()
            cells["value"].set(2)

        transport = SilentTransport()
        runtime, _ = self.mount(cells, handler, transport=transport)
        runtime.acknowledge_native_apply(1)
        runtime.dispatch_native_events([listener(transport, sequence=12)])
        await runtime._settle_async_callbacks()
        self.assertEqual(transport.latest["revision"], 2)

        gate.set()
        await runtime._settle_async_callbacks()
        runtime.report_native_failure(
            "known rejection",
            revision=2,
            unknown=False,
        )
        self.assertEqual(cells["value"].value, 2)
        self.assertEqual(transport.latest["revision"], 3)
        self.assertEqual(transport.latest["origin_event_seq"], 12)

    async def test_failure_while_commit_in_flight_preserves_prior_candidate(self):
        gate = asyncio.Event()
        cells = {}

        async def handler(event):
            cells["value"].set(1)
            await gate.wait()
            cells["value"].set(2)
            raise RuntimeError("late failure")

        transport = SilentTransport()
        runtime, _ = self.mount(cells, handler, transport=transport)
        runtime.acknowledge_native_apply(1)
        runtime.dispatch_native_events([listener(transport)])
        await runtime._settle_async_callbacks()
        gate.set()
        await runtime._settle_async_callbacks()

        self.assertEqual(cells["value"].value, 1)
        self.assertEqual(transport.latest["revision"], 2)
        runtime.acknowledge_native_apply(2)
        self.assertEqual(cells["value"].value, 1)

    async def test_stale_event_never_creates_async_task(self):
        cells = {}
        called = False

        async def handler(event):
            nonlocal called
            called = True

        runtime, transport = self.mount(cells, handler)
        event = listener(transport)
        runtime.dispatch_native_events(
            [
                Event(
                    name=event.name,
                    target=event.target,
                    handler=event.handler + 99,
                    payload={},
                    sequence=1,
                )
            ]
        )
        await runtime._settle_async_callbacks()
        self.assertFalse(called)

    def mount(self, cells, handler, *, transport=None):
        def App():
            value = state(0)
            cells["value"] = value
            return Text(text=str(value.value), on_click=handler)

        selected = transport or MemoryTransport()
        runtime = Runtime(App, transport=selected)
        runtime.mount()
        self.addCleanup(runtime.dispose)
        return runtime, selected


if __name__ == "__main__":
    unittest.main()
