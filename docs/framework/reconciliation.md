# The Reconciliation Algorithm (CORE-01)

Source: `vyne/reconcile.py`.

`plan_reconcile(old_snapshot, desired_canonical_root, next_node_id)`
produces a `ReconcileResult`: a side-effect-free, ordered list of
operations plus the predicted next snapshot.

The planner is pure. It never touches the accepted snapshot. It does no
IO, no transport, no mutation of accepted state.

## Identity rule

Two nodes share identity when `kind` and `key` match.

- Identity match -> reuse the node id, diff props and children in place.
- Identity mismatch -> tear down the whole subtree (`remove`) and rebuild
  (`create`).
- Exact blueprint match (`old_node.element is desired`) -> reuse the
  accepted subtree without visiting descendants.

## Child matching strategy

For each parent, in order:

1. **Keyed children match first** via an O(1) dict lookup by key. The old
   child kind must match the desired kind.
2. **Unkeyed children match by position** when the old child at that
   position is also unkeyed and still unmatched.
3. Unmatched old children are removed in **reverse order** (postorder-safe:
   earlier indices stay valid while removing).
4. New children without a match are created detached, then inserted.
5. Matched children at different positions emit `move_child`.

## The mutable shadow list

Index correctness is the hard part. Every `insert_child` / `move_child`
index must match what the native side sees *after* the previous
operations.

The planner keeps a mutable native-order shadow list per parent
(`_ParentShadow`). After every remove, insert, and move, the shadow is
updated and reindexed. Every subsequent op is computed against the updated
shadow.

This is CORE-01: "sequential move ops use correct indices after each
shadow update."

## Copy-on-write snapshots

Accepted `RenderNode`s are immutable. The planner:

- shallow-copies the id table
- structurally shares unchanged subtrees
- creates replacement nodes only where the tree changed

A one-prop update therefore scales with the changed part, not the whole
app. A full defensive deepcopy is unnecessary.

## Subtree removal contract (RP3-02)

`remove(id)` destroys the subtree root and every descendant.

- exactly one `remove` op is emitted, for the detached root
- descendants are cleaned from the node index without individual ops

## Prop diffing

For each desired prop: if the accepted value differs, emit `set_prop`.
For each accepted prop missing in the desired set: emit `remove_prop`.

## Complexity

- keyed matching: O(1) per child via the key dict
- unkeyed matching: O(1) per child by position
- shadow reindex after remove/insert: O(children) for that parent
- overall: O(tree size) per pass

## Verification

The planner output is verified by a reference applier:

- `tests/support/native_model.py` — applies ops to a fresh simulated
  native tree
- `tests/support/reconciliation_oracle.py` — compares the applied tree
  against building the desired tree from scratch

Any plan must reproduce the desired tree exactly. This is a test-only
enforcement of the renderer contract (RP3-02).

## Related

- [core-model.md](../concepts/core-model.md) — RenderNode, RenderSnapshot
- [protocol.md](protocol.md) — the operations on the wire
- [runtime.md](runtime.md) — how plans become commits
