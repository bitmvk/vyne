from __future__ import annotations

import asyncio
import unittest

from vyne import Box, Column, Ref, Scroll, Text, state
from vyne._effects import ScrollToEffect
from vyne.runtime import Runtime
from vyne.state import current_runtime
from vyne.transport import MemoryTransport


def _listener(runtime: Runtime, event_name: str = "click") -> tuple[int, int]:
    for node in runtime._coordinator.accepted_index.values():
        handler = node.listeners.get(event_name)
        if handler is not None:
            return node.id, handler
    raise AssertionError(f"No accepted {event_name} listener")


def _dispatch_click(runtime: Runtime, *, sequence: int = 1) -> None:
    target, handler = _listener(runtime)
    runtime.dispatch_event({
        "type": "event",
        "seq": sequence,
        "target": target,
        "event": "click",
        "handler": handler,
        "payload": {},
    })


def _scroll(ref: Ref, *, on_click) -> Column:
    return Column(
        Scroll(Box(height=1000), ref=ref, height=100),
        Text(text="run", on_click=on_click),
    )


def _queue_scroll(ref: Ref, *, offset: float, animated: bool = False) -> None:
    runtime = current_runtime()
    runtime._queue_native_effect(
        ScrollToEffect(
            ref.current,
            offset_x=0,
            offset_y=offset,
            animated=animated,
        )
    )


class RuntimeEffectTests(unittest.TestCase):
    def test_effect_only_commit_does_not_render_components(self) -> None:
        scroll_ref = Ref()
        renders = 0

        def app():
            nonlocal renders
            renders += 1
            return _scroll(
                scroll_ref,
                on_click=lambda event: _queue_scroll(
                    scroll_ref,
                    offset=240.5,
                    animated=True,
                ),
            )

        transport = MemoryTransport()
        runtime = Runtime(app, transport=transport)
        runtime.mount()
        send_count = transport.send_count

        _dispatch_click(runtime, sequence=7)

        self.assertEqual(renders, 1)
        self.assertEqual(transport.send_count, send_count + 1)
        self.assertEqual(runtime.latest_commit["origin_event_seq"], 7)
        self.assertEqual(runtime.latest_commit["ops"], [{
            "op": "scroll_to",
            "id": scroll_ref.current.node_id,
            "offset_x": 0.0,
            "offset_y": 240.5,
            "animated": True,
        }])

    def test_effect_piggybacks_after_tree_operations(self) -> None:
        scroll_ref = Ref()

        def app():
            count = state(0)

            def run(event):
                count.set(count.value + 1)
                _queue_scroll(scroll_ref, offset=50)

            return Column(
                Scroll(Box(height=1000), ref=scroll_ref, height=100),
                Text(text=str(count.value), on_click=run),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        _dispatch_click(runtime)

        operations = runtime.latest_commit["ops"]
        self.assertTrue(any(
            op.get("op") == "set_prop"
            and op.get("name") == "text"
            and op.get("value") == "1"
            for op in operations
        ))
        self.assertEqual(operations[-1]["op"], "scroll_to")

    def test_effect_for_removed_target_is_dropped_from_tree_commit(self) -> None:
        scroll_ref = Ref()

        def app():
            visible = state(True)

            def remove_and_scroll(event):
                visible.set(False)
                _queue_scroll(scroll_ref, offset=90)

            children = []
            if visible.value:
                children.append(Scroll(Box(height=1000), ref=scroll_ref, height=100))
            children.append(Text(text="remove", on_click=remove_and_scroll))
            return Column(*children)

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        _dispatch_click(runtime)

        self.assertFalse(any(
            op.get("op") == "scroll_to"
            for op in runtime.latest_commit["ops"]
        ))
        self.assertIsNone(scroll_ref.current)
        self.assertEqual(runtime._effect_pending, [])

    def test_known_rejection_rolls_back_state_and_drops_effect(self) -> None:
        class SilentTransport:
            preflights_commits = False

            def __init__(self) -> None:
                self.messages: list[dict] = []

            def send(self, message: dict) -> None:
                self.messages.append(message)

        scroll_ref = Ref()

        def app():
            changed = state(False)

            def run(event):
                changed.set(True)
                _queue_scroll(scroll_ref, offset=75)

            return Column(
                Scroll(Box(height=1000), ref=scroll_ref, height=100),
                Text(text=str(changed.value), on_click=run),
            )

        transport = SilentTransport()
        runtime = Runtime(app, transport=transport)
        runtime.mount()
        runtime.acknowledge_native_apply(1)

        _dispatch_click(runtime)
        rejected_revision = runtime.revision
        runtime.report_native_failure(revision=rejected_revision, unknown=False)

        self.assertFalse(runtime._root_scope.hooks[0].value)
        self.assertEqual(runtime._effect_pending, [])
        self.assertFalse(runtime._coordinator.in_flight)
        self.assertEqual(len(transport.messages), 2)

    def test_transport_failure_drops_effect_and_releases_barrier(self) -> None:
        class FailSecondTransport(MemoryTransport):
            def send(self, message):
                if self.send_count == 1:
                    raise RuntimeError("bridge failed")
                super().send(message)

        scroll_ref = Ref()
        transport = FailSecondTransport()
        runtime = Runtime(
            lambda: _scroll(
                scroll_ref,
                on_click=lambda event: _queue_scroll(scroll_ref, offset=30),
            ),
            transport=transport,
        )
        runtime.mount()

        _dispatch_click(runtime)

        self.assertEqual(runtime.revision, 1)
        self.assertFalse(runtime._coordinator.in_flight)
        self.assertEqual(runtime._effect_pending, [])

    def test_unknown_result_resets_snapshot_without_replaying_effect(self) -> None:
        class SilentTransport:
            preflights_commits = False

            def __init__(self) -> None:
                self.messages: list[dict] = []

            def send(self, message: dict) -> None:
                self.messages.append(message)

        scroll_ref = Ref()
        transport = SilentTransport()
        runtime = Runtime(
            lambda: _scroll(
                scroll_ref,
                on_click=lambda event: _queue_scroll(scroll_ref, offset=40),
            ),
            transport=transport,
        )
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        _dispatch_click(runtime)
        uncertain_revision = runtime.revision

        runtime.report_native_failure(
            revision=uncertain_revision,
            unknown=True,
        )

        self.assertEqual(
            sum(
                operation.get("op") == "scroll_to"
                for message in transport.messages
                for operation in message["ops"]
            ),
            1,
        )
        self.assertEqual(runtime._effect_pending, [])
        self.assertGreater(runtime.revision, uncertain_revision)

    def test_effect_waiting_behind_rejected_commit_is_not_lost(self) -> None:
        class SilentTransport:
            preflights_commits = False

            def __init__(self) -> None:
                self.messages: list[dict] = []

            def send(self, message: dict) -> None:
                self.messages.append(message)

        scroll_ref = Ref()
        clicks = 0

        def app():
            count = state(0)

            def run(event):
                nonlocal clicks
                clicks += 1
                if clicks == 1:
                    count.set(1)
                else:
                    _queue_scroll(scroll_ref, offset=55)

            return Column(
                Scroll(Box(height=1000), ref=scroll_ref, height=100),
                Text(text=str(count.value), on_click=run),
            )

        transport = SilentTransport()
        runtime = Runtime(app, transport=transport)
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        _dispatch_click(runtime, sequence=1)
        tree_revision = runtime.revision
        _dispatch_click(runtime, sequence=2)
        sent = len(transport.messages)

        runtime.report_native_failure(revision=tree_revision, unknown=False)

        self.assertEqual(len(transport.messages), sent + 1)
        self.assertEqual(transport.messages[-1]["ops"][0]["op"], "scroll_to")
        self.assertEqual(transport.messages[-1]["ops"][0]["offset_y"], 55.0)

    def test_foreign_runtime_handle_is_rejected(self) -> None:
        first_ref = Ref()
        second_ref = Ref()
        failure: list[Exception] = []

        first = Runtime(
            lambda: Scroll(Box(height=1000), ref=first_ref, height=100),
            transport=MemoryTransport(),
        )
        first.mount()

        def try_foreign_handle(event):
            try:
                current_runtime()._queue_native_effect(
                    ScrollToEffect(first_ref.current, 0, 10, False)
                )
            except Exception as error:
                failure.append(error)

        second = Runtime(
            lambda: Scroll(
                Box(height=1000),
                ref=second_ref,
                height=100,
                on_click=try_foreign_handle,
            ),
            transport=MemoryTransport(),
        )
        second.mount()
        send_count = second.transport.send_count

        _dispatch_click(second)

        self.assertEqual(second.transport.send_count, send_count)
        self.assertEqual(len(failure), 1)
        self.assertIsInstance(failure[0], ValueError)

    def test_effect_waiting_behind_tree_commit_flushes_after_ack(self) -> None:
        class SilentTransport:
            preflights_commits = False

            def __init__(self) -> None:
                self.messages: list[dict] = []

            def send(self, message: dict) -> None:
                self.messages.append(message)

        scroll_ref = Ref()
        clicks = 0

        def app():
            count = state(0)

            def run(event):
                nonlocal clicks
                clicks += 1
                if clicks == 1:
                    count.set(1)
                else:
                    _queue_scroll(scroll_ref, offset=60)

            return Column(
                Scroll(Box(height=1000), ref=scroll_ref, height=100),
                Text(text=str(count.value), on_click=run),
            )

        transport = SilentTransport()
        runtime = Runtime(app, transport=transport)
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        _dispatch_click(runtime, sequence=1)
        tree_revision = runtime.revision
        sent = len(transport.messages)

        _dispatch_click(runtime, sequence=2)
        self.assertEqual(len(transport.messages), sent)
        self.assertEqual(len(runtime._effect_pending), 1)

        runtime.acknowledge_native_apply(tree_revision)

        self.assertEqual(len(transport.messages), sent + 1)
        self.assertEqual(runtime._effect_pending, [])
        self.assertEqual(transport.messages[-1]["ops"][0]["op"], "scroll_to")

    def test_failing_handler_does_not_publish_queued_effect(self) -> None:
        scroll_ref = Ref()

        def fail(event):
            _queue_scroll(scroll_ref, offset=10)
            raise RuntimeError("stop")

        transport = MemoryTransport()
        runtime = Runtime(lambda: _scroll(scroll_ref, on_click=fail), transport=transport)
        runtime.mount()
        send_count = transport.send_count

        _dispatch_click(runtime)

        self.assertEqual(transport.send_count, send_count)
        self.assertEqual(runtime._effect_pending, [])
        self.assertEqual(runtime._last_error, "stop")


class AsyncRuntimeEffectTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_callback_can_publish_effect_only_commit(self) -> None:
        scroll_ref = Ref()

        async def run(event):
            await asyncio.sleep(0)
            _queue_scroll(scroll_ref, offset=125)

        transport = MemoryTransport()
        runtime = Runtime(lambda: _scroll(scroll_ref, on_click=run), transport=transport)
        runtime.mount()
        send_count = transport.send_count

        _dispatch_click(runtime, sequence=9)
        await runtime._settle_async_callbacks()

        self.assertEqual(transport.send_count, send_count + 1)
        self.assertEqual(runtime.latest_commit["origin_event_seq"], 9)
        self.assertEqual(runtime.latest_commit["ops"][0]["op"], "scroll_to")


if __name__ == "__main__":
    unittest.main()
