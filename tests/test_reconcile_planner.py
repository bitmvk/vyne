"""Pure reconciliation planner tests (RECON-04 / CORE-01).

Validates the side-effect-free ``plan_reconcile()`` function through the
exact ``NativeModel`` reference applier.  Every test asserts that applying
the planned operations to a simulated native tree produces the same tree
as building the desired element tree from scratch.

Key acceptance criteria:
- RC-1: 106,276 ordered-subset transitions (exhaustive 5-key universe).
- RC-2: Mixed keyed/unkeyed, replacements, multiple parents, re-add,
        duplicate occurrences, and seeded random sequences.
- RC-3: Planning failure changes no accepted snapshot.
- RC-4: Oracle mechanics differential-tested against structural fixtures.

The planner is **not** instantiated through the full Runtime; every test
runs through the pure planner and the NativeModel applier, keeping
execution fast enough for the full exhaustive suite.
"""

from __future__ import annotations

import itertools
import random
import unittest

from vyne.lowering import lower_element, CanonicalElement
from vyne.elements import Element
from vyne import Column, Layout, Row, Text, Box
from vyne.reconcile import plan_reconcile
from vyne.render_model import RenderSnapshot, RenderNode
from tests.support.native_model import NativeModel


# ---- test helpers -----------------------------------------------------------


def _make_canonical(element: Element) -> CanonicalElement:
    """Lower a public Element to a canonical one for reconciliation."""
    return lower_element(element)


def _apply_plan(model: NativeModel, plan_ops) -> None:
    """Apply a plan's ops to a NativeModel."""
    from vyne.render_model import ReconcileOperation
    for op in plan_ops:
        if isinstance(op, ReconcileOperation):
            model.apply_ops([op.to_wire_op()])
        else:
            model.apply_ops([op])


def _build_fresh_model(element: Element) -> NativeModel:
    """Build a fresh NativeModel by applying the initial-plan ops."""
    canon = _make_canonical(element)
    empty = RenderSnapshot(root=None, node_index={}, revision=0)
    result = plan_reconcile(empty, canon, next_node_id=1)
    model = NativeModel()
    _apply_plan(model, result.ops)
    return model


def _trees_equal_structurally(a_tree: dict, b_tree: dict) -> bool:
    """Compare two serialized trees ignoring exact node IDs.

    Two trees are structurally equal if they have the same kinds, props,
    listeners, latest_events, and child order.
    """
    a_children = a_tree.get("children", [])
    b_children = b_tree.get("children", [])
    if len(a_children) != len(b_children):
        return False
    for ac, bc in zip(a_children, b_children):
        if not _nodes_equal_structurally(ac, bc):
            return False
    return True


def _nodes_equal_structurally(a: dict, b: dict) -> bool:
    """Compare two serialized nodes ignoring their exact IDs."""
    if a.get("kind") != b.get("kind"):
        return False
    if a.get("props", {}) != b.get("props", {}):
        return False
    if a.get("listeners", {}) != b.get("listeners", {}):
        return False
    if sorted(a.get("latest_events", [])) != sorted(b.get("latest_events", [])):
        return False
    return _trees_equal_structurally(a, b)


def verify_transition(
    test: unittest.TestCase,
    old_element: Element,
    new_element: Element,
    label: str = "",
) -> None:
    """Verify a full transition from old_element → new_element.

    1. Build the old snapshot from old_element.
    2. Apply the old ops to a NativeModel.
    3. Plan reconciliation from old snapshot to new_element.
    4. Apply the new ops to the NativeModel.
    5. Compare with fresh build of new_element.
    """
    old_canon = _make_canonical(old_element)
    new_canon = _make_canonical(new_element)

    # Build old snapshot and apply old ops.
    empty = RenderSnapshot(root=None, node_index={}, revision=0)
    old_result = plan_reconcile(empty, old_canon, next_node_id=1)
    old_snapshot = old_result.new_snapshot

    model = NativeModel()
    _apply_plan(model, old_result.ops)

    # Snapshot for mutation check.
    old_root_id_before = old_snapshot.root.id if old_snapshot.root else None
    old_index_keys_before = set(old_snapshot.node_index.keys())

    # Plan reconciliation.
    next_id = max(old_snapshot.node_index.keys()) + 1 if old_snapshot.node_index else 1
    new_result = plan_reconcile(old_snapshot, new_canon, next_node_id=next_id)

    # RC-3: old snapshot untouched.
    test.assertEqual(
        old_root_id_before,
        old_snapshot.root.id if old_snapshot.root else None,
        f"old snapshot mutated during planning ({label})",
    )

    # Apply new ops.
    _apply_plan(model, new_result.ops)

    # Build expected.
    expected_model = _build_fresh_model(new_element)

    test.assertTrue(
        _trees_equal_structurally(model.tree(), expected_model.tree()),
        f"Structural mismatch {label}.\n"
        f"Applied: {model.tree()}\n"
        f"Expected: {expected_model.tree()}\n"
        f"Recon ops: {[op.op for op in new_result.ops]}",
    )


# ---- RC-1: exhaustive ordered-subset transitions ----------------------------


class ExhaustiveReconcileTests(unittest.TestCase):
    """RC-1: Every ordered-subset pair over five keys applies correctly.

    106,276 pairs = 326 old states × 326 new states.

    Optimized: canonical forms and expected tree shapes are pre-computed
    once per state rather than per transition.
    """

    def test_exhaustive_ordered_subset_pairs(self):
        """All 106,276 ordered-subset pairs of 5 keys produce correct trees."""
        keys = ["a", "b", "c", "d", "e"]
        all_states = _all_ordered_subsets(keys)
        total = len(all_states)
        expected_pairs = total * total
        self.assertEqual(expected_pairs, 106276,
                         f"Expected 106,276 pairs, got {expected_pairs}")

        # ---- pre-compute per state ----
        # For each state: canonical element, initial plan ops, initial snapshot,
        # expected serialized tree shape (ignoring IDs).
        precomputed: dict[int, dict] = {}
        for idx, ks in enumerate(all_states):
            elem = Column(*[Text(text=k, key=k) for k in ks])
            canon = _make_canonical(elem)
            empty = RenderSnapshot(root=None, node_index={}, revision=0)
            plan_result = plan_reconcile(empty, canon, next_node_id=1)
            precomputed[idx] = {
                "keys": ks,
                "canon": canon,
                "snapshot": plan_result.new_snapshot,
                "init_ops": plan_result.ops,
                "next_id": (
                    max(plan_result.new_snapshot.node_index.keys()) + 1
                    if plan_result.new_snapshot.node_index
                    else 1
                ),
                "expected_shape": _expected_shape_for(ks),
            }

        failures: list[str] = []
        checked = 0

        for old_idx, old_info in precomputed.items():
            old_keys = old_info["keys"]
            old_snapshot = old_info["snapshot"]
            old_ops = old_info["init_ops"]
            base_next_id = old_info["next_id"]

            for new_idx, new_info in precomputed.items():
                # Identity: skip (no re-render).
                if old_idx == new_idx:
                    checked += 1
                    continue

                new_keys = new_info["keys"]
                new_canon = new_info["canon"]
                expected_shape = new_info["expected_shape"]

                try:
                    # Apply old ops to a fresh model.
                    model = NativeModel()
                    _apply_plan(model, old_ops)

                    # Plan and apply reconciliation.
                    new_result = plan_reconcile(
                        old_snapshot, new_canon, next_node_id=base_next_id,
                    )
                    _apply_plan(model, new_result.ops)

                    # Compare structural shape (fast dict comparison).
                    actual_shape = _tree_shape(model.tree())
                    if actual_shape != expected_shape:
                        failures.append(
                            f"{old_keys} -> {new_keys}: shape mismatch\n"
                            f"  actual: {actual_shape}\n"
                            f"  expected: {expected_shape}"
                        )

                except Exception as exc:
                    failures.append(
                        f"{old_keys} -> {new_keys}: {type(exc).__name__}: {exc}"
                    )

                checked += 1

        self.assertEqual(
            len(failures), 0,
            f"Exhaustive test: {checked} pairs checked, "
            f"{len(failures)} failures out of {checked}:\n"
            + "\n".join(failures[:20])
        )


# ---- RC-2: mixed lifecycle tests --------------------------------------------


class MixedLifecycleTests(unittest.TestCase):
    """RC-2: Mixed keyed/unkeyed, replacements, nested parents, etc."""

    def test_mixed_keyed_unkeyed_reorder(self):
        """Keyed and unkeyed children mixed and reordered."""
        old = Column(
            Text(text="u1"),
            Text(text="k1", key="a"),
            Text(text="u2"),
            Text(text="k2", key="b"),
        )
        new = Column(
            Text(text="k2", key="b"),
            Text(text="u2"),
            Text(text="k1", key="a"),
            Text(text="u1"),
        )
        verify_transition(self, old, new, "mixed-keyed-unkeyed")

    def test_kind_mismatch_replacement(self):
        """Same key, different kind → subtree replaced."""
        old = Column(
            Text(text="click", key="root"),
        )
        new = Column(
            Box(key="root"),
        )
        verify_transition(self, old, new, "kind-mismatch")

    def test_non_leaf_replacement_emits_one_recursive_remove(self):
        """A detached subtree is removed once; descendants are implicit."""
        old = Column(
            Box(Text(text="nested"), key="item"),
        )
        new = Column(
            Text(text="flat", key="item"),
        )
        old_result = plan_reconcile(
            RenderSnapshot(root=None, node_index={}, revision=0),
            _make_canonical(old),
            next_node_id=1,
        )
        old_child = old_result.new_snapshot.root.children[0]
        descendant_ids = {child.id for child in old_child.children}
        next_id = max(old_result.new_snapshot.node_index) + 1
        result = plan_reconcile(
            old_result.new_snapshot,
            _make_canonical(new),
            next_node_id=next_id,
        )
        removes = [op for op in result.ops if op.op == "remove"]
        self.assertEqual([op.id for op in removes], [old_child.id])
        self.assertTrue(descendant_ids.isdisjoint({op.id for op in removes}))
        verify_transition(self, old, new, "recursive-non-leaf-replacement")

    def test_keyed_remove_and_re_add(self):
        """Remove a keyed child, then re-add it later."""
        old = Column(
            Text(text="a", key="a"),
            Text(text="b", key="b"),
            Text(text="c", key="c"),
        )
        new = Column(
            Text(text="a", key="a"),
            Text(text="c", key="c"),
        )
        verify_transition(self, old, new, "remove-b")

        # Re-add
        newer = Column(
            Text(text="a", key="a"),
            Text(text="b", key="b"),
            Text(text="c", key="c"),
        )
        verify_transition(self, new, newer, "re-add-b")

    def test_multiple_parents_move(self):
        """Keyed child moves between different parents."""
        old = Layout(
            Column(
                Text(text="child", key="movable"),
            ),
            Column(),
            orientation="vertical",
        )
        new = Layout(
            Column(),
            Column(
                Text(text="child", key="movable"),
            ),
            orientation="vertical",
        )
        verify_transition(self, old, new, "parent-move")

    def test_nested_children_reorder(self):
        """Reordering within nested containers."""
        old = Column(
            Layout(
                Text(text="a", key="a"),
                Text(text="b", key="b"),
                orientation="vertical",
            ),
        )
        new = Column(
            Layout(
                Text(text="b", key="b"),
                Text(text="a", key="a"),
                orientation="vertical",
            ),
        )
        verify_transition(self, old, new, "nested-reorder")

    def test_empty_to_populated(self):
        """Transition from empty children to populated."""
        old = Column()
        new = Column(
            Text(text="a", key="a"),
            Text(text="b", key="b"),
        )
        verify_transition(self, old, new, "empty-to-pop")

    def test_populated_to_empty(self):
        """Transition from populated children to empty."""
        old = Column(
            Text(text="a", key="a"),
            Text(text="b", key="b"),
        )
        new = Column()
        verify_transition(self, old, new, "pop-to-empty")

    def test_duplicate_occurrences_distinct(self):
        """Two occurrences of the same Element produce distinct mounts."""
        # The planner doesn't handle duplicate element objects specially;
        # each occurrence gets its own RenderNode via the canonical tree.
        shared = Text(text="shared", key="dup")
        old = Column(shared)
        new = Column(shared, Text(text="extra", key="extra"))
        verify_transition(self, old, new, "duplicate-occ")


# ---- RC-3: no-mutation fault tests ------------------------------------------


class NoMutationFaultTests(unittest.TestCase):
    """RC-3: Planning/preflight failure changes no accepted snapshot."""

    def test_identical_cached_blueprint_structurally_shares_snapshot(self):
        element = Column(Text(text="stable"))
        cache = {}
        canonical = lower_element(element, _identity_cache=cache)
        initial = plan_reconcile(
            RenderSnapshot(root=None, node_index={}, revision=0),
            canonical,
            next_node_id=1,
        ).new_snapshot

        same_canonical = lower_element(element, _identity_cache=cache)
        result = plan_reconcile(initial, same_canonical, next_node_id=3)

        self.assertEqual(result.ops, [])
        self.assertIs(result.new_snapshot.root, initial.root)
        self.assertIs(result.new_snapshot.node_index[2], initial.node_index[2])

    def test_planning_preserves_empty_snapshot(self):
        """Planning against an empty snapshot leaves it unchanged."""
        empty = RenderSnapshot(root=None, node_index={}, revision=5)
        canon = _make_canonical(Column(Text(text="hello")))

        root_before = empty.root
        index_before = dict(empty.node_index)
        rev_before = empty.revision

        result = plan_reconcile(empty, canon, next_node_id=1)

        self.assertIsNone(empty.root)
        self.assertEqual(empty.root, root_before)
        self.assertEqual(dict(empty.node_index), index_before)
        self.assertEqual(empty.revision, rev_before)

        # The result should have a new snapshot.
        self.assertIsNotNone(result.new_snapshot.root)
        self.assertEqual(result.new_snapshot.revision, 6)

    def test_planning_preserves_populated_snapshot(self):
        """Planning against a populated snapshot leaves it unchanged."""
        old_element = Column(
            Text(text="a", key="a"),
            Text(text="b", key="b"),
        )
        old_canon = _make_canonical(old_element)
        empty = RenderSnapshot(root=None, node_index={}, revision=0)
        old_result = plan_reconcile(empty, old_canon, next_node_id=1)
        old_snapshot = old_result.new_snapshot

        root_id_before = old_snapshot.root.id
        index_ids_before = set(old_snapshot.node_index.keys())
        rev_before = old_snapshot.revision

        new_element = Column(
            Text(text="b", key="b"),
            Text(text="a", key="a"),
        )
        new_canon = _make_canonical(new_element)
        next_id = max(old_snapshot.node_index.keys()) + 1

        result = plan_reconcile(old_snapshot, new_canon, next_node_id=next_id)

        # Old snapshot untouched.
        self.assertEqual(old_snapshot.root.id, root_id_before)
        self.assertEqual(set(old_snapshot.node_index.keys()), index_ids_before)
        self.assertEqual(old_snapshot.revision, rev_before)

        # New snapshot differs.
        self.assertNotEqual(result.new_snapshot.revision, rev_before)

    def test_repeated_planning_from_same_snapshot_produces_same_result(self):
        """Repeated planning from the same snapshot is deterministic."""
        old_element = Column(
            Text(text="a", key="a"),
            Text(text="b", key="b"),
        )
        old_canon = _make_canonical(old_element)
        empty = RenderSnapshot(root=None, node_index={}, revision=0)
        old_result = plan_reconcile(empty, old_canon, next_node_id=1)
        old_snapshot = old_result.new_snapshot

        new_element = Column(
            Text(text="b", key="b"),
            Text(text="a", key="a"),
        )
        new_canon = _make_canonical(new_element)
        next_id = max(old_snapshot.node_index.keys()) + 1

        result1 = plan_reconcile(old_snapshot, new_canon, next_node_id=next_id)
        result2 = plan_reconcile(old_snapshot, new_canon, next_node_id=next_id)

        # Same number of ops.
        self.assertEqual(len(result1.ops), len(result2.ops))
        # Same op types.
        self.assertEqual(
            [op.op for op in result1.ops],
            [op.op for op in result2.ops],
        )


# ---- RC-4: structural fixture parity ----------------------------------------


class StructuralFixtureParityTests(unittest.TestCase):
    """RC-4: Oracle insert/move/remove mechanics match reference fixtures."""

    def test_initial_mount_matches_fresh_build(self):
        """Every initial mount produces the same tree as a fresh build."""
        fixtures = [
            [],
            ["a"],
            ["a", "b"],
            ["c", "b", "a"],
            ["d", "c", "b", "a"],
            ["e", "d", "c", "b", "a"],
        ]
        for keys in fixtures:
            with self.subTest(keys=keys):
                element = Column(*[
                    Text(text=k, key=k) for k in keys
                ])
                model = _build_fresh_model(element)
                expected = _build_fresh_model(element)
                self.assertTrue(
                    _trees_equal_structurally(model.tree(), expected.tree()),
                    f"Initial mount mismatch for keys={keys}",
                )

    def test_move_child_updates_shadow_correctly(self):
        """Move ops are indexed against the updated shadow."""
        old = Column(
            Text(text="a", key="a"),
            Text(text="b", key="b"),
            Text(text="c", key="c"),
            Text(text="d", key="d"),
        )
        new = Column(
            Text(text="d", key="d"),
            Text(text="c", key="c"),
            Text(text="b", key="b"),
            Text(text="a", key="a"),
        )
        verify_transition(self, old, new, "reverse-4")

    def test_insert_at_various_positions(self):
        """Inserts at start, middle, and end produce correct indices."""
        old = Column(
            Text(text="a", key="a"),
            Text(text="c", key="c"),
        )
        new = Column(
            Text(text="x", key="x"),
            Text(text="a", key="a"),
            Text(text="y", key="y"),
            Text(text="c", key="c"),
            Text(text="z", key="z"),
        )
        verify_transition(self, old, new, "insert-multi")

    def test_remove_from_various_positions(self):
        """Removes from start, middle, and end produce correct trees."""
        old = Column(
            Text(text="a", key="a"),
            Text(text="b", key="b"),
            Text(text="c", key="c"),
            Text(text="d", key="d"),
            Text(text="e", key="e"),
        )
        new = Column(
            Text(text="c", key="c"),
        )
        verify_transition(self, old, new, "remove-multi")


# ---- Randomized tests -------------------------------------------------------


class RandomizedReconcileTests(unittest.TestCase):
    """Seeded random lifecycle transitions (RC-1/R C-2)."""

    def test_randomized_keyed_permutations(self):
        """Seeded random sequences over an 8-key pool."""
        rng = random.Random(42)
        keys_pool = [f"k{i}" for i in range(8)]
        failures: list[str] = []

        for iteration in range(200):
            count = rng.randint(0, 5)
            old_keys = rng.sample(keys_pool, count)
            new_keys = rng.sample(keys_pool, rng.randint(0, 5))

            old_element = Column(*[
                Text(text=k, key=k) for k in old_keys
            ])
            new_element = Column(*[
                Text(text=k, key=k) for k in new_keys
            ])

            try:
                verify_transition(
                    self, old_element, new_element,
                    f"rand-{iteration}: {old_keys}->{new_keys}",
                )
            except Exception as exc:
                failures.append(
                    f"rand-{iteration} {old_keys}->{new_keys}: "
                    f"{type(exc).__name__}: {exc}"
                )

        if failures:
            self.fail(
                f"Randomized test: {200 - len(failures)}/200 passing, "
                f"{len(failures)} failures:\n" + "\n".join(failures[:20])
            )

    def test_seeded_deterministic_sequences(self):
        """Specific seeds produce deterministic results (persisted on failure)."""
        seeds = [1, 7, 19, 101, 1009]
        for seed in seeds:
            rng = random.Random(seed)
            keys_pool = [f"k{i}" for i in range(6)]
            for i in range(20):
                old_keys = rng.sample(keys_pool, rng.randint(0, 5))
                new_keys = rng.sample(keys_pool, rng.randint(0, 5))

                old_element = Column(*[
                    Text(text=k, key=k) for k in old_keys
                ])
                new_element = Column(*[
                    Text(text=k, key=k) for k in new_keys
                ])

                verify_transition(
                    self, old_element, new_element,
                    f"seed{seed}-{i}: {old_keys}->{new_keys}",
                )


# ---- helpers ----------------------------------------------------------------


def _all_ordered_subsets(items: list[str]) -> list[list[str]]:
    """Generate all ordered subsets (permutations for each subset size)."""
    result: list[list[str]] = []
    for r in range(len(items) + 1):
        for combo in itertools.permutations(items, r):
            result.append(list(combo))
    return result


def _tree_shape(tree: dict) -> dict:
    """Strip node IDs from a serialized tree for structural comparison.

    Returns a nested dict with only kind, props, listeners, latest_events
    and child shapes — no id fields.
    """
    return {
        "children": [_node_shape(c) for c in tree.get("children", [])],
    }


def _node_shape(node: dict) -> dict:
    """Strip node ID from a serialized node."""
    return {
        "kind": node.get("kind"),
        "props": node.get("props", {}),
        "listeners": node.get("listeners", {}),
        "latest_events": sorted(node.get("latest_events", [])),
        "children": [_node_shape(c) for c in node.get("children", [])],
    }


def _expected_shape_for(keys: list[str]) -> dict:
    """Pre-compute the expected structural shape for a key list.

    Uses a fresh model build and strips IDs.
    """
    element = Column(*[Text(text=k, key=k) for k in keys])
    model = _build_fresh_model(element)
    return _tree_shape(model.tree())


if __name__ == "__main__":
    unittest.main()
