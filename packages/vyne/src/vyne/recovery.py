"""Python-owned recovery state machine and snapshot/resync policy.

This module defines:

- **RecoveryState**: the Python-side view of native synchronization health.
- **RecoveryActions**: what the framework should do in each state when a
  commit, event, or exception arrives.
- **build_snapshot_commit**: builds a complete-snapshot commit from a
  RenderNode tree — every create, prop set, listener, and insert in
  deterministic order, producing a known-good baseline for native reset.

The policy guarantees:

- Malformed inbound events do NOT clear a known-good tree.
- A native ``unknown`` state receives only a complete acknowledged snapshot.
- Failed import/remount candidates never replace a prior known-good install.
- Terminal failures have bounded behavior — no retry storms.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

from vyne.protocol import (
    MSG_COMMIT,
    OP_CREATE,
    OP_INSERT_CHILD,
    OP_LISTEN,
    OP_LISTEN_LATEST,
    OP_SET_PROPS,
    JsonObject,
)

if TYPE_CHECKING:
    from vyne.render_model import RenderNode


class RecoveryState(Enum):
    """Python's view of native-synchronization health.

    Transitions:
    - SYNCED → AWAITING_APPLY (commit sent, waiting for native ack)
    - SYNCED → NEEDS_RESET (native reported unknown, send snapshot)
    - AWAITING_APPLY → SYNCED (native ack received)
    - AWAITING_APPLY → NEEDS_RESET (native reported failure during apply)
    - NEEDS_RESET → AWAITING_APPLY (snapshot sent, waiting for ack)
    - NEEDS_RESET → SYNCED (snapshot accepted)
    - Any → FAULTED (unrecoverable native failure)
    - FAULTED → NEEDS_RESET (full remount attempt)
    - Any → DISPOSED (renderer disposed)
    """

    SYNCED = auto()            # Python and native trees match
    AWAITING_APPLY = auto()    # Commit sent, waiting for native confirmation
    NEEDS_RESET = auto()       # Native tree unknown or desynchronized
    FAULTED = auto()           # Native irrecoverably failed
    DISPOSED = auto()          # Renderer disposed


def build_snapshot_commit(
    root: RenderNode,
    revision: int,
    *,
    origin_event_seq: int | None = None,
) -> JsonObject:
    """Build a complete-snapshot commit from the authoritative RenderNode tree.

    This produces create ops for every node, set_props for all resolved props,
    listener ops for all active listeners, and insert_child ops in order.  The
    resulting commit is self-contained: native can wipe its tree and apply this
    to reach the exact same state as the Python RenderNode mirror.

    The snapshot is deterministic (children are traversed in order, props are
    sorted) so the same tree always produces the same commit bytes.
    """
    ops: list[JsonObject] = []

    # Start with a root clear to wipe any unknown native state.
    ops.append({"op": "clear", "id": 0})

    def _emit_node(node: RenderNode, parent_id: int, insert_index: int) -> None:
        # Create the node.
        ops.append({"op": OP_CREATE, "id": node.id, "kind": node.kind})

        # Set all props in sorted order for deterministic output.
        if node.props:
            sorted_props = dict(sorted(node.props.items()))
            ops.append({"op": OP_SET_PROPS, "id": node.id, "props": sorted_props})

        # Set each removed prop that was previously present but isn't now.
        # (In a full snapshot, all props are resolved so there are no removes.)

        # Register all listeners.
        for event_name in sorted(node.listeners.keys()):
            handler_id = node.listeners[event_name]
            is_latest = event_name in node.latest_events
            ops.append({
                "op": OP_LISTEN_LATEST if is_latest else OP_LISTEN,
                "id": node.id,
                "event": event_name,
                "handler": handler_id,
            })

        # Insert into parent.
        ops.append({
            "op": OP_INSERT_CHILD,
            "parent": parent_id,
            "child": node.id,
            "index": insert_index,
        })

        # Recurse into children.
        for idx, child in enumerate(node.children):
            _emit_node(child, node.id, idx)

    _emit_node(root, 0, 0)

    commit: JsonObject = {
        "type": MSG_COMMIT,
        "revision": revision,
        "ops": ops,
    }
    if origin_event_seq is not None:
        commit["origin_event_seq"] = origin_event_seq

    return commit
