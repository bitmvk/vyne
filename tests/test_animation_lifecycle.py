"""Ordered control-plane and native lifecycle animation tests."""

from __future__ import annotations

import asyncio
import unittest

from vyne import AnimationEvent, AnimationHandle, Text, animate, state
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport


def _click(runtime: Runtime, sequence: int = 1) -> None:
    target, node = next(
        (node_id, node)
        for node_id, node in runtime._coordinator.accepted_index.items()
        if "click" in node.listeners
    )
    runtime.dispatch_event({
        "type": "event",
        "seq": sequence,
        "target": target,
        "event": "click",
        "handler": node.listeners["click"],
        "payload": {},
    })


def _lifecycle(
    handle: AnimationHandle,
    status: str,
    *,
    reason: str | None = None,
    sequence: int = 2,
) -> dict:
    payload = {
        "type": "animation_lifecycle",
        "animation_id": handle.id,
        "status": status,
        "node_id": handle.slot.node_id,
        "property": handle.slot.property,
    }
    if reason is not None:
        payload["reason"] = reason
    return {
        "type": "event",
        "seq": sequence,
        "target": handle.slot.node_id,
        "event": "__vyne_system__",
        "handler": 0,
        "payload": payload,
    }


class AnimationLifecycleTests(unittest.TestCase):
    def test_handle_becomes_running_after_commit_acceptance(self):
        handles: list[AnimationHandle] = []

        def app():
            return Text(
                text="go",
                on_click=lambda event: handles.append(
                    animate(event.target, "alpha", to=0.25)
                ),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        _click(runtime)

        self.assertEqual(handles[0].status, "running")
        operation = runtime.latest_commit["ops"][0]
        self.assertEqual(operation["animation_id"], handles[0].id)
        self.assertEqual(operation["property"], "opacity")

    def test_completion_updates_handle_and_invokes_callback_once(self):
        completed: list[AnimationEvent] = []
        handles: list[AnimationHandle] = []

        def app():
            return Text(
                text="go",
                on_click=lambda event: handles.append(
                    animate(
                        event.target,
                        "opacity",
                        to=0.25,
                        on_complete=completed.append,
                    )
                ),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        _click(runtime)
        handle = handles[0]

        runtime.dispatch_event(_lifecycle(handle, "completed"))
        runtime.dispatch_event(_lifecycle(handle, "completed", sequence=3))

        self.assertTrue(handle.done)
        self.assertEqual(handle.status, "completed")
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].animation_id, handle.id)
        self.assertNotIn(handle.id, runtime._animations)

    def test_cancel_is_generation_safe_and_uses_ordered_commit(self):
        handles: list[AnimationHandle] = []

        def app():
            return Text(
                text="go",
                on_click=lambda event: handles.append(
                    animate(event.target, "opacity", to=0.25)
                ),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        _click(runtime)
        handle = handles[0]

        runtime._phase = "event"
        try:
            self.assertTrue(handle.cancel())
            runtime._flush_batched_render(None)
        finally:
            runtime._phase = None

        operation = runtime.latest_commit["ops"][0]
        self.assertEqual(operation["op"], "motion_cancel")
        self.assertEqual(operation["animation_id"], handle.id)
        runtime.dispatch_event(
            _lifecycle(handle, "cancelled", reason="cancelled")
        )
        self.assertEqual(handle.status, "cancelled")
        self.assertFalse(handle.cancel())

    def test_late_old_lifecycle_does_not_finish_replacement(self):
        handles: list[AnimationHandle] = []

        def app():
            return Text(
                text="go",
                on_click=lambda event: handles.append(
                    animate(event.target, "opacity", to=0.2 * (len(handles) + 1))
                ),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        _click(runtime, 1)
        _click(runtime, 2)

        first, second = handles
        runtime.dispatch_event(
            _lifecycle(first, "cancelled", reason="replaced", sequence=3)
        )
        self.assertEqual(first.status, "cancelled")
        self.assertEqual(second.status, "running")

    def test_async_completion_callback_renders_in_a_later_commit(self):
        handles: list[AnimationHandle] = []

        def app():
            finished = state(False)

            async def on_complete():
                await asyncio.sleep(0)
                finished.set(True)

            return Text(
                text="done" if finished.value else "running",
                on_click=lambda event: handles.append(
                    animate(
                        event.target,
                        "opacity",
                        to=0.5,
                        on_complete=on_complete,
                    )
                ),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        _click(runtime)
        animation_revision = runtime.revision
        runtime.dispatch_event(_lifecycle(handles[0], "completed"))
        self.assertTrue(runtime.wait_for_async_callbacks(timeout=2))

        self.assertGreater(runtime.revision, animation_revision)
        text_updates = [
            operation
            for operation in runtime.latest_commit["ops"]
            if operation.get("op") == "set_prop"
            and operation.get("name") == "text"
        ]
        self.assertEqual(text_updates[-1]["value"], "done")

    def test_animation_queued_by_failing_handler_is_rolled_back(self):
        handles: list[AnimationHandle] = []

        def fail(event):
            handles.append(animate(event.target, "opacity", to=0.5))
            raise RuntimeError("handler failed")

        runtime = Runtime(
            lambda: Text(text="go", on_click=fail),
            transport=MemoryTransport(),
        )
        runtime.mount()
        revision = runtime.revision
        _click(runtime)

        self.assertEqual(runtime.revision, revision)
        self.assertEqual(handles[0].status, "rejected")
        self.assertEqual(runtime._anim_pending, [])
        self.assertEqual(runtime._animations, {})

    def test_cancel_queued_by_failing_handler_is_rolled_back(self):
        handles: list[AnimationHandle] = []

        def click(event):
            if not handles:
                handles.append(animate(event.target, "opacity", to=0.5))
                return
            self.assertTrue(handles[0].cancel())
            raise RuntimeError("cancel transaction failed")

        runtime = Runtime(
            lambda: Text(text="go", on_click=click),
            transport=MemoryTransport(),
        )
        runtime.mount()
        _click(runtime)
        handle = handles[0]
        self.assertEqual(handle.status, "running")

        _click(runtime, sequence=2)

        self.assertEqual(handle.status, "running")
        self.assertEqual(runtime._anim_pending, [])
        self.assertIs(runtime._animations[handle.id].handle, handle)

    def test_apply_receipt_closes_before_lifecycle_callback_transaction(self):
        class SilentTransport:
            def __init__(self):
                self.messages = []

            def send(self, message):
                self.messages.append(message)

        handles: list[AnimationHandle] = []

        def app():
            finished = state(False)
            return Text(
                text="done" if finished.value else "running",
                on_click=lambda event: handles.append(
                    animate(
                        event.target,
                        "opacity",
                        to=0.5,
                        on_complete=lambda: finished.set(True),
                    )
                ),
            )

        transport = SilentTransport()
        runtime = Runtime(app, transport=transport)
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        _click(runtime)
        animation_revision = runtime.revision
        handle = handles[0]

        receipt = {
            "type": "event",
            "seq": 0,
            "target": 0,
            "event": "__vyne_system__",
            "handler": 0,
            "payload": {
                "type": "native_apply_result",
                "result": "ok",
                "revision": animation_revision,
                "session": runtime.session_id,
            },
        }
        runtime.dispatch_events([
            receipt,
            _lifecycle(handle, "completed", sequence=4),
        ])

        self.assertEqual(handle.status, "completed")
        self.assertGreater(runtime.revision, animation_revision)
        self.assertEqual(runtime.recovery_state.name, "AWAITING_APPLY")

    def test_animation_transport_failure_rolls_back_registration_and_barrier(self):
        class FailSecondTransport(MemoryTransport):
            def send(self, message):
                if self.send_count == 1:
                    raise RuntimeError("bridge failed")
                super().send(message)

        handles: list[AnimationHandle] = []
        transport = FailSecondTransport()
        runtime = Runtime(
            lambda: Text(
                text="go",
                on_click=lambda event: handles.append(
                    animate(event.target, "opacity", to=0.5)
                ),
            ),
            transport=transport,
        )
        runtime.mount()
        _click(runtime)

        self.assertEqual(runtime.revision, 1)
        self.assertFalse(runtime._coordinator.in_flight)
        self.assertEqual(handles[0].status, "rejected")
        self.assertEqual(runtime._animations, {})
        self.assertEqual(runtime._anim_pending, [])

    def test_known_native_rejection_marks_unstarted_handle_rejected(self):
        class SilentTransport:
            def __init__(self):
                self.messages = []

            def send(self, message):
                self.messages.append(message)

        handles: list[AnimationHandle] = []
        runtime = Runtime(
            lambda: Text(
                text="go",
                on_click=lambda event: handles.append(
                    animate(event.target, "opacity", to=0.5)
                ),
            ),
            transport=SilentTransport(),
        )
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        _click(runtime)
        runtime.report_native_failure(
            revision=runtime.revision,
            unknown=False,
        )

        self.assertEqual(handles[0].status, "rejected")
        self.assertEqual(runtime._animations, {})

    def test_unknown_native_result_does_not_leave_handle_running_forever(self):
        class SilentTransport:
            def __init__(self):
                self.messages = []

            def send(self, message):
                self.messages.append(message)

        handles: list[AnimationHandle] = []
        runtime = Runtime(
            lambda: Text(
                text="go",
                on_click=lambda event: handles.append(
                    animate(event.target, "opacity", to=0.5)
                ),
            ),
            transport=SilentTransport(),
        )
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        _click(runtime)
        animation_revision = runtime.revision

        runtime.report_native_failure(
            revision=animation_revision,
            unknown=True,
        )

        self.assertEqual(handles[0].status, "rejected")
        self.assertEqual(handles[0].reason, "native_state_unknown")
        self.assertNotIn(handles[0].id, runtime._animations)


if __name__ == "__main__":
    unittest.main()
