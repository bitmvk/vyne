"""Immutable render model types for the Vyne reconciliation pipeline.

These types separate the Python-owned description from runtime state:

* ``CanonicalElement`` — deeply immutable, fully lowered element ready for diffing.
* ``RenderNode`` — runtime-owned mirror node with monotonic ID, parent, and
  children.  This is the **single canonical definition** — ``vyne.runtime``
  imports it here and uses it as the authoritative runtime mirror.
* ``RenderSnapshot`` — the complete tree state at one revision, used as the
  accepted baseline for the next reconciliation pass.
* ``ReconcileResult`` — the output of the pure side-effect-free
  reconciliation planner (``plan_reconcile``): a list of wire-format
  operation dicts plus the predicted next snapshot.

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


# ---- reconciliation result --------------------------------------------------


@dataclass(frozen=True)
class ReconcileResult:
    """Output of a pure reconciliation pass.

    ``ops`` is the sequenced list of wire-format operation dicts (the same
    shape ``recovery.build_snapshot_commit`` emits) to apply to the native
    tree. ``new_snapshot`` is the predicted state after all operations are
    applied.
    """

    ops: list[dict[str, Any]]
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
