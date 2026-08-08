"""Immutable render model types for the Vyne reconciliation pipeline.

These types separate the Python-owned description from runtime state:

* ``CanonicalElement`` — deeply immutable, fully lowered element ready for diffing.
* ``RenderNode`` — runtime-owned mirror node with monotonic ID, parent, and
  children.  This is the **single canonical definition** — ``vyne.runtime``
  imports it here and uses it as the authoritative runtime mirror.
* ``RenderSnapshot`` — the complete tree state at one revision, used as the
  accepted baseline for the next reconciliation pass.
* ``ReconcileOperation`` / ``ReconcileResult`` — the output of the pure
  side-effect-free reconciliation planner (``plan_reconcile``).

CORE-01: The pure planner in ``vyne.reconcile`` produces these operations
given a previous ``RenderSnapshot`` and a desired ``CanonicalElement``.
The planner is verified by an exact Renderer-faithful applier
(``tests/support/native_model.py``) that applies the operations to a
simulated native tree and compares against a fresh build.

This module is pure data; it has no IO, threads, or side effects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# ---- scalar values ----------------------------------------------------------

type CanonicalValue = (
    None
    | bool
    | int
    | float
    | str
    | list[CanonicalValue]
    | dict[str, CanonicalValue]
)

type FrozenProps = Mapping[str, CanonicalValue]


# ---- render mirror nodes ----------------------------------------------------


@dataclass(eq=False)
class RenderNode:
    """One node in the runtime-owned shadow of the native tree.

    This is the **single canonical definition** of RenderNode used by the
    Runtime, recovery snapshot builder, and all test support modules.

    Every occurrence of an Element gets its own RenderNode, even when the
    same Element object is reused.  Nodes hold runtime state only — the
    element reference is the immutable blueprint.
    """

    id: int
    kind: str
    key: Any = None
    props: dict[str, Any] = field(default_factory=dict)
    listeners: dict[str, int] = field(default_factory=dict)
    latest_events: set[str] = field(default_factory=set)
    listener_callbacks: dict[str, Any] = field(default_factory=dict, repr=False)
    ref: Any | None = field(default=None, repr=False)
    children: list["RenderNode"] = field(default_factory=list)
    element: Any | None = field(default=None, repr=False)
    intent_element: Any | None = field(default=None, repr=False)
    parent_id: int | None = field(default=None, repr=False)


# ---- reconciliation operations ----------------------------------------------


@dataclass(frozen=True)
class ReconcileOperation:
    """A single planned operation produced by the pure reconciliation planner.

    These operations are verified by the ``NativeModel`` reference applier
    before they are converted to wire-format commits.  Every field that is
    not applicable for a given op type is ``None``.
    """

    op: str
    # create / remove
    id: int | None = None
    kind: str | None = None
    # set_props / set_prop / remove_prop
    name: str | None = None
    value: Any = None
    props: dict[str, Any] | None = None
    # listen / unlisten
    event: str | None = None
    handler: int | None = None
    # insert_child / move_child / remove_child
    parent: int | None = None
    child: int | None = None
    index: int | None = None

    def to_wire_op(self) -> dict[str, Any]:
        """Convert to the wire-format dict expected by the transport layer."""
        wire: dict[str, Any] = {"op": self.op}
        if self.id is not None:
            wire["id"] = self.id
        if self.kind is not None:
            wire["kind"] = self.kind
        if self.name is not None:
            wire["name"] = self.name
        if self.value is not None:
            wire["value"] = self.value
        if self.props is not None:
            wire["props"] = self.props
        if self.event is not None:
            wire["event"] = self.event
        if self.handler is not None:
            wire["handler"] = self.handler
        if self.parent is not None:
            wire["parent"] = self.parent
        if self.child is not None:
            wire["child"] = self.child
        if self.index is not None:
            wire["index"] = self.index
        return wire


@dataclass(frozen=True)
class ReconcileResult:
    """Output of a pure reconciliation pass.

    ``ops`` is the sequenced list of operations to apply to the native tree.
    ``new_snapshot`` is the predicted state after all operations are applied.
    """

    ops: list[ReconcileOperation]
    new_snapshot: "RenderSnapshot"


# ---- the complete snapshot --------------------------------------------------


@dataclass
class RenderSnapshot:
    """The complete runtime state at one revision.

    Owned by the scheduler / coordinator and used as the accepted baseline
    for the next reconciliation pass.  The root node and node_index are
    treated as immutable by the planner. Candidate snapshots are built with
    copy-on-write nodes, so planning and preflight failure cannot mutate the
    accepted snapshot.
    """

    root: RenderNode | None
    node_index: dict[int, RenderNode]
    revision: int
