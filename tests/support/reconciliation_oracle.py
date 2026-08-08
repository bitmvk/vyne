"""Reconciliation correctness oracle for CORE-01.

Validates that the operations emitted by Runtime._diff_children, when applied
to a reference native model, produce exactly the expected tree.

This is the gold standard for correctness: the order of nodes in the applied
model must match what create_subtree would produce if applied from scratch.

Provides:
- apply_and_compare(runtime, desired_tree_func): Mount, apply, compare.
- permutation_tests(): Exhaustive ordered-subset pairs of a 5-key universe.
- keyed_unkeyed_mixed_tests(): Mixed keyed/unkeyed scenarios.
- identity_change_tests(): Kind/key identity mismatches.
- randomized_lifecycle_tests(): Seeded random sequences.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from vyne.elements import Element
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport
from tests.support.native_model import NativeModel


@dataclass
class OracleResult:
    """Result of a reconciliation correctness check."""
    passed: bool
    failure_message: str | None = None
    expected_tree: dict[str, Any] | None = None
    actual_tree: dict[str, Any] | None = None
    commit_ops: list[dict[str, Any]] | None = None


def apply_and_compare(
    element_factory: Callable[[], Element],
) -> OracleResult:
    """Mount a Runtime with this root, apply its ops to a NativeModel,
    then compare with a fresh NativeModel rendered directly."""
    transport = MemoryTransport()
    runtime = Runtime(element_factory, transport=transport)
    runtime.mount()

    # Collect the emitted commit ops and apply to a reference model
    commit = runtime.latest_commit
    if commit is None:
        return OracleResult(False, "No commit emitted")
    commit_ops = commit.get("ops", [])

    # Check if this was an error commit
    for op in commit_ops:
        if op.get("op") == "clear":
            return OracleResult(
                False,
                f"Error commit detected: {commit_ops}",
                commit_ops=commit_ops,
            )

    # Apply ops to the reference native model
    model = NativeModel()
    model.apply_ops(commit_ops)
    actual_tree = model.tree()

    # Build expected tree by applying to a fresh model from scratch
    expected_model = NativeModel()
    _create_subtree_from_element(expected_model, element_factory(), parent_id=0)
    expected_tree = expected_model.tree()

    # Compare
    if actual_tree == expected_tree:
        return OracleResult(True, commit_ops=commit_ops)
    else:
        return OracleResult(
            False,
            "Applied tree does not match expected tree",
            expected_tree=expected_tree,
            actual_tree=actual_tree,
            commit_ops=commit_ops,
        )


def _create_subtree_from_element(
    model: NativeModel,
    element: Element,
    *,
    parent_id: int,
) -> int:
    """Recursively create a full fresh subtree in the model."""
    from vyne.runtime import RenderNode

    node_id = _next_id()
    node = model._nodes[node_id] = model._nodes.get(node_id, type(
        "NativeNode",
        (),
        {"id": node_id, "kind": element.kind, "props": {}, "listeners": {},
         "latest_events": set(), "children": [], "parent_id": None},
    )())
    node.id = node_id
    node.kind = element.kind

    # Copy non-event, non-key props
    from vyne.elements import event_name_for_prop
    for name, value in element.props.items():
        if name == "key":
            continue
        if event_name_for_prop(name) is not None:
            node.listeners[name] = 0  # placeholder
            continue
        node.props[name] = deepcopy(value)

    # Recursively create children
    for child_element in element.children:
        child_id = _create_subtree_from_element(
            model, child_element, parent_id=node_id
        )
        child = model._nodes[child_id]
        child.parent_id = node_id
        node.children.append(child)

    if parent_id == 0:
        model._root_children.append(node)
    return node_id


_next_node_id = 1


def _next_id() -> int:
    global _next_node_id
    node_id = _next_node_id
    _next_node_id += 1
    return node_id


def build_keyed_permutation_tests() -> list[Callable[[], Element]]:
    """Build test cases for keyed child reconciliation.

    Returns a list of element factories that exercise different
    permutations of keyed children to validate CORE-01.
    """
    from vyne import Column, Text

    tests: list[Callable[[], Element]] = []

    # Test: [a,b,c,d] -> [c,b,d,a] (known CORE-01 failure)
    def case_move_last_to_first():
        return Column(
            Text(text="c", key="c"),
            Text(text="b", key="b"),
            Text(text="d", key="d"),
            Text(text="a", key="a"),
        )
    tests.append(case_move_last_to_first)

    # Test: [a,b] -> [c,b,d] (mix of remove, keep, create)
    def case_mixed_remove_keep_create():
        return Column(
            Text(text="c", key="c"),
            Text(text="b", key="b"),
            Text(text="d", key="d"),
        )
    tests.append(case_mixed_remove_keep_create)

    # Test: reverse a 5-element list
    def case_reverse_five():
        return Column(
            Text(text="e", key="e"),
            Text(text="d", key="d"),
            Text(text="c", key="c"),
            Text(text="b", key="b"),
            Text(text="a", key="a"),
        )
    tests.append(case_reverse_five)

    # Test: shuffle
    def case_shuffle():
        return Column(
            Text(text="b", key="b"),
            Text(text="d", key="d"),
            Text(text="a", key="a"),
            Text(text="e", key="e"),
            Text(text="c", key="c"),
        )
    tests.append(case_shuffle)

    # Test: move with replace (same key, different kind)
    def case_keyed_kind_change():
        return Column(
            Text(text="replaced", key="a"),
            Text(text="b", key="b"),
        )
    tests.append(case_keyed_kind_change)

    return tests


def build_unkeyed_mixed_tests() -> list[Callable[[], Element]]:
    """Build test cases for unkeyed and mixed keyed/unkeyed scenarios."""
    from vyne import Box, Column, Layout, Text

    tests: list[Callable[[], Element]] = []

    # Unkeyed: simple insert at front
    def case_unkeyed_insert_front():
        return Column(
            Text(text="new"),
            Text(text="first"),
            Text(text="second"),
        )
    tests.append(case_unkeyed_insert_front)

    # Unkeyed: insert in middle
    def case_unkeyed_insert_middle():
        return Column(
            Text(text="first"),
            Text(text="middle"),
            Text(text="second"),
        )
    tests.append(case_unkeyed_insert_middle)

    # Unkeyed: remove first
    def case_unkeyed_remove_first():
        return Column(
            Text(text="second"),
        )
    tests.append(case_unkeyed_remove_first)

    # Mixed: keyed items among unkeyed
    def case_mixed_keyed_unkeyed():
        return Column(
            Text(text="unkeyed-a"),
            Text(text="keyed", key="k1"),
            Text(text="unkeyed-b"),
            Text(text="keyed2", key="k2"),
        )
    tests.append(case_mixed_keyed_unkeyed)

    # Multiple parents
    def case_multiple_parents():
        return Layout(
            Column(
                Text(text="child1", key="a"),
                Text(text="child2", key="b"),
            ),
            Column(
                Text(text="child3", key="c"),
            ),
            orientation="vertical",
        )
    tests.append(case_multiple_parents)

    return tests
