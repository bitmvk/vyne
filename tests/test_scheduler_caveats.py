"""Caveat tests for the scheduler primitives.

CommitCoordinator state-machine misuse, PassGuard bounds, the
AcknowledgementMap suppression contract, StateJournal rollback, and
schema-driven ack extraction.
"""

from __future__ import annotations

import unittest

from vyne.render_model import RenderNode
from vyne.refs import Ref
from vyne.scheduler import (
    AcknowledgementMap,
    CommitCoordinator,
    PassGuard,
    RenderPhaseMutationError,
    StateJournal,
    extract_acknowledgements,
)
from vyne.state import State


def _stage(c: CommitCoordinator, root_id: int = 1, **kwargs) -> RenderNode:
    root = RenderNode(id=root_id, kind="Box")
    c.stage_candidate(root, {root_id: root}, next_node_id=root_id + 1, **kwargs)
    return root


def _reserve(coordinator: CommitCoordinator, revision: int) -> None:
    """Complete the same provisional-send transition used by Runtime."""
    coordinator.reserve_send(revision)
    coordinator.finish_send(revision)


class CoordinatorMisuseTests(unittest.TestCase):
    def test_stage_while_in_flight_rejected(self):
        c = CommitCoordinator()
        _stage(c)
        _reserve(c, 1)
        with self.assertRaisesRegex(RuntimeError, "in flight"):
            _stage(c, root_id=2)

    def test_reserve_without_candidate_rejected(self):
        c = CommitCoordinator()
        with self.assertRaisesRegex(RuntimeError, "provisional"):
            _reserve(c, 1)

    def test_reserve_send_requires_staged_idle_candidate(self):
        c = CommitCoordinator()
        with self.assertRaisesRegex(RuntimeError, "provisional"):
            c.reserve_send(1)
        _stage(c)
        _reserve(c, 1)
        with self.assertRaisesRegex(RuntimeError, "provisional"):
            c.reserve_send(2)

    def test_finish_send_revision_mismatch_rejected(self):
        c = CommitCoordinator()
        _stage(c)
        c.reserve_send(1)
        with self.assertRaisesRegex(RuntimeError, "mismatch"):
            c.finish_send(2)

    def test_promote_stale_revision_returns_false(self):
        c = CommitCoordinator()
        _stage(c)
        _reserve(c, 1)
        self.assertFalse(c.promote(99))
        self.assertTrue(c.promote(1))

    def test_promote_while_provisional_returns_false(self):
        """A synchronous ack during send() is held, not promoted early."""
        c = CommitCoordinator()
        _stage(c)
        c.reserve_send(1)
        self.assertTrue(c.hold_provisional_ack(1))
        self.assertFalse(c.promote(1))  # still provisional
        self.assertTrue(c.finish_send(1))  # reports the held ack
        self.assertTrue(c.promote(1))

    def test_reject_stale_revision_returns_false(self):
        c = CommitCoordinator()
        _stage(c)
        _reserve(c, 1)
        self.assertFalse(c.reject_known(77))
        self.assertTrue(c.reject_known(1))

    def test_abort_send_clears_candidate_and_flight(self):
        c = CommitCoordinator()
        _stage(c)
        c.reserve_send(1)
        self.assertFalse(c.abort_send(2))
        self.assertTrue(c.abort_send(1))
        self.assertFalse(c.in_flight)
        self.assertFalse(c.has_candidate())

    def test_promote_local_requires_no_ops_candidate(self):
        c = CommitCoordinator()
        self.assertFalse(c.promote_local())  # nothing staged
        _stage(c)
        self.assertTrue(c.promote_local())
        self.assertIsNotNone(c.accepted_root)

    def test_staged_candidate_does_not_mutate_accepted_tree(self):
        c = CommitCoordinator()
        accepted = _stage(c)
        _reserve(c, 1)
        c.promote(1)
        candidate = _stage(c, root_id=2)
        candidate.kind = "Text"
        self.assertIs(c.accepted_root, accepted)
        self.assertEqual(c.accepted_root.kind, "Box")

    def test_report_unknown_retains_candidate_for_snapshot(self):
        c = CommitCoordinator()
        _stage(c)
        _reserve(c, 1)
        c.report_unknown()
        self.assertFalse(c.in_flight)
        self.assertTrue(c.has_candidate())  # desired state retained

    def test_reset_accepted_clears_everything(self):
        c = CommitCoordinator()
        ref = Ref()
        _stage(c, ref_map={1: ref})
        _reserve(c, 1)
        c.promote(1)
        c.reset_accepted()
        self.assertIsNone(c.accepted_root)
        self.assertEqual(c.ref_map, {})
        self.assertFalse(c.in_flight)

    def test_discard_staged_only_when_idle(self):
        c = CommitCoordinator()
        _stage(c)
        _reserve(c, 1)
        c.discard_staged()
        self.assertTrue(c.has_candidate())  # in-flight candidates are kept
        c.reject_known(1)
        _stage(c)
        c.discard_staged()
        self.assertFalse(c.has_candidate())

    def test_effect_only_promote_keeps_tree(self):
        c = CommitCoordinator()
        _stage(c)
        _reserve(c, 1)
        c.promote(1)
        # Effect-only commit: in-flight without a tree candidate.
        c.reserve_effect_send(2)
        c.finish_send(2)
        self.assertTrue(c.promote(2))
        self.assertEqual(c.accepted_root.kind, "Box")
        self.assertEqual(c.accepted_revision, 2)


class PassGuardTests(unittest.TestCase):
    def test_trips_after_max_passes(self):
        guard = PassGuard()
        guard.begin_flush()
        for _ in range(PassGuard.MAX_PASSES_PER_FLUSH):
            guard.enter_pass()
        with self.assertRaisesRegex(RuntimeError, "pass limit"):
            guard.enter_pass()

    def test_begin_flush_resets_budget(self):
        guard = PassGuard()
        guard.begin_flush()
        for _ in range(PassGuard.MAX_PASSES_PER_FLUSH):
            guard.enter_pass()
        guard.begin_flush()
        guard.enter_pass()  # must not raise
        self.assertEqual(guard.pass_count, 1)


class AcknowledgementMapTests(unittest.TestCase):
    def test_suppresses_only_equal_values(self):
        ack = AcknowledgementMap()
        ack.acknowledge(1, "text", "hello")
        self.assertTrue(ack.should_suppress(1, "text", "hello"))
        self.assertFalse(ack.should_suppress(1, "text", "HELLO"))
        self.assertFalse(ack.should_suppress(2, "text", "hello"))
        self.assertFalse(ack.should_suppress(1, "other", "hello"))

    def test_acknowledged_value_and_size(self):
        ack = AcknowledgementMap()
        self.assertFalse(ack)
        ack.acknowledge(1, "text", "a")
        ack.acknowledge(1, "focused", True)
        self.assertTrue(ack)
        self.assertEqual(len(ack), 2)
        self.assertEqual(ack.acknowledged_value(1, "text"), "a")
        self.assertIsNone(ack.acknowledged_value(9, "text"))
        ack.clear()
        self.assertFalse(ack)
        self.assertFalse(ack.should_suppress(1, "text", "a"))

    def test_entries_returns_copy(self):
        ack = AcknowledgementMap()
        ack.acknowledge(1, "text", "a")
        ack.entries[(1, "text")] = "mutated"
        self.assertEqual(ack.acknowledged_value(1, "text"), "a")


class StateJournalTests(unittest.TestCase):
    def _state(self, value):
        cell = State(value, lambda: None)
        return cell

    def test_record_applies_optimistically_and_rollback_restores(self):
        journal = StateJournal()
        cell = self._state(1)
        journal.begin()
        journal.record(cell, 2)
        self.assertEqual(cell._value, 2)
        journal.rollback()
        self.assertEqual(cell._value, 1)
        self.assertFalse(journal.active)

    def test_first_write_wins_for_rollback(self):
        """Multiple writes in one flush roll back to the pre-flush value."""
        journal = StateJournal()
        cell = self._state(1)
        journal.begin()
        journal.record(cell, 2)
        journal.record(cell, 3)
        journal.rollback()
        self.assertEqual(cell._value, 1)

    def test_commit_discards_rollback_information(self):
        journal = StateJournal()
        cell = self._state(1)
        journal.begin()
        journal.record(cell, 2)
        journal.commit()
        self.assertFalse(journal.active)
        journal.rollback()  # nothing to roll back
        self.assertEqual(cell._value, 2)

    def test_record_when_inactive_is_noop(self):
        journal = StateJournal()
        cell = self._state(1)
        journal.record(cell, 9)
        # record() applies the value but tracks nothing.
        self.assertEqual(journal.entry_count, 0)

    def test_render_phase_mutation_error_message(self):
        error = RenderPhaseMutationError()
        self.assertIn("render pass", str(error))


class AckExtractionTests(unittest.TestCase):
    def test_text_change_acknowledges_text(self):
        ack = AcknowledgementMap()
        extract_acknowledgements(
            "text_change", 7, {"text": "typed"}, ack,
        )
        self.assertTrue(ack.should_suppress(7, "text", "typed"))

    def test_focus_change_acknowledges_focused(self):
        ack = AcknowledgementMap()
        extract_acknowledgements(
            "focus_change", 3, {"has_focus": True}, ack,
        )
        self.assertTrue(ack.should_suppress(3, "focused", True))

    def test_accessibility_progress_acknowledges_range_current(self):
        ack = AcknowledgementMap()
        extract_acknowledgements(
            "accessibility_progress", 2, {"value": 0.5}, ack,
        )
        self.assertTrue(
            ack.should_suppress(2, "accessibility_range_current", 0.5),
        )

    def test_uncontrolled_event_is_noop(self):
        ack = AcknowledgementMap()
        extract_acknowledgements("click", 1, {}, ack)
        self.assertFalse(ack)

    def test_missing_payload_field_skipped(self):
        ack = AcknowledgementMap()
        extract_acknowledgements("text_change", 1, {}, ack)
        self.assertFalse(ack)


if __name__ == "__main__":
    unittest.main()
