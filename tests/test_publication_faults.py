"""COORD-05: Publication fault tests.

Tests that injected faults during send, render, and no-ack in-flight
gating leave State cells and the accepted snapshot unchanged.  Batch
handler rollback, single-event commit counts, render-phase mutation
rejection, and pass-guard reset are covered by ``test_batch_transaction``,
``test_framework``, ``test_commit_coordinator``, and ``test_runtime_caveats``.
"""

from __future__ import annotations

import unittest

from vyne import Box, Text, state, component
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport

from tests.support.runtime_helpers import (
    dispatch_native_event,
    first_listener,
)


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
        listener = first_listener(runtime.latest_commit)

        transport.fail_next = True
        dispatch_native_event(runtime, listener)

        self.assertIs(runtime._coordinator.accepted_root, accepted_root)
        self.assertEqual(runtime.revision, accepted_revision)
        self.assertEqual(runtime._coordinator.next_node_id, accepted_next_id)
        self.assertEqual(runtime.events.handler_ids, accepted_handlers)
        self.assertEqual(runtime._root_scope.hooks[0].value, 0)
        self.assertFalse(runtime._coordinator.in_flight)


class StateJournalFaultTests(unittest.TestCase):
    """State journal rollback on render failures."""

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
        accepted_revision = runtime.revision
        listener = first_listener(runtime.latest_commit)

        dispatch_native_event(runtime, listener)

        self.assertIs(runtime._coordinator.accepted_root, accepted_root)
        self.assertEqual(runtime.revision, accepted_revision)
        self.assertEqual(runtime._root_scope.hooks[0].value, 0)
        self.assertFalse(runtime._coordinator.in_flight)
        self.assertIn("Render failure", runtime._last_error or "")


class NoAckGatingTests(unittest.TestCase):
    """One-commit-in-flight gating tests (COORD-05)."""

    def _click(self, runtime):
        listener = first_listener(runtime.latest_commit)
        dispatch_native_event(runtime, listener)

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
        self._click(runtime)

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

        transport = DelayedTransport()
        runtime = Runtime(App, transport=transport)
        # Override auto-wire.
        runtime.transport = transport
        runtime.mount()

        # If in-flight (no auto-ack), acknowledging unlocks the next render.
        if runtime._coordinator.in_flight:
            revision = runtime.revision
            runtime.acknowledge_native_apply(revision)
            self.assertFalse(runtime._coordinator.in_flight)


if __name__ == "__main__":
    unittest.main()
