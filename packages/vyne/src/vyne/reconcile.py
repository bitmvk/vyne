"""Pure reconciliation planner (CORE-01).

``plan_reconcile()`` takes a previous ``RenderSnapshot`` and a desired
``CanonicalElement`` tree and produces a ``ReconcileResult`` with a
side-effect-free sequenced list of operations and the next snapshot.

Key design:
- Keyed elements matched by key+kind first (O(1) lookup).
- Unkeyed elements matched by position when both are unkeyed.
- A mutable native-order shadow list per parent is updated after every
  remove, insert, and move so subsequent indices are correct.
- The planner is pure: no IO, no transport, no mutation of the accepted
  snapshot (the old snapshot is deep-copied before planning begins).

The reference applier (``tests/support/native_model.py``) is used to
verify every plan: applying the ops to a fresh NativeModel must produce
the same tree as building the desired element tree from scratch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vyne.lowering import CanonicalElement
from vyne.render_model import (
    ReconcileResult,
    RenderNode,
    RenderSnapshot,
)


# ---- shadow helpers ---------------------------------------------------------


@dataclass
class _ParentShadow:
    """Mutable native-order shadow for one parent node.

    Maintained during reconciliation so that every insert/move/remove
    operation is indexed against the expected native state immediately
    after the operation takes effect.
    """

    parent_id: int
    children: list[int] = field(default_factory=list)
    _positions: dict[int, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._positions = {
            child_id: index for index, child_id in enumerate(self.children)
        }

    def _reindex(self, start: int, end: int | None = None) -> None:
        stop = len(self.children) if end is None else end
        for index in range(start, stop):
            self._positions[self.children[index]] = index

    def remove(self, child_id: int) -> None:
        """Remove a child node id from the shadow."""
        index = self._positions.pop(child_id)
        self.children.pop(index)
        self._reindex(index)

    def insert(self, child_id: int, index: int) -> None:
        """Insert a child node id at the given shadow index."""
        self.children.insert(index, child_id)
        self._reindex(index)

    def move(self, child_id: int, from_index: int, to_index: int) -> None:
        """Move a child node id from one shadow index to another."""
        self.children.pop(from_index)
        self.children.insert(to_index, child_id)
        self._reindex(min(from_index, to_index), max(from_index, to_index) + 1)

    def index_of(self, child_id: int) -> int:
        """Return the current shadow index of child_id."""
        return self._positions[child_id]


# ---- public API -------------------------------------------------------------


def plan_reconcile(
    old: RenderSnapshot,
    desired: CanonicalElement,
    *,
    next_node_id: int,
) -> ReconcileResult:
    """Produce a reconciliation plan from a previous snapshot to a desired tree.

    This is the pure, side-effect-free reconciliation entry point (CORE-01).
    The accepted snapshot ``old`` is never mutated. Planning reads it directly
    and constructs a new snapshot using copy-on-write nodes. If planning fails,
    the caller's snapshot is left untouched without copying the whole tree.

    Args:
        old: The previous accepted snapshot (root=None for initial render).
        desired: The canonical element tree to build or reconcile toward.
        next_node_id: The next monotonic node ID to allocate.

    Returns:
        A ``ReconcileResult`` with sequenced operations and the new snapshot.
        The ``new_snapshot`` can be promoted as the next accepted state.
    """
    planner = _ReconcilePlanner(old, next_node_id)
    result = planner.plan(desired)
    return result


# ---- internal planner -------------------------------------------------------


class _ReconcilePlanner:
    """Internal planner state machine for one reconciliation pass.

    All mutable state is local to this instance and discarded after
    ``plan()`` returns.  The accepted snapshot is never touched.
    """

    def __init__(self, old: RenderSnapshot, next_node_id: int) -> None:
        # RenderNode instances in the accepted snapshot are treated as
        # immutable. The planner only reads them and creates replacement nodes
        # for the candidate snapshot, so an O(tree-size) defensive deepcopy is
        # unnecessary and made one-property updates scale with the whole app.
        self._old_root = old.root
        self._old_index = old.node_index
        self._old_revision = old.revision
        self._next_node_id = next_node_id
        self._ops: list[dict[str, Any]] = []
        # Shallow-copy only the ID table. Individual accepted nodes are
        # immutable and can be structurally shared by unchanged subtrees.
        self._next_snapshot_nodes: dict[int, RenderNode] = dict(old.node_index)
        self._shadows: dict[int, _ParentShadow] = {}

    def plan(self, desired: CanonicalElement) -> ReconcileResult:
        """Execute the full reconciliation pass."""
        if self._old_root is None:
            new_root = self._create_subtree(desired, parent_id=0)
            self._ops.append({"op": "insert_child", "parent": 0, "child": new_root.id, "index": 0})
            self._shadow_for(0).insert(new_root.id, 0)
        else:
            new_root = self._diff_node(
                self._old_root,
                desired,
                parent_id=0,
                index=0,
            )

        snapshot = RenderSnapshot(
            root=new_root,
            node_index=self._next_snapshot_nodes,
            revision=self._old_revision + 1,
        )
        return ReconcileResult(
            ops=self._ops,
            new_snapshot=snapshot,
        )

    # ---- shadow management --------------------------------------------------

    def _shadow_for(self, parent_id: int) -> _ParentShadow:
        """Get or create the native-order shadow for a parent."""
        shadow = self._shadows.get(parent_id)
        if shadow is None:
            old_parent = self._old_index.get(parent_id)
            if parent_id == 0:
                shadow = _ParentShadow(
                    parent_id=0,
                    children=[self._old_root.id] if self._old_root is not None else [],
                )
            elif old_parent is not None:
                shadow = _ParentShadow(
                    parent_id=parent_id,
                    children=[child.id for child in old_parent.children],
                )
            else:
                shadow = _ParentShadow(parent_id=parent_id)
            self._shadows[parent_id] = shadow
        return shadow

    # ---- tree diffing -------------------------------------------------------

    def _diff_node(
        self,
        old_node: RenderNode,
        desired: CanonicalElement,
        *,
        parent_id: int,
        index: int,
    ) -> RenderNode:
        """Diff one node: reconcile old RenderNode with desired CanonicalElement.

        If the identity changed (kind or key mismatch), the entire subtree
        is torn down and rebuilt.  Otherwise, we diff props and recursively
        diff children while reusing the existing node ID.
        """
        # A cached canonical subtree is an exact immutable blueprint match.
        # Reuse the accepted RenderNode subtree without visiting descendants.
        if old_node.element is desired and old_node.parent_id == parent_id:
            return old_node

        if not self._same_identity(old_node, desired):
            self._ops.append(
                {"op": "remove_child", "parent": parent_id, "child": old_node.id}
            )
            self._remove_subtree(old_node)
            self._shadow_for(parent_id).remove(old_node.id)

            new_node = self._create_subtree(desired, parent_id=parent_id)
            self._ops.append(
                {"op": "insert_child", "parent": parent_id, "child": new_node.id, "index": index}
            )
            self._shadow_for(parent_id).insert(new_node.id, index)
            return new_node

        # Same identity — diff props and children in place.
        new_node = RenderNode(
            id=old_node.id,
            kind=desired.kind,
            key=desired.key,
            props=dict(desired.native_props),
            listeners=dict(old_node.listeners),
            latest_events=set(old_node.latest_events),
            listener_callbacks=dict(old_node.listener_callbacks),
            ref=old_node.ref,
            parent_id=parent_id,
            element=desired,
            intent_element=old_node.intent_element,
        )

        self._diff_props(old_node, desired, new_node)
        self._diff_children(old_node, desired, new_node)

        self._next_snapshot_nodes[new_node.id] = new_node
        return new_node

    @staticmethod
    def _same_identity(old_node: RenderNode, desired: CanonicalElement) -> bool:
        """Two nodes share identity if kind and key match."""
        return old_node.kind == desired.kind and old_node.key == desired.key

    def _diff_props(
        self,
        old_node: RenderNode,
        desired: CanonicalElement,
        new_node: RenderNode,
    ) -> None:
        """Diff properties between old and desired, emitting set/remove ops."""
        for name, value in desired.native_props.items():
            if old_node.props.get(name) != value:
                self._ops.append(
                    {"op": "set_prop", "id": old_node.id, "name": name, "value": value}
                )

        for name in old_node.props:
            if name not in desired.native_props:
                self._ops.append(
                    {"op": "remove_prop", "id": old_node.id, "name": name}
                )

    def _diff_children(
        self,
        old_node: RenderNode,
        desired: CanonicalElement,
        new_node: RenderNode,
    ) -> None:
        """Reconcile children using keyed matching and a mutable shadow (CORE-01).

        Strategy:
        1. Match keyed children first via O(1) lookup.
        2. Match unkeyed children by position (both must be unkeyed).
        3. For unmatched old children: emit remove_child + remove subtree.
        4. For new children without a match: create detached, emit insert_child.
        5. For matched children at different positions: emit move_child.
        6. For matched children: recurse with _diff_node.
        """
        old_children = old_node.children
        parent_id = old_node.id
        shadow = self._shadow_for(parent_id)

        matched_old: list[bool] = [False] * len(old_children)
        new_children: list[RenderNode] = []

        # Build keyed lookup for O(1) keyed matching.
        keyed_old: dict[Any, int] = {}
        for i, child in enumerate(old_children):
            if child.key is not None:
                keyed_old[child.key] = i

        for next_index, child_element in enumerate(desired.children):
            old_index = self._match_old_child(
                child_element,
                next_index,
                old_children,
                keyed_old,
                matched_old,
            )

            if old_index is None:
                # No match — create detached subtree.
                new_child = self._create_subtree(
                    child_element,
                    parent_id=parent_id,
                )
                self._ops.append(
                    {"op": "insert_child", "parent": parent_id, "child": new_child.id, "index": next_index}
                )
                shadow.insert(new_child.id, next_index)
                new_children.append(new_child)
                continue

            # Matched — diff the existing child.
            matched_old[old_index] = True
            old_child = old_children[old_index]

            # Compute the correct native index for the move.
            current_shadow_index = shadow.index_of(old_child.id)

            if current_shadow_index != next_index:
                self._ops.append(
                    {"op": "move_child", "parent": parent_id, "child": old_child.id, "index": next_index}
                )
                shadow.move(old_child.id, current_shadow_index, next_index)

            new_child = self._diff_node(
                old_child,
                child_element,
                parent_id=parent_id,
                index=next_index,
            )
            new_children.append(new_child)

        # Remove unmatched old children in reverse order (postorder-safe).
        for old_index in range(len(old_children) - 1, -1, -1):
            if matched_old[old_index]:
                continue
            old_child = old_children[old_index]
            self._ops.append(
                {"op": "remove_child", "parent": parent_id, "child": old_child.id}
            )
            self._remove_subtree(old_child)
            shadow.remove(old_child.id)

        new_node.children = new_children

    def _match_old_child(
        self,
        element: CanonicalElement,
        next_index: int,
        old_children: list[RenderNode],
        keyed_old: dict[Any, int],
        matched_old: list[bool],
    ) -> int | None:
        """Try to find an old child that corresponds to this new element.

        Keyed elements must match an old child with the same key and
        compatible kind.  Unkeyed elements match by position if the old
        child at that position is also unkeyed and still unmatched.
        """
        key = element.key
        if key is not None:
            old_index = keyed_old.get(key)
            if old_index is not None and not matched_old[old_index]:
                if old_children[old_index].kind == element.kind:
                    return old_index
            return None

        # Unkeyed: match by position if both are unkeyed and unmatched.
        if next_index < len(old_children) and not matched_old[next_index]:
            old_child = old_children[next_index]
            if old_child.key is None:
                return next_index
        return None

    # ---- subtree creation and removal ---------------------------------------

    def _create_subtree(
        self,
        element: CanonicalElement,
        *,
        parent_id: int,
    ) -> RenderNode:
        """Build a RenderNode tree from a CanonicalElement tree.

        Each created node gets a fresh monotonic ID and is registered in
        the next snapshot's node_index.
        """
        node_id = self._allocate_node_id()
        node = RenderNode(
            id=node_id,
            kind=element.kind,
            key=element.key,
            props=dict(element.native_props),
            parent_id=parent_id,
            element=element,
        )
        self._ops.append({"op": "create", "id": node_id, "kind": element.kind})
        if element.native_props:
            self._ops.append(
                {"op": "set_props", "id": node_id, "props": dict(element.native_props)}
            )

        # Recursively create children.
        shadow = self._shadow_for(node_id)
        for idx, child_element in enumerate(element.children):
            child = self._create_subtree(child_element, parent_id=node_id)
            node.children.append(child)
            self._ops.append(
                {"op": "insert_child", "parent": node_id, "child": child.id, "index": idx}
            )
            shadow.insert(child.id, idx)

        self._next_snapshot_nodes[node_id] = node
        return node

    def _remove_subtree(self, node: RenderNode) -> None:
        """Tear down a subtree, emitting exactly one remove for the root.

        The recursive contract (RP3-02): ``remove(id)`` destroys *id* and
        every descendant.  Only the detached root gets a remove operation;
        descendants are cleaned from indexes without individual operations.
        """
        # Collect all descendant IDs for cleanup.
        stack: list[RenderNode] = [node]
        all_ids: list[int] = []
        while stack:
            current = stack.pop()
            all_ids.append(current.id)
            stack.extend(current.children)

        # Emit exactly one remove for the subtree root.
        self._ops.append({"op": "remove", "id": node.id})

        # Clean all subtree node IDs from the next snapshot.
        for nid in all_ids:
            self._next_snapshot_nodes.pop(nid, None)

    def _allocate_node_id(self) -> int:
        node_id = self._next_node_id
        self._next_node_id += 1
        return node_id
