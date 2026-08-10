"""COORD-05: Commit coordinator unit tests.

Tests for the ``CommitCoordinator`` state machine:
- Accepted/candidate/in-flight state transitions.
- One revision in flight enforcement.
- Atomic promotion on matching OK ack.
- Known rejection discards candidate, preserves accepted.
- Unknown-native-state marks for snapshot.
"""

from __future__ import annotations

import unittest

from vyne.scheduler import CommitCoordinator, AcknowledgementMap
from vyne.render_model import RenderNode

from tests.support.runtime_helpers import reserve


def _stage(c: CommitCoordinator, **kwargs) -> RenderNode:
    """Stage the standard single-node candidate used by most tests."""
    root = RenderNode(id=1, kind="Box")
    idx = {1: root}
    c.stage_candidate(root, idx, next_node_id=2, **kwargs)
    return root


class CoordinatorLifecycleTests(unittest.TestCase):
    """Test the basic lifecycle of the coordinator."""

    def test_initial_state_is_empty(self):
        c = CommitCoordinator()
        self.assertIsNone(c.accepted_root)
        self.assertEqual(c.accepted_revision, 0)
        self.assertFalse(c.in_flight)
        self.assertFalse(c.has_candidate())

    def test_stage_and_reserve_candidate(self):
        c = CommitCoordinator()
        root = _stage(c)
        self.assertTrue(c.has_candidate())

        reserve(c, 1)
        self.assertTrue(c.in_flight)
        self.assertEqual(c.in_flight_revision, 1)

    def test_promote_transitions_to_accepted(self):
        c = CommitCoordinator()
        root = _stage(c)
        reserve(c, 1)
        self.assertTrue(c.promote(1))

        self.assertFalse(c.in_flight)
        self.assertFalse(c.has_candidate())
        self.assertIsNotNone(c.accepted_root)
        self.assertEqual(c.accepted_revision, 1)

    def test_promote_stale_revision_ignored(self):
        c = CommitCoordinator()
        root = _stage(c)
        reserve(c, 2)  # revision 2 in flight
        self.assertFalse(c.promote(1))  # stale ack for revision 1
        self.assertTrue(c.in_flight)  # still in flight

    def test_double_ack_does_not_double_promote(self):
        """A duplicate OK ack for an already-promoted revision is ignored."""
        c = CommitCoordinator()
        root = _stage(c)
        reserve(c, 1)
        self.assertTrue(c.promote(1))
        self.assertFalse(c.promote(1))  # duplicate ack
        self.assertFalse(c.in_flight)
        self.assertEqual(c.accepted_revision, 1)

    def test_reject_known_discards_candidate(self):
        c = CommitCoordinator()
        root = _stage(c)
        reserve(c, 1)
        self.assertTrue(c.reject_known(1))

        self.assertFalse(c.in_flight)
        self.assertFalse(c.has_candidate())
        # Accepted should be unchanged (still None / empty).
        self.assertEqual(c.accepted_revision, 0)

    def test_reject_known_stale_ignored(self):
        c = CommitCoordinator()
        root = _stage(c)
        reserve(c, 2)
        self.assertFalse(c.reject_known(1))  # stale
        self.assertTrue(c.in_flight)

    def test_report_unknown_retains_desired_candidate(self):
        c = CommitCoordinator()
        root = _stage(c)
        reserve(c, 1)
        c.report_unknown()

        self.assertFalse(c.in_flight)
        self.assertTrue(c.has_candidate())
        self.assertIs(c.desired_root, root)

    def test_desired_root_falls_back_to_accepted(self):
        c = CommitCoordinator()
        root = _stage(c)
        reserve(c, 1)
        c.promote(1)

        self.assertIs(c.desired_root, root)

    def test_desired_root_exposes_unaccepted_candidate_for_recovery(self):
        c = CommitCoordinator()
        root = _stage(c)
        self.assertIs(c.desired_root, root)
        self.assertIsNone(c.accepted_root)

    def test_desired_root_none_when_empty(self):
        c = CommitCoordinator()
        self.assertIsNone(c.desired_root)

    def test_reserve_without_candidate_raises(self):
        c = CommitCoordinator()
        with self.assertRaises(RuntimeError):
            reserve(c, 1)

    def test_effect_send_reservation_works_without_candidate(self):
        """Effect-only commits use the same provisional receipt barrier."""
        c = CommitCoordinator()
        c.reserve_effect_send(1)
        self.assertTrue(c.in_flight)
        self.assertEqual(c.in_flight_revision, 1)
        c.finish_send(1)

    def test_promote_effect_only_updates_revision(self):
        """Promoting an effect-only in-flight updates revision on accepted."""
        c = CommitCoordinator()
        # Set up initial accepted state.
        root = RenderNode(id=1, kind="Box")
        idx = {1: root}
        c.stage_candidate(root, idx, next_node_id=2)
        reserve(c, 1)
        c.promote(1)

        # Now reserve an effect commit without staging a tree.
        c.reserve_effect_send(2)
        c.finish_send(2)
        promoted = c.promote(2)
        self.assertTrue(promoted)
        self.assertEqual(c.accepted_revision, 2)
        self.assertIsNotNone(c.accepted_root)


class ImperativeBindingPromotionTests(unittest.TestCase):
    def test_bindings_promote_and_report_transition(self):
        coordinator = CommitCoordinator()
        root = RenderNode(id=1, kind="Scroll")
        target = object()
        intent = object()

        coordinator.stage_candidate(
            root,
            {1: root},
            next_node_id=2,
            imperative_bindings={target: intent},
        )
        reserve(coordinator, 1)
        coordinator.promote(1)

        self.assertEqual(
            coordinator.accepted_imperative_bindings,
            {target: intent},
        )
        self.assertEqual(
            coordinator.take_imperative_transition(),
            ({}, {target: intent}),
        )

    def test_rejection_keeps_accepted_bindings(self):
        coordinator = CommitCoordinator()
        root = RenderNode(id=1, kind="Scroll")
        target = object()
        accepted_intent = object()
        rejected_intent = object()
        coordinator.stage_candidate(
            root,
            {1: root},
            next_node_id=2,
            imperative_bindings={target: accepted_intent},
        )
        reserve(coordinator, 1)
        coordinator.promote(1)
        coordinator.take_imperative_transition()

        coordinator.stage_candidate(
            root,
            {1: root},
            next_node_id=2,
            imperative_bindings={target: rejected_intent},
        )
        reserve(coordinator, 2)
        coordinator.reject_known(2)

        self.assertEqual(
            coordinator.accepted_imperative_bindings,
            {target: accepted_intent},
        )
        self.assertIsNone(coordinator.take_imperative_transition())


class RefPromotionTests(unittest.TestCase):
    """Test that Ref attachments/invalidations promote atomically."""

    def test_ref_attachment_promotes_on_ack(self):
        from vyne.refs import Ref

        c = CommitCoordinator()
        ref = Ref()
        root = _stage(c, ref_map={1: ref})
        reserve(c, 1)
        c.promote(1)

        self.assertIn(1, c.ref_map)
        self.assertIs(c.ref_map[1], ref)

    def test_ref_attachment_cleared_on_reject(self):
        from vyne.refs import Ref

        c = CommitCoordinator()
        ref = Ref()
        root = _stage(c, ref_map={1: ref})
        reserve(c, 1)
        c.reject_known(1)

        self.assertNotIn(1, c.ref_map)
        self.assertIsNone(c._candidate_ref_map)

    def test_ref_invalidation_promotes_on_ack(self):
        from vyne.refs import Ref

        c = CommitCoordinator()
        ref = Ref()
        root = RenderNode(id=1, kind="Box")
        idx = {1: root}

        # Set up with ref attached.
        c.stage_candidate(root, idx, next_node_id=2, ref_map={1: ref})
        reserve(c, 1)
        c.promote(1)
        self.assertIn(1, c.ref_map)

        # Now stage a new candidate that removes node 1.
        new_root = RenderNode(id=2, kind="Text")
        c.stage_candidate(new_root, {2: new_root}, next_node_id=3, ref_map={})
        reserve(c, 2)
        c.promote(2)

        self.assertNotIn(1, c.ref_map)

    def test_clear_all_refs_returns_all(self):
        from vyne.refs import Ref

        c = CommitCoordinator()
        ref1 = Ref()
        ref2 = Ref()
        root = RenderNode(id=1, kind="Box")
        idx = {1: root, 2: RenderNode(id=2, kind="Text")}

        c.stage_candidate(root, idx, next_node_id=3, ref_map={1: ref1, 2: ref2})
        reserve(c, 1)
        c.promote(1)

        refs = c.clear_all_refs()
        self.assertEqual(len(refs), 2)
        self.assertEqual(len(c.ref_map), 0)


class AcknowledgementMapTests(unittest.TestCase):
    """Tests for the batch acknowledgement map (SCHED-02)."""

    def test_acknowledge_and_suppress(self):
        ack = AcknowledgementMap()
        ack.acknowledge(1, "text", "Hello")
        self.assertTrue(ack.should_suppress(1, "text", "Hello"))
        self.assertFalse(ack.should_suppress(1, "text", "World"))
        self.assertFalse(ack.should_suppress(2, "text", "Hello"))

    def test_clear_removes_all(self):
        ack = AcknowledgementMap()
        ack.acknowledge(1, "text", "Hello")
        ack.clear()
        self.assertFalse(ack)
        self.assertFalse(ack.should_suppress(1, "text", "Hello"))

    def test_multiple_entries(self):
        ack = AcknowledgementMap()
        ack.acknowledge(1, "text", "Hello")
        ack.acknowledge(2, "focused", True)
        self.assertEqual(len(ack), 2)
        self.assertTrue(ack.should_suppress(1, "text", "Hello"))
        self.assertTrue(ack.should_suppress(2, "focused", True))

    def test_bool_value_suppression(self):
        ack = AcknowledgementMap()
        ack.acknowledge(1, "focused", True)
        self.assertTrue(ack.should_suppress(1, "focused", True))
        self.assertFalse(ack.should_suppress(1, "focused", False))

    def test_none_value_handling(self):
        ack = AcknowledgementMap()
        # acknowledge with None value should store None
        ack.acknowledge(1, "text", None)
        self.assertTrue(ack.should_suppress(1, "text", None))
        self.assertFalse(ack.should_suppress(1, "text", ""))


class StateJournalTests(unittest.TestCase):
    """Tests for the per-flush State journal (COORD-05)."""

    def test_journal_rollback_restores_old_values(self):
        from vyne.scheduler import StateJournal

        # Create a mock state cell.
        class MockState:
            _value = "initial"
        cell = MockState()

        journal = StateJournal()
        journal.begin()
        self.assertTrue(journal.active)

        journal.record(cell, "new_value")
        self.assertEqual(cell._value, "new_value")

        journal.rollback()
        self.assertEqual(cell._value, "initial")
        self.assertFalse(journal.active)

    def test_journal_commit_keeps_values(self):
        from vyne.scheduler import StateJournal

        class MockState:
            _value = "initial"
        cell = MockState()

        journal = StateJournal()
        journal.begin()
        journal.record(cell, "new_value")
        journal.commit()
        self.assertEqual(cell._value, "new_value")
        self.assertFalse(journal.active)

    def test_journal_second_write_to_same_cell_preserves_original(self):
        from vyne.scheduler import StateJournal

        class MockState:
            _value = "initial"
        cell = MockState()

        journal = StateJournal()
        journal.begin()
        journal.record(cell, "first")
        journal.record(cell, "second")
        self.assertEqual(cell._value, "second")

        journal.rollback()
        # Should restore to "initial", not "first".
        self.assertEqual(cell._value, "initial")

    def test_journal_multiple_cells(self):
        from vyne.scheduler import StateJournal

        class MockState:
            pass
        cell1 = MockState()
        cell1._value = "a"
        cell2 = MockState()
        cell2._value = "b"

        journal = StateJournal()
        journal.begin()
        journal.record(cell1, "a2")
        journal.record(cell2, "b2")

        journal.rollback()
        self.assertEqual(cell1._value, "a")
        self.assertEqual(cell2._value, "b")


class PassGuardTests(unittest.TestCase):
    """Tests for the render pass guard (SCHED-03)."""

    def test_guard_allows_up_to_max_passes(self):
        from vyne.scheduler import PassGuard

        guard = PassGuard()
        guard.begin_flush()
        for _ in range(PassGuard.MAX_PASSES_PER_FLUSH):
            guard.enter_pass()  # Should not raise.
        self.assertEqual(guard.pass_count, PassGuard.MAX_PASSES_PER_FLUSH)

    def test_guard_raises_on_exceeding_max(self):
        from vyne.scheduler import PassGuard

        guard = PassGuard()
        guard.begin_flush()
        for _ in range(PassGuard.MAX_PASSES_PER_FLUSH):
            guard.enter_pass()
        with self.assertRaises(RuntimeError):
            guard.enter_pass()

    def test_guard_resets_on_begin_flush(self):
        from vyne.scheduler import PassGuard

        guard = PassGuard()
        guard.begin_flush()
        guard.enter_pass()
        guard.begin_flush()  # Reset
        self.assertEqual(guard.pass_count, 0)


class AckExtractionTests(unittest.TestCase):
    """Schema-driven acknowledgement extraction tests."""

    def test_text_change_extracts_text(self):
        from vyne.scheduler import extract_acknowledgements, AcknowledgementMap

        ack = AcknowledgementMap()
        extract_acknowledgements("text_change", 1, {"text": "Hello"}, ack)
        self.assertTrue(ack.should_suppress(1, "text", "Hello"))

    def test_focus_change_extracts_has_focus(self):
        from vyne.scheduler import extract_acknowledgements, AcknowledgementMap

        ack = AcknowledgementMap()
        extract_acknowledgements("focus_change", 1, {"has_focus": True}, ack)
        self.assertTrue(ack.should_suppress(1, "focused", True))
        self.assertFalse(ack.should_suppress(1, "focused", False))

    def test_unknown_event_is_noop(self):
        from vyne.scheduler import extract_acknowledgements, AcknowledgementMap

        ack = AcknowledgementMap()
        extract_acknowledgements("click", 1, {"x": 10}, ack)
        self.assertFalse(ack)  # Click has no ack mapping.

    def test_focus_change_missing_has_focus_is_noop(self):
        from vyne.scheduler import extract_acknowledgements, AcknowledgementMap

        ack = AcknowledgementMap()
        extract_acknowledgements("focus_change", 1, {}, ack)
        self.assertFalse(ack)

if __name__ == "__main__":
    unittest.main()
