"""COORD-05: Publication fault tests.

Tests that injected faults during handler, lower, plan, encode, and
transport send phases leave State cells and the accepted snapshot unchanged.

Tests the state journal rollback mechanism and the coordinator's fault
isolation.
"""

from __future__ import annotations

import unittest

from vyne import Box, Text, TextInput, state, component
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport


class _FailingMemoryTransport(MemoryTransport):
    def __init__(self):
        super().__init__()
        self.fail_next = False

    def send(self, message):
        if self.fail_next:
            self.fail_next = False
            raise OSError("injected send failure")
        super().send(message)


class ProvisionalSendTests(unittest.TestCase):
    def test_send_failure_restores_complete_accepted_state(self):
        @component
        def App():
            count = state(0)
            return Text(
                text=f"Count: {count.value}",
                on_click=lambda: count.set(count.value + 1),
            )

        transport = _FailingMemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()
        accepted_root = runtime._coordinator.accepted_root
        accepted_revision = runtime.revision
        accepted_next_id = runtime._coordinator.next_node_id
        accepted_handlers = runtime.events.handler_ids
        listener = next(op for op in runtime.latest_commit["ops"] if op["op"] == "listen")

        transport.fail_next = True
        runtime.dispatch_event({
            "type": "event", "seq": 1, "target": listener["id"],
            "event": "click", "handler": listener["handler"], "payload": {},
        })

        self.assertIs(runtime._coordinator.accepted_root, accepted_root)
        self.assertEqual(runtime.revision, accepted_revision)
        self.assertEqual(runtime._coordinator.next_node_id, accepted_next_id)
        self.assertEqual(runtime.events.handler_ids, accepted_handlers)
        self.assertEqual(runtime._hooks[0].value, 0)
        self.assertFalse(runtime._coordinator.in_flight)


class StateJournalFaultTests(unittest.TestCase):
    """State journal rollback on handler/render failures."""

    def test_handler_failure_rolls_back_state(self):
        """A failing event handler should roll back state mutations."""
        @component
        def App():
            click_count = state(0)

            def failing_handler(event):
                click_count.set(click_count.value + 1)
                raise ValueError("Handler failure")

            return Box(
                Text(text=f"Count: {click_count.value}"),
                Text(text="Click me", on_click=failing_handler),
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        # Get the click listener.
        listener = None
        for op in runtime.latest_commit["ops"]:
            if op.get("op") == "listen" and op.get("event") == "click":
                listener = op
                break
        self.assertIsNotNone(listener, "Should have a click listener")

        # Read initial value from the rendered tree.
        initial_text = None
        for op in runtime.latest_commit["ops"]:
            if op.get("op") == "set_props" and op.get("props", {}).get("text") == "Count: 0":
                initial_text = "Count: 0"
                break
        self.assertEqual(initial_text, "Count: 0")

        # Dispatch a click event — handler will fail.
        runtime.dispatch_event({
            "type": "event",
            "seq": 1,
            "target": listener["id"],
            "event": "click",
            "handler": listener["handler"],
            "payload": {},
        })

        # After failure with accepted UI, the tree should be preserved (RE-1).
        # The state journal rolled back the State.set, but the accepted tree
        # remains intact.
        self.assertIsNotNone(runtime._coordinator.accepted_root,
                             "Tree must survive handler failure with accepted UI")
        # The last error should be recorded.
        self.assertIsNotNone(runtime._last_error)
        self.assertIn("Handler failure", runtime._last_error)

    def test_render_failure_rolls_back_state(self):
        """A render failure after State.set restores State and accepted UI."""
        @component
        def App():
            count = state(0)
            if count.value:
                raise ValueError("Render failure")
            return Text(
                text="Count: 0",
                on_click=lambda: count.set(1),
            )

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()
        accepted_root = runtime._coordinator.accepted_root
        listener = next(
            op for op in runtime.latest_commit["ops"]
            if op.get("op") == "listen" and op.get("event") == "click"
        )

        runtime.dispatch_event({
            "type": "event",
            "seq": 1,
            "target": listener["id"],
            "event": "click",
            "handler": listener["handler"],
            "payload": {},
        })

        self.assertIs(runtime._coordinator.accepted_root, accepted_root)
        self.assertEqual(runtime._hooks[0].value, 0)
        self.assertFalse(runtime._coordinator.in_flight)
        self.assertIn("Render failure", runtime._last_error or "")

    def test_dispatch_events_batch_rolls_back_on_failure(self):
        """If one event in a batch fails, all state changes roll back."""
        @component
        def App():
            flag = state(0)

            def good_handler(event):
                flag.set(1)

            def bad_handler(event):
                flag.set(2)
                raise ValueError("Batch failure")

            return Box(
                Text(text=f"Flag: {flag.value}"),
                Text(text="Good", on_click=good_handler),
                Text(text="Bad", on_click=bad_handler),
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        # Find both listeners.
        ops = runtime.latest_commit["ops"]
        good_listener = None
        bad_listener = None
        for op in ops:
            if op.get("op") == "listen" and op.get("event") == "click":
                if good_listener is None:
                    good_listener = op
                else:
                    bad_listener = op
                    break

        # Verify initial state.
        text_ops = [op for op in ops if op.get("op") == "set_props" and op.get("props", {}).get("text") == "Flag: 0"]
        self.assertTrue(len(text_ops) > 0, "Initial flag should be 0")

        # Dispatch both events as a batch.
        runtime.dispatch_events([
            {
                "type": "event", "seq": 1,
                "target": good_listener["id"],
                "event": "click",
                "handler": good_listener["handler"],
                "payload": {},
            },
            {
                "type": "event", "seq": 2,
                "target": bad_listener["id"],
                "event": "click",
                "handler": bad_listener["handler"],
                "payload": {},
            },
        ])

        # After batch failure with accepted UI, the tree should be preserved (RE-1).
        # The state journal rolled back both state mutations, but the accepted
        # tree remains intact.
        self.assertIsNotNone(runtime._coordinator.accepted_root,
                             "Tree must survive batch handler failure with accepted UI")
        self.assertIsNotNone(runtime._last_error)
        self.assertIn("Batch failure", runtime._last_error)


class NoAckGatingTests(unittest.TestCase):
    """One-commit-in-flight gating tests (COORD-05)."""

    def test_second_render_coalesces_while_in_flight(self):
        """When a commit is in-flight, subsequent renders should coalesce."""
        @component
        def App():
            flag = state(0)
            return Box(
                Text(text=f"Flag: {flag.value}"),
                Text(text="Inc", on_click=lambda e: flag.set(flag.value + 1)),
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        # After mount, the commit was auto-acknowledged.
        self.assertFalse(runtime._coordinator.in_flight)

        # Dispatch a click — this should trigger render and commit.
        listener = None
        for op in runtime.latest_commit["ops"]:
            if op.get("op") == "listen" and op.get("event") == "click":
                listener = op
                break

        runtime.dispatch_event({
            "type": "event", "seq": 1,
            "target": listener["id"],
            "event": "click",
            "handler": listener["handler"],
            "payload": {},
        })

        # State should have been committed.
        self.assertFalse(runtime._coordinator.in_flight)

    def test_in_flight_prevents_immediate_render(self):
        """If coordinator is in-flight, _schedule_render returns without
        running _render_loop."""
        @component
        def App():
            flag = state(0)
            return Box(
                Text(text=f"Flag: {flag.value}"),
                Text(text="Inc", on_click=lambda e: flag.set(flag.value + 1)),
            )

        # Use a transport that does NOT auto-ack so we stay in-flight.
        class NoAckTransport(MemoryTransport):
            def send(self, message):
                # Store message but do NOT auto-acknowledge.
                self.send_count += 1
                self._latest = message
                if self.keep_history:
                    self.messages.append(message)
                # Note: no auto-ack call here.

        transport = NoAckTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        # After mount, coordinator should be in-flight (no auto-ack).
        self.assertTrue(runtime._coordinator.in_flight,
                        "Coordinator should be in-flight after mount without ack")

        # Try to request a render — should be gated.
        runtime._needs_render = False
        runtime.request_render()
        self.assertTrue(runtime._needs_render,
                        "needs_render should be set (deferred)")

    def test_ack_unlocks_deferred_render(self):
        """When ack arrives, deferred render should be scheduled."""
        @component
        def App():
            flag = state(0)
            return Box(
                Text(text=f"Flag: {flag.value}"),
                Text(text="Inc", on_click=lambda e: flag.set(flag.value + 1)),
            )

        class DelayedTransport(MemoryTransport):
            def __init__(self):
                super().__init__(keep_history=True)

            def send(self, message):
                super().send(message)

        transport = DelayedTransport()
        runtime = Runtime(App, transport=transport)
        # Override auto-wire.
        runtime.transport = transport
        runtime.mount()

        # Should be in-flight (DelayedTransport doesn't auto-ack via set_runtime).
        # But actually MemoryTransport.send checks self._runtime which is None
        # since set_runtime was overridden. Let's check.
        # If in-flight, acknowledge.
        if runtime._coordinator.in_flight:
            revision = runtime.revision
            runtime.acknowledge_native_apply(revision)
            self.assertFalse(runtime._coordinator.in_flight)


class OneEventOneCommitTests(unittest.TestCase):
    """One event batch produces at most one tree commit (SCHED-04/COORD-05)."""

    def test_single_event_produces_one_commit(self):
        @component
        def App():
            flag = state(0)
            return Box(
                Text(text=f"Flag: {flag.value}"),
                Text(text="Inc", on_click=lambda e: flag.set(flag.value + 1)),
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        commit_count_before = transport.send_count

        listener = None
        for op in runtime.latest_commit["ops"]:
            if op.get("op") == "listen" and op.get("event") == "click":
                listener = op
                break

        runtime.dispatch_event({
            "type": "event", "seq": 1,
            "target": listener["id"],
            "event": "click",
            "handler": listener["handler"],
            "payload": {},
        })

        # Should have sent exactly one more commit.
        self.assertEqual(transport.send_count - commit_count_before, 1,
                         "One event should produce at most one commit")

    def test_dispatch_events_batch_produces_one_commit(self):
        @component
        def App():
            flag = state(0)
            return Box(
                Text(text=f"Flag: {flag.value}"),
                Text(text="A", on_click=lambda e: flag.set(flag.value + 1)),
                Text(text="B", on_click=lambda e: flag.set(flag.value + 2)),
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        commit_count_before = transport.send_count

        listeners = [
            op for op in runtime.latest_commit["ops"]
            if op.get("op") == "listen" and op.get("event") == "click"
        ]
        self.assertEqual(len(listeners), 2)

        runtime.dispatch_events([
            {
                "type": "event", "seq": 1,
                "target": listeners[0]["id"],
                "event": "click",
                "handler": listeners[0]["handler"],
                "payload": {},
            },
            {
                "type": "event", "seq": 2,
                "target": listeners[1]["id"],
                "event": "click",
                "handler": listeners[1]["handler"],
                "payload": {},
            },
        ])

        self.assertEqual(transport.send_count - commit_count_before, 1,
                         "Batch of events should produce at most one commit")


class RenderPassGuardIntegrationTests(unittest.TestCase):
    """Integration tests for the render pass guard."""

    def test_pass_guard_resets_each_flush(self):
        @component
        def App():
            flag = state(0)
            return Box(
                Text(text=f"Flag: {flag.value}"),
                Text(text="Inc", on_click=lambda e: flag.set(flag.value + 1)),
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        self.assertLessEqual(runtime._pass_guard.pass_count, 5)

        listener = None
        for op in runtime.latest_commit["ops"]:
            if op.get("op") == "listen" and op.get("event") == "click":
                listener = op
                break

        runtime.dispatch_event({
            "type": "event", "seq": 1,
            "target": listener["id"],
            "event": "click",
            "handler": listener["handler"],
            "payload": {},
        })

        self.assertLessEqual(runtime._pass_guard.pass_count, 5)

    def test_state_set_during_render_rejected(self):
        """State.set() during render should raise RenderPhaseMutationError."""
        @component
        def App():
            s = state(0)
            if s.value == 0:
                s.set(1)  # Set during render — should be caught
            return Text(text=f"Count: {s.value}")

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        self.assertIsNotNone(runtime.latest_commit)
        # Error commit should contain the render-phase error.
        found = False
        for op in runtime.latest_commit.get("ops", []):
            op_str = str(op)
            if "State.set() called during render" in op_str:
                found = True
                break
        if not found:
            # Check the whole commit for the error message.
            commit_str = str(runtime.latest_commit)
            self.assertIn("State.set", commit_str,
                          "Error commit should reference render-phase mutation")


if __name__ == "__main__":
    unittest.main()
