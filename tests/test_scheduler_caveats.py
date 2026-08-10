"""Caveat tests for the scheduler primitives.

CommitCoordinator state-machine misuse, PassGuard bounds, the
AcknowledgementMap suppression contract, StateJournal rollback, and
schema-driven ack extraction.

Lifecycle-transition, journal, guard-budget, and ack-extraction happy
paths are covered by ``test_commit_coordinator.py``; this file keeps only
the misuse/caveat angles that file does not already pin.
"""

from __future__ import annotations

import unittest

from vyne.render_model import RenderNode
from vyne.refs import Ref
from vyne.scheduler import (
    AcknowledgementMap,
    CommitCoordinator,
    RenderPhaseMutationError,
    StateJournal,
    extract_acknowledgements,
)
from vyne.state import State

from tests.support.runtime_helpers import reserve


def _stage(c: CommitCoordinator, root_id: int = 1, **kwargs) -> RenderNode:
    root = RenderNode(id=root_id, kind="Box")
    c.stage_candidate(root, {root_id: root}, next_node_id=root_id + 1, **kwargs)
    return root


class CoordinatorMisuseTests(unittest.TestCase):
    def test_stage_while_in_flight_rejected(self):
        c = CommitCoordinator()
        _stage(c)
        reserve(c, 1)
        with self.assertRaisesRegex(RuntimeError, "in flight"):
            _stage(c, root_id=2)

    def test_reserve_send_requires_staged_idle_candidate(self):
        c = CommitCoordinator()
        with self.assertRaisesRegex(RuntimeError, "provisional"):
            c.reserve_send(1)
        _stage(c)
        reserve(c, 1)
        with self.assertRaisesRegex(RuntimeError, "provisional"):
            c.reserve_send(2)

    def test_finish_send_revision_mismatch_rejected(self):
        c = CommitCoordinator()
        _stage(c)
        c.reserve_send(1)
        with self.assertRaisesRegex(RuntimeError, "mismatch"):
            c.finish_send(2)

    def test_promote_while_provisional_returns_false(self):
        """A synchronous ack during send() is held, not promoted early."""
        c = CommitCoordinator()
        _stage(c)
        c.reserve_send(1)
        self.assertTrue(c.hold_provisional_ack(1))
        self.assertFalse(c.promote(1))  # still provisional
        self.assertTrue(c.finish_send(1))  # reports the held ack
        self.assertTrue(c.promote(1))

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
        reserve(c, 1)
        c.promote(1)
        candidate = _stage(c, root_id=2)
        candidate.kind = "Text"
        self.assertIs(c.accepted_root, accepted)
        self.assertEqual(c.accepted_root.kind, "Box")

    def test_reset_accepted_clears_everything(self):
        c = CommitCoordinator()
        ref = Ref()
        _stage(c, ref_map={1: ref})
        reserve(c, 1)
        c.promote(1)
        c.reset_accepted()
        self.assertIsNone(c.accepted_root)
        self.assertEqual(c.ref_map, {})
        self.assertFalse(c.in_flight)

    def test_discard_staged_only_when_idle(self):
        c = CommitCoordinator()
        _stage(c)
        reserve(c, 1)
        c.discard_staged()
        self.assertTrue(c.has_candidate())  # in-flight candidates are kept
        c.reject_known(1)
        _stage(c)
        c.discard_staged()
        self.assertFalse(c.has_candidate())


class AcknowledgementMapTests(unittest.TestCase):
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
    def test_record_when_inactive_is_noop(self):
        journal = StateJournal()
        cell = State(1, lambda: None)
        journal.record(cell, 9)
        # record() applies the value but tracks nothing.
        self.assertEqual(journal.entry_count, 0)

    def test_render_phase_mutation_error_message(self):
        error = RenderPhaseMutationError()
        self.assertIn("render pass", str(error))


class AckExtractionTests(unittest.TestCase):
    def test_accessibility_progress_acknowledges_range_current(self):
        ack = AcknowledgementMap()
        extract_acknowledgements(
            "accessibility_progress", 2, {"value": 0.5}, ack,
        )
        self.assertTrue(
            ack.should_suppress(2, "accessibility_range_current", 0.5),
        )


if __name__ == "__main__":
    unittest.main()
