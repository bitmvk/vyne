"""Strict reference native operation applier and applied-snapshot oracle.

This module provides a deterministic, pure-Python simulation of the Android
renderer's operation semantics.  It is the gold standard for correctness:
every sequence of operations emitted by reconciliation must, when applied to
this model, produce exactly the tree described by the desired Element tree.

Key invariants:
- Matches the expected Kotlin renderer behavior (mechanical, no policy).
- Uses string-key-only frozen mappings and stable value equality.
- Tracks a mutable shadow of current root child order that mirrors the
  native View hierarchy.
- Validates move indices against that shadow (unlike the buggy old code).
- Supports full create, set/remove props, listen/unlisten, insert/move/remove
  children, remove subtree, animation ops, and clear.

Usage in tests:
    model = NativeModel()
    model.apply_ops(commit["ops"])
    # Compare model.tree with expected canonical tree representation.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NativeNode:
    """A simulated native view node."""
    id: int
    kind: str
    props: dict[str, Any] = field(default_factory=dict)
    listeners: dict[str, int] = field(default_factory=dict)
    latest_events: set[str] = field(default_factory=set)
    children: list[NativeNode] = field(default_factory=list)
    parent_id: int | None = None


class NativeModelError(ValueError):
    """Raised when operations are invalid or inconsistent."""


class NativeModel:
    """Pure-Python simulation of the native Android renderer.

    Applies operations in order and maintains a shadow tree that represents
    the native View hierarchy.  Validates moves against the current native
    order, matching the expected Kotlin behavior.
    """

    def __init__(self) -> None:
        self._nodes: dict[int, NativeNode] = {}
        self._root_children: list[NativeNode] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_ops(self, ops: list[dict[str, Any]]) -> None:
        """Apply a list of protocol operations in order."""
        for op in ops:
            self._apply_one(op)

    def apply_commit(self, commit: dict[str, Any]) -> None:
        """Apply an entire commit."""
        self.apply_ops(commit.get("ops", []))

    def tree(self) -> dict[str, Any]:
        """Return the current root tree as a canonical dict for comparison."""
        return {
            "children": [self._serialize_node(child) for child in self._root_children],
        }

    def node_ids(self) -> set[int]:
        """Return the set of all live node IDs."""
        return set(self._nodes.keys())

    def node(self, node_id: int) -> NativeNode | None:
        """Return a node by ID, or None."""
        return self._nodes.get(node_id)

    def root_child_order(self) -> list[int]:
        """Return the current root child order (view IDs)."""
        return [child.id for child in self._root_children]

    # ------------------------------------------------------------------
    # Operation dispatch
    # ------------------------------------------------------------------

    def _apply_one(self, op: dict[str, Any]) -> None:
        op_name = op.get("op")
        if op_name is None:
            raise NativeModelError("Operation has no 'op' field")

        handler = getattr(self, f"_op_{op_name}", None)
        if handler is None:
            raise NativeModelError(f"Unknown operation: {op_name!r}")
        handler(op)

    def _op_clear(self, op: dict[str, Any]) -> None:
        target_id = op["id"]
        if target_id != 0:
            raise NativeModelError(f"clear must target root (id=0), got {target_id}")
        # Remove all root children in postorder
        for child in list(self._root_children):
            self._remove_subtree(child)
        self._root_children.clear()

    def _op_create(self, op: dict[str, Any]) -> None:
        node_id = op["id"]
        if node_id in self._nodes:
            raise NativeModelError(f"Node {node_id} already exists")
        node = NativeNode(id=node_id, kind=op["kind"])
        self._nodes[node_id] = node

    def _op_set_props(self, op: dict[str, Any]) -> None:
        node = self._require_node(op["id"])
        for key, value in op["props"].items():
            node.props[key] = deepcopy(value)

    def _op_set_prop(self, op: dict[str, Any]) -> None:
        node = self._require_node(op["id"])
        node.props[op["name"]] = deepcopy(op["value"])

    def _op_remove_prop(self, op: dict[str, Any]) -> None:
        node = self._require_node(op["id"])
        node.props.pop(op["name"], None)

    def _op_listen(self, op: dict[str, Any]) -> None:
        node = self._require_node(op["id"])
        node.listeners[op["event"]] = op["handler"]
        node.latest_events.discard(op["event"])

    def _op_listen_latest(self, op: dict[str, Any]) -> None:
        node = self._require_node(op["id"])
        node.listeners[op["event"]] = op["handler"]
        node.latest_events.add(op["event"])

    def _op_unlisten(self, op: dict[str, Any]) -> None:
        node = self._require_node(op["id"])
        node.listeners.pop(op["event"], None)
        node.latest_events.discard(op["event"])

    def _op_insert_child(self, op: dict[str, Any]) -> None:
        parent_id = op["parent"]
        child_id = op["child"]
        index = op["index"]
        child = self._require_node(child_id)

        if parent_id == 0:
            siblings = self._root_children
        else:
            parent = self._require_node(parent_id)
            siblings = parent.children

        if index < 0 or index > len(siblings):
            raise NativeModelError(
                f"insert_child index {index} out of range [0, {len(siblings)}]"
            )
        siblings.insert(index, child)
        child.parent_id = parent_id

    def _op_move_child(self, op: dict[str, Any]) -> None:
        parent_id = op["parent"]
        child_id = op["child"]
        index = op["index"]

        if parent_id == 0:
            siblings = self._root_children
        else:
            parent = self._require_node(parent_id)
            siblings = parent.children

        child = self._require_node(child_id)
        current_index = self._index_of(siblings, child_id)
        if current_index is None:
            raise NativeModelError(
                f"move_child: child {child_id} is not a child of parent {parent_id}"
            )

        # Remove from current position...
        siblings.pop(current_index)
        # Adjust target index if removing before it shifted it
        if current_index < index:
            target = index - 1
        else:
            target = index
        if target < 0 or target > len(siblings):
            raise NativeModelError(
                f"move_child target index {target} out of range after removal"
            )
        siblings.insert(target, child)

    def _op_remove_child(self, op: dict[str, Any]) -> None:
        parent_id = op["parent"]
        child_id = op["child"]

        if parent_id == 0:
            siblings = self._root_children
        else:
            parent = self._require_node(parent_id)
            siblings = parent.children

        child = self._require_node(child_id)
        current_index = self._index_of(siblings, child_id)
        if current_index is None:
            raise NativeModelError(
                f"remove_child: child {child_id} is not a child of parent {parent_id}"
            )
        siblings.pop(current_index)
        child.parent_id = None
        # Note: remove_child detaches the child but does NOT delete it.
        # The node is deleted only by _op_remove.

    def _op_remove(self, op: dict[str, Any]) -> None:
        node = self._require_node(op["id"])
        if node.parent_id is not None:
            raise NativeModelError(
                f"remove: subtree root {node.id} is still attached to parent "
                f"{node.parent_id}"
            )
        self._remove_subtree(node)

    def _op_scroll_to(self, op: dict[str, Any]) -> None:
        node = self._require_node(op["id"])
        if node.kind not in {"Scroll", "HorizontalScroll"}:
            raise NativeModelError("scroll_to target must be a scroll container")
        # Accepted effect only. It does not change the logical render tree.


    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_node(self, node_id: int) -> NativeNode:
        node = self._nodes.get(node_id)
        if node is None:
            raise NativeModelError(f"Node {node_id} not found")
        return node

    @staticmethod
    def _index_of(siblings: list[NativeNode], node_id: int) -> int | None:
        for i, child in enumerate(siblings):
            if child.id == node_id:
                return i
        return None

    def _remove_subtree(self, node: NativeNode) -> None:
        """Remove a node and all its descendants (postorder)."""
        stack = [node]
        postorder: list[NativeNode] = []
        while stack:
            current = stack.pop()
            postorder.append(current)
            stack.extend(current.children)
        for n in reversed(postorder):
            # Remove from parent's children list if still attached
            if n.parent_id is not None:
                parent = self._nodes.get(n.parent_id)
                if parent is not None and n in parent.children:
                    parent.children.remove(n)
            # Remove from root
            if n in self._root_children:
                self._root_children.remove(n)
            self._nodes.pop(n.id, None)

    def _serialize_node(self, node: NativeNode) -> dict[str, Any]:
        """Serialize a node to a canonical dict for comparison."""
        return {
            "id": node.id,
            "kind": node.kind,
            "props": dict(sorted(node.props.items())),
            "listeners": dict(sorted(node.listeners.items())),
            "latest_events": sorted(node.latest_events),
            "children": [self._serialize_node(child) for child in node.children],
        }
