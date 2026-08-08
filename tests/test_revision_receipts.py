"""Revision receipt tests (RECOVER-07 / RE-2).

Tests that stale success/failure, null revision, and reordered receipts
cannot promote or reset current state in either the coordinator or the
runtime.
"""

from __future__ import annotations

import unittest

from vyne.recovery import RecoveryState
from vyne.runtime import Runtime
from vyne.scheduler import CommitCoordinator
from vyne.transport import MemoryTransport


def _reserve(coordinator: CommitCoordinator, revision: int) -> None:
    """Complete the same provisional-send transition used by Runtime."""
    coordinator.reserve_send(revision)
    coordinator.finish_send(revision)


class StaleRevisionTests(unittest.TestCase):
    """Stale revision acknowledgements must not affect current state."""

    def test_stale_ok_does_not_promote(self):
        """A stale OK ack must not promote a newer revision."""
        c = CommitCoordinator()
        from vyne.render_model import RenderNode

        # Stage and publish rev 10.
        r10 = RenderNode(id=1, kind="Layout", parent_id=0)
        c.stage_candidate(r10, {1: r10}, next_node_id=2)
        _reserve(c, 10)
        self.assertTrue(c.in_flight)
        self.assertEqual(c.in_flight_revision, 10)

        # Stale ack for rev 5.
        self.assertFalse(c.promote(5))
        self.assertTrue(c.in_flight)
        self.assertEqual(c.in_flight_revision, 10)

        # Correct ack for rev 10.
        self.assertTrue(c.promote(10))
        self.assertFalse(c.in_flight)
        self.assertEqual(c.accepted_revision, 10)

    def test_stale_rejection_does_not_discard_current(self):
        """A stale rejection must not discard the current in-flight."""
        c = CommitCoordinator()
        from vyne.render_model import RenderNode

        r = RenderNode(id=1, kind="Layout", parent_id=0)
        c.stage_candidate(r, {1: r}, next_node_id=2)
        _reserve(c, 20)

        # Reject a different revision.
        self.assertFalse(c.reject_known(19))
        self.assertTrue(c.in_flight)
        self.assertEqual(c.in_flight_revision, 20)

        # Reject the correct revision.
        self.assertTrue(c.reject_known(20))
        self.assertFalse(c.in_flight)

    def test_double_ack_does_not_double_promote(self):
        """Receiving the same ack twice must not cause issues."""
        c = CommitCoordinator()
        from vyne.render_model import RenderNode

        r = RenderNode(id=1, kind="Layout", parent_id=0)
        c.stage_candidate(r, {1: r}, next_node_id=2)
        _reserve(c, 1)
        self.assertTrue(c.promote(1))
        self.assertFalse(c.in_flight)

        # Second ack for same revision (already promoted).
        self.assertFalse(c.promote(1))
        self.assertFalse(c.in_flight)
        self.assertEqual(c.accepted_revision, 1)


class NullRevisionTests(unittest.TestCase):
    """Null or missing revision cannot promote or reset state."""

    def test_promote_null_does_nothing(self):
        """Promoting revision 0 when in-flight is nonzero fails."""
        c = CommitCoordinator()
        c._in_flight_revision = 7
        self.assertFalse(c.promote(0))
        self.assertTrue(c.in_flight)

    def test_promote_negative_does_nothing(self):
        """Promoting a negative revision fails."""
        c = CommitCoordinator()
        c._in_flight_revision = 3
        self.assertFalse(c.promote(-1))
        self.assertTrue(c.in_flight)

    def test_reject_null_does_nothing(self):
        """Rejecting revision 0 when in-flight is nonzero fails."""
        c = CommitCoordinator()
        c._in_flight_revision = 7
        self.assertFalse(c.reject_known(0))
        self.assertTrue(c.in_flight)

    def test_promote_with_no_in_flight(self):
        """Promoting when nothing is in-flight fails."""
        c = CommitCoordinator()
        self.assertFalse(c.in_flight)
        self.assertFalse(c.promote(1))


class ReorderedReceiptTests(unittest.TestCase):
    """Reordered receipts must not corrupt state."""

    def test_late_ack_between_revisions(self):
        """Late ack for prior revision after new one in-flight."""
        c = CommitCoordinator()
        from vyne.render_model import RenderNode

        # R1: publish and promote.
        r1 = RenderNode(id=1, kind="Layout", parent_id=0,
                        props={"orientation": "vertical"})
        c.stage_candidate(r1, {1: r1}, next_node_id=2)
        _reserve(c, 1)
        self.assertTrue(c.promote(1))
        self.assertEqual(c.accepted_revision, 1)

        # R2: publish but not yet promoted.
        r2 = RenderNode(id=1, kind="Layout", parent_id=0,
                        props={"orientation": "horizontal"})
        c.stage_candidate(r2, {1: r2}, next_node_id=2)
        _reserve(c, 2)
        self.assertTrue(c.in_flight)
        self.assertEqual(c.in_flight_revision, 2)

        # Late ack for R1.
        self.assertFalse(c.promote(1))
        self.assertTrue(c.in_flight)
        self.assertEqual(c.in_flight_revision, 2)

        # Correct ack for R2.
        self.assertTrue(c.promote(2))
        self.assertFalse(c.in_flight)
        self.assertEqual(c.accepted_revision, 2)

    def test_failure_then_late_success(self):
        """Failure ack processed, then a late success ack must be ignored."""
        c = CommitCoordinator()
        from vyne.render_model import RenderNode

        r = RenderNode(id=1, kind="Layout", parent_id=0)
        c.stage_candidate(r, {1: r}, next_node_id=2)
        _reserve(c, 5)

        # Failure for rev 5.
        self.assertTrue(c.reject_known(5))
        self.assertFalse(c.in_flight)

        # Late success for rev 5 (already rejected).
        self.assertFalse(c.promote(5))
        self.assertFalse(c.in_flight)


class RuntimeRevisionIntegrationTests(unittest.TestCase):
    """Revision receipts integrated with Runtime."""

    def test_runtime_ignores_stale_ack(self):
        """Runtime.acknowledge_native_apply ignores stale revision."""
        transport = MemoryTransport()
        runtime = Runtime(
            lambda: __import__("vyne").Text(text="test"),
            transport=transport,
        )
        runtime.mount()

        # Mount produced a commit which was auto-acked by MemoryTransport.
        # Runtime should now be AWAITING_APPLY (auto-acked).
        # Now send a stale ack.
        runtime.acknowledge_native_apply(999)
        # Must not crash or change recovery state incorrectly.
        self.assertNotEqual(runtime._recovery_state, RecoveryState.DISPOSED)

    def test_runtime_ignores_revisionless_native_failure(self):
        """A failure without exact correlation cannot mutate lifecycle state."""
        transport = MemoryTransport()
        runtime = Runtime(
            lambda: __import__("vyne").Text(text="test"),
            transport=transport,
        )
        runtime.mount()

        prev_revision = runtime.revision

        runtime.report_native_failure("uncorrelated failure")

        self.assertEqual(runtime.revision, prev_revision)
        self.assertEqual(runtime._recovery_state, RecoveryState.SYNCED)

    def test_runtime_multiple_successive_stale_acks(self):
        """Multiple stale acks in sequence must not accumulate state."""
        transport = MemoryTransport()
        runtime = Runtime(
            lambda: __import__("vyne").Text(text="test"),
            transport=transport,
        )
        runtime.mount()

        for i in range(10):
            runtime.acknowledge_native_apply(i)
        # Must not crash or change recovery state unexpectedly.
        self.assertIsNotNone(runtime._coordinator.accepted_root)

    def test_runtime_successive_native_failures(self):
        """Multiple native failure reports must not cause undefined behavior."""
        transport = MemoryTransport()
        runtime = Runtime(
            lambda: __import__("vyne").Text(text="resilient"),
            transport=transport,
        )
        runtime.mount()

        prev_revision = runtime.revision
        for i in range(3):
            runtime.report_native_failure(f"failure {i}")
        # Uncorrelated failures are ignored and cannot consume a revision.
        self.assertEqual(runtime.revision, prev_revision)
        self.assertIsNotNone(runtime._coordinator.accepted_root)


if __name__ == "__main__":
    unittest.main()
