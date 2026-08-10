"""Reconciliation acceptance tests (CORE-01).

Validates that Runtime._diff_children emits operations that produce the
correct native tree. Tests initial mount (always passes) and re-renders
with keyed child reordering (demonstrates CORE-01).

Evidence level: E2 (strict applied reference state).
"""

from __future__ import annotations

import random
import unittest

from vyne import Column, Layout, Text, state
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport
from tests.support.native_model import NativeModel


_next_fresh_id = 1


def _build_fresh(model: NativeModel, element, *, parent_id: int) -> int:
    global _next_fresh_id
    node_id = _next_fresh_id
    _next_fresh_id += 1

    from vyne.elements import event_name_for_prop
    node = model._nodes[node_id] = model._nodes.get(
        node_id,
        type("NN", (), {
            "id": node_id, "kind": element.kind, "props": {},
            "listeners": {}, "latest_events": set(),
            "children": [], "parent_id": None,
        })(),
    )
    node.id = node_id
    node.kind = element.kind

    for name, value in element.props.items():
        if name == "key":
            continue
        if event_name_for_prop(name) is not None:
            continue
        node.props[name] = value

    for child_element in element.children:
        child_id = _build_fresh(model, child_element, parent_id=node_id)
        child = model._nodes[child_id]
        child.parent_id = node_id
        node.children.append(child)

    if parent_id == 0:
        model._root_children.append(node)
    return node_id


class ReconciliationCorrectnessTests(unittest.TestCase):
    """Reconciliation correctness tests for CORE-01."""

    def setUp(self):
        global _next_fresh_id
        _next_fresh_id = 1

    # ----------------------------------------------------------------
    # Initial mount (should always pass)
    # ----------------------------------------------------------------

    def test_initial_mount_matches_expected_tree(self):
        """Initial mount always produces correct tree via create_subtree."""
        for keys in [["a"], ["a", "b"], ["c", "b", "a"],
                      ["d", "c", "b", "a"], ["e", "d", "c", "b", "a"]]:
            with self.subTest(keys=keys):
                def build():
                    return Column(*(Text(text=k, key=k) for k in keys))

                transport = MemoryTransport()
                runtime = Runtime(build, transport=transport)
                runtime.mount()

                applied = NativeModel()
                applied.apply_ops(runtime.latest_commit["ops"])

                expected = NativeModel()
                _build_fresh(expected, build(), parent_id=0)

                self._assert_trees_match(applied, expected)

    def test_initial_mount_with_mixed_keyed_unkeyed(self):
        """Initial mount with mixed keyed and unkeyed children works."""
        def build():
            return Column(
                Text(text="unkeyed-1"),
                Text(text="keyed-a", key="a"),
                Text(text="unkeyed-2"),
                Text(text="keyed-b", key="b"),
            )

        transport = MemoryTransport()
        runtime = Runtime(build, transport=transport)
        runtime.mount()

        applied = NativeModel()
        applied.apply_ops(runtime.latest_commit["ops"])

        expected = NativeModel()
        _build_fresh(expected, build(), parent_id=0)

        self._assert_trees_match(applied, expected)

    def test_initial_mount_multiple_parents(self):
        """Nested children across multiple parents work."""
        def build():
            return Column(
                Layout(
                    Text(text="child1", key="a"),
                    Text(text="child2", key="b"),
                    orientation="vertical",
                ),
                Layout(
                    Text(text="child3", key="c"),
                    orientation="vertical",
                ),
            )

        transport = MemoryTransport()
        runtime = Runtime(build, transport=transport)
        runtime.mount()

        applied = NativeModel()
        applied.apply_ops(runtime.latest_commit["ops"])

        expected = NativeModel()
        _build_fresh(expected, build(), parent_id=0)

        self._assert_trees_match(applied, expected)

    # ----------------------------------------------------------------
    # Keyed re-rendering (CORE-01 demonstrations)
    # ----------------------------------------------------------------

    def _test_reorder(self, initial_keys, desired_keys, label):
        """Helper: test re-render with keyed child reordering.

        Applies both initial and re-render commits to the same NativeModel
        and compares against the desired final tree.
        """
        def App():
            order = state(0)
            keys = initial_keys if order.value == 0 else desired_keys
            return Column(
                Text(text="Trigger", on_click=lambda: order.set(1)),
                *(Text(text=k, key=k) for k in keys),
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        applied = NativeModel()
        applied.apply_ops(runtime.latest_commit["ops"])

        click_listener = [
            op for op in runtime.latest_commit["ops"]
            if op.get("op") == "listen" and op.get("event") == "click"
        ][0]

        runtime.dispatch_event({
            "type": "event", "seq": 1,
            "target": click_listener["id"],
            "event": "click",
            "handler": click_listener["handler"],
            "payload": {},
        })

        applied.apply_ops(runtime.latest_commit["ops"])

        def final_state():
            return Column(
                Text(text="Trigger"),
                *(Text(text=k, key=k) for k in desired_keys),
            )

        expected = NativeModel()
        _build_fresh(expected, final_state(), parent_id=0)

        return applied, expected, runtime.latest_commit["ops"]

    def test_keyed_reorder_traces(self):
        """Known keyed reorder traces produce matching native trees."""
        cases = [
            ("a_b->c_b_d", ["a", "b"], ["c", "b", "d"]),
            ("abcd->dbca", ["a", "b", "c", "d"], ["d", "b", "c", "a"]),
            ("abcde->edcba", list("abcde"), list("edcba")),
            ("abcde->bdaec", list("abcde"), ["b", "d", "a", "e", "c"]),
        ]
        for label, initial, desired in cases:
            with self.subTest(trace=label):
                applied, expected, ops = self._test_reorder(
                    initial, desired, label,
                )
                self._assert_trees_match(applied, expected)

    # ----------------------------------------------------------------
    # Randomized lifecycle
    # ----------------------------------------------------------------

    def test_randomized_keyed_lifecycle(self):
        """Seeded random sequences of keyed child mutations (CORE-01).

        Every random transition must produce a correct native tree —
        zero failures are expected.  The assertion is strict: if any
        transition fails, the test fails with full diagnostics.
        """
        rng = random.Random(42)
        keys_pool = [f"k{i}" for i in range(8)]
        failures: list[str] = []

        for iteration in range(20):
            count = rng.randint(2, 5)
            initial_keys = rng.sample(keys_pool, count)
            desired_keys = rng.sample(keys_pool, count)
            label = f"{''.join(k for k in initial_keys)}->{''.join(k for k in desired_keys)}"

            try:
                applied, expected, ops = self._test_reorder(
                    initial_keys, desired_keys, label,
                )

                if not self._trees_equal(applied, expected):
                    failures.append(
                        f"iter={iteration} {label}: tree mismatch\n"
                        f"  ops: {ops}\n"
                        f"  applied: {applied.tree()}\n"
                        f"  expected: {expected.tree()}"
                    )
            except Exception as exc:
                failures.append(f"iter={iteration} {label}: exception: {exc}")

        if failures:
            self.fail(
                f"Randomized lifecycle: {20 - len(failures)}/20 passing, "
                f"{len(failures)} failures:\n"
                + "\n".join(failures[:10])
            )

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    @staticmethod
    def _trees_equal(applied: NativeModel, expected: NativeModel) -> bool:
        a_children = applied.tree()["children"]
        e_children = expected.tree()["children"]
        return ReconciliationCorrectnessTests._children_equal(a_children, e_children)

    @staticmethod
    def _children_equal(a_children, e_children) -> bool:
        if len(a_children) != len(e_children):
            return False
        for a, e in zip(a_children, e_children):
            if not ReconciliationCorrectnessTests._node_equal(a, e):
                return False
        return True

    @staticmethod
    def _node_equal(a, e) -> bool:
        if a.get("kind") != e.get("kind"):
            return False
        a_props = dict(a.get("props", {}))
        e_props = dict(e.get("props", {}))
        # With the lowering pipeline, all defaults are materialized.
        # The expected tree only specifies key props; check that all
        # expected props are present with the expected values.
        for key, val in e_props.items():
            if a_props.get(key) != val:
                return False
        return ReconciliationCorrectnessTests._children_equal(
            a.get("children", []), e.get("children", [])
        )

    def _assert_trees_match(self, applied: NativeModel, expected: NativeModel):
        self.assertTrue(
            self._trees_equal(applied, expected),
            f"Trees do not match.\n"
            f"Applied: {applied.tree()}\n"
            f"Expected: {expected.tree()}",
        )


if __name__ == "__main__":
    unittest.main()
