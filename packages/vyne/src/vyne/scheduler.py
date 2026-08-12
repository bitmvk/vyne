"""Scheduler and commit coordinator for the Vyne Runtime.

Provides:

- ``CommitCoordinator`` — accepted/candidate/in-flight state machine with
  one-revision-in-flight gating, atomic promotion, and rollback (COORD-05).
- ``StateJournal`` — per-flush State-cell write journal for fault rollback.
- ``AcknowledgementMap`` — batch native-value acknowledgement map (SCHED-02).
- ``PassGuard`` — bounded render-pass loop guard (SCHED-03).
- ``RenderPhaseMutationError`` — raised when State.set is called during render.
- ``extract_acknowledgements`` — schema-driven ack extraction from event payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ---- render-phase guard -----------------------------------------------------


class RenderPhaseMutationError(RuntimeError):
    """Raised when State.set is called during a render pass.

    Mutating state during render can lead to infinite loops or partial
    publication.  State changes should be driven by event handlers or
    animation frames, never by the render pass itself.
    """

    def __init__(self) -> None:
        super().__init__(
            "State.set() cannot be called during a render pass. "
            "Move state mutations to event handlers or animation callbacks."
        )


# ---- acknowledgement map ----------------------------------------------------


class AcknowledgementMap:
    """Tracks native-controlled values acknowledged in an event batch.

    Every native event that reports a controlled value (e.g. text_change
    reports the new text) adds an entry keyed by (node_id, prop_name).
    During the next render, the diff suppresses equal-value set_prop ops
    for acknowledged entries while still emitting Python transforms,
    normalizations, and resets that differ from the native value.

    This replaces the old _NATIVE_PROP_SKIPS mechanism which only handled
    text_change and only for the current event.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[int, str], Any] = {}

    def acknowledge(self, node_id: int, prop_name: str, value: Any) -> None:
        """Record that the native side holds this value for this node/prop."""
        self._entries[(node_id, prop_name)] = value

    def clear(self) -> None:
        """Reset all acknowledgements (called after commit publication)."""
        self._entries.clear()

    def should_suppress(self, node_id: int, prop_name: str, desired_value: Any) -> bool:
        """Return True if the desired value equals the acknowledged native value.

        This suppresses redundant set_prop ops for values that the native
        side already holds, preventing double-updates that can cause
        cursor jumps in TextInput or visual flicker.
        """
        key = (node_id, prop_name)
        if key not in self._entries:
            return False
        return self._entries[key] == desired_value

    def acknowledged_value(self, node_id: int, prop_name: str) -> Any:
        """Return the acknowledged native value, or None if not present."""
        return self._entries.get((node_id, prop_name))

    @property
    def entries(self) -> dict[tuple[int, str], Any]:
        """Return a copy of all acknowledgement entries (for testing)."""
        return dict(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


# ---- pass guard -------------------------------------------------------------


class PassGuard:
    """Bounded top-level render pass invariant.

    Prevents accidental infinite re-render loops caused by state mutation
    during render.  When the guard trips (too many passes in one batch),
    the runtime routes to controlled recovery instead of hanging.

    Reset on every external mount/direct/async/event flush; nested
    rerenders share one bound.
    """

    MAX_PASSES_PER_FLUSH = 5

    def __init__(self) -> None:
        self._pass_count = 0

    @property
    def pass_count(self) -> int:
        """Number of render passes executed this flush."""
        return self._pass_count

    def begin_flush(self) -> None:
        """Reset the per-flush pass counter."""
        self._pass_count = 0

    def enter_pass(self) -> None:
        """Increment the pass counter; raise if limit exceeded."""
        self._pass_count += 1
        if self._pass_count > self.MAX_PASSES_PER_FLUSH:
            raise RuntimeError(
                f"Render pass limit ({self.MAX_PASSES_PER_FLUSH}) exceeded. "
                "This usually means state is being mutated during render. "
                "Check for State.set() calls inside component functions."
            )


# ---- state journal ----------------------------------------------------------


@dataclass
class _JournalEntry:
    """One recorded State mutation for potential rollback."""
    state_cell: Any  # State[T]
    old_value: Any


class StateJournal:
    """Per-flush journal for State cell writes.

    When a flush begins, the journal starts recording State.set() calls.
    On flush success, the journal is committed (no-op — values are already
    applied).  On flush failure (handler, render, plan, encode, or send
    error), the journal rolls back every State cell to its pre-flush value.

    This ensures that a failed event handler or render pass does not leave
    component state in an inconsistent state despite the component tree
    being reset to the error commit.
    """

    def __init__(self) -> None:
        self._entries: dict[int, _JournalEntry] = {}  # keyed by id(State)
        self._active: bool = False

    @property
    def active(self) -> bool:
        """Whether the journal is currently recording."""
        return self._active

    @property
    def entry_count(self) -> int:
        """Number of recorded entries (for testing)."""
        return len(self._entries)

    def begin(self) -> None:
        """Start a new journal session.  Must be called before any handler runs."""
        self._entries.clear()
        self._active = True

    def record(self, state_cell: Any, new_value: Any) -> None:
        """Record a state mutation for potential rollback.

        Called by State.set() when the journal is active.  The first
        write to a State cell in a flush captures the pre-flush value
        so we can restore it on rollback.  Subsequent writes to the
        same cell in the same flush update the in-memory value but
        keep the original old_value for rollback.
        """
        if not self._active:
            return
        state_id = id(state_cell)
        if state_id not in self._entries:
            # First mutation of this cell in this flush: save pre-flush value.
            self._entries[state_id] = _JournalEntry(
                state_cell=state_cell,
                old_value=state_cell._value,
            )
        # Apply the new value immediately (optimistic).
        state_cell._value = new_value

    def record_from(
        self,
        state_cell: Any,
        old_value: Any,
        new_value: Any,
    ) -> None:
        """Record a deferred write with an explicitly accepted baseline."""
        if not self._active:
            return
        state_id = id(state_cell)
        if state_id not in self._entries:
            self._entries[state_id] = _JournalEntry(
                state_cell=state_cell,
                old_value=old_value,
            )
        state_cell._value = new_value

    def commit(self) -> None:
        """Commit all journaled changes (flush succeeded).

        Values are already applied in the State cells; we just clear
        the journal so rollback is no longer possible.
        """
        self._entries.clear()
        self._active = False

    def rollback(self) -> None:
        """Rollback every journaled State cell to its pre-flush value."""
        for entry in self._entries.values():
            entry.state_cell._value = entry.old_value
        self._entries.clear()
        self._active = False


# ---- commit coordinator -----------------------------------------------------


@dataclass
class _AcceptedState:
    """Immutable snapshot of the accepted (acknowledged) runtime state."""
    root: Any | None  # RenderNode | None
    node_index: dict[int, Any]  # dict[int, RenderNode]
    revision: int
    next_node_id: int


class CommitCoordinator:
    """Owns the accepted/candidate/in-flight commit lifecycle.

    The coordinator enforces:
    - At most one revision in flight at a time.
    - Planning/encoding must not mutate the accepted state.
    - Atomic promotion on matching OK acknowledgement.
    - Known rejection discards the candidate and preserves accepted.
    - Unknown native state retains the candidate as desired state and
      requires a complete snapshot for resynchronization.

    This replaces the previous practice of mutating self._root,
    self._node_index, self._ref_map, and self._next_node_id inline
    during rendering — those mutations could leave the runtime in an
    inconsistent state if encoding or transport failed.
    """

    def __init__(self) -> None:
        self._accepted: _AcceptedState | None = None
        self._next_node_id: int = 1
        # In-flight tracking.
        self._in_flight_revision: int = 0
        # Candidate (staged but not yet published).
        self._candidate_root: Any | None = None  # RenderNode | None
        self._candidate_index: dict[int, Any] | None = None  # dict[int, RenderNode]
        self._candidate_ref_map: dict[int, Any] | None = None
        self._candidate_event_registry: Any | None = None
        self._candidate_imperative_bindings: dict[Any, Any] | None = None
        # Ref map, handlers, and imperative bindings reflect accepted state.
        self._ref_map: dict[int, Any] = {}
        self._accepted_event_registry: Any | None = None
        self._imperative_bindings: dict[Any, Any] = {}
        self._last_ref_transition: tuple[dict[int, Any], dict[int, Any]] | None = None
        self._last_imperative_transition: (
            tuple[dict[Any, Any], dict[Any, Any]] | None
        ) = None
        # Provisional send captures synchronous acknowledgements without
        # publishing a candidate before send() returns.
        self._provisional: bool = False
        self._held_ack_revision: int | None = None

    # ---- read-only accessors ------------------------------------------------

    @property
    def accepted_root(self) -> Any | None:
        """The last exactly acknowledged root, never a staged candidate."""
        return self._accepted.root if self._accepted is not None else None

    @property
    def accepted_index(self) -> dict[int, Any]:
        """The accepted node_index (node_id -> RenderNode)."""
        if self._accepted is None:
            return {}
        return self._accepted.node_index

    @property
    def accepted_revision(self) -> int:
        """The last acknowledged revision, or 0."""
        if self._accepted is None:
            return 0
        return self._accepted.revision

    @property
    def next_node_id(self) -> int:
        """The next monotonic node ID to allocate."""
        return self._next_node_id

    @property
    def ref_map(self) -> dict[int, Any]:
        """Read-only view of the accepted ref map."""
        return self._ref_map

    @property
    def accepted_event_registry(self) -> Any | None:
        return self._accepted_event_registry

    @property
    def accepted_imperative_bindings(self) -> dict[Any, Any]:
        return dict(self._imperative_bindings)

    @property
    def desired_imperative_bindings(self) -> dict[Any, Any]:
        if self._candidate_imperative_bindings is not None:
            return dict(self._candidate_imperative_bindings)
        return dict(self._imperative_bindings)

    @property
    def in_flight(self) -> bool:
        """True when a commit has been sent and we're awaiting ack."""
        return self._in_flight_revision > 0

    @property
    def in_flight_revision(self) -> int:
        """The revision of the in-flight commit, or 0."""
        return self._in_flight_revision

    @property
    def desired_root(self) -> Any | None:
        """Return the staged desired root, falling back to accepted state."""
        return self._candidate_root or self.accepted_root

    @property
    def candidate_index(self) -> dict[int, Any]:
        """Return the currently staged node index without exposing storage."""
        return self._candidate_index or {}

    # ---- staging ------------------------------------------------------------

    def stage_candidate(
        self,
        root: Any,
        node_index: dict[int, Any],
        next_node_id: int,
        *,
        ref_map: dict[int, Any] | None = None,
        event_registry: Any | None = None,
        imperative_bindings: dict[Any, Any] | None = None,
    ) -> None:
        """Stage a candidate tree produced by the reconciliation planner.

        At this point the candidate has been planned and the commit ops
        have been encoded/validated. ``reserve_send()`` makes the candidate
        provisionally in-flight before transport publication.
        """
        if self.in_flight:
            raise RuntimeError("Cannot stage while another revision is in flight")
        self._candidate_root = root
        self._candidate_index = node_index
        self._next_node_id = next_node_id
        self._candidate_ref_map = dict(ref_map) if ref_map is not None else dict(self._ref_map)
        self._candidate_event_registry = event_registry
        self._candidate_imperative_bindings = (
            dict(imperative_bindings)
            if imperative_bindings is not None
            else dict(self._imperative_bindings)
        )

    def has_candidate(self) -> bool:
        """True if a candidate has been staged."""
        return self._candidate_root is not None

    def discard_staged(self) -> None:
        if not self.in_flight:
            self._discard_candidate()

    # ---- send / promote / reject / reset ------------------------------------

    def reserve_send(self, revision: int) -> None:
        """Reserve identity before send so synchronous receipts can be held."""
        if not self.has_candidate() or self.in_flight:
            raise RuntimeError("Cannot reserve provisional send")
        self._reserve_provisional(revision)

    def reserve_effect_send(self, revision: int) -> None:
        """Reserve an effect-only revision without staging a tree."""
        if self.has_candidate() or self.in_flight:
            raise RuntimeError("Cannot reserve effect-only send")
        self._reserve_provisional(revision)

    def _reserve_provisional(self, revision: int) -> None:
        self._in_flight_revision = revision
        self._provisional = True
        self._held_ack_revision = None

    def hold_provisional_ack(self, revision: int) -> bool:
        if self._provisional and revision == self._in_flight_revision:
            self._held_ack_revision = revision
            return True
        return False

    def finish_send(self, revision: int) -> bool:
        if not self._provisional or revision != self._in_flight_revision:
            raise RuntimeError("Provisional send identity mismatch")
        self._provisional = False
        held = self._held_ack_revision == revision
        self._held_ack_revision = None
        return held

    def abort_send(self, revision: int) -> bool:
        if revision != self._in_flight_revision:
            return False
        self._discard_candidate()
        self._in_flight_revision = 0
        self._provisional = False
        self._held_ack_revision = None
        return True

    def promote_local(self) -> bool:
        """Promote a candidate whose plan contains no native operations."""
        if not self.has_candidate() or self.in_flight:
            return False
        revision = self.accepted_revision
        self._in_flight_revision = revision if revision > 0 else -1
        return self.promote(self._in_flight_revision)

    def promote(self, revision: int) -> bool:
        """Atomically promote the in-flight revision to accepted.

        Returns True if promotion succeeded (matching revision).
        Returns False for stale acknowledgements (wrong revision).

        On promotion:
        - If a candidate exists, it becomes the new accepted state.
        - If no candidate (effect-only commit), the accepted state revision
          is updated but the tree remains unchanged.
        - Pending Ref attachments and invalidations are applied.
        - In-flight state is cleared.
        """
        if revision != self._in_flight_revision:
            return False

        if self._provisional:
            return False

        if self.has_candidate():
            old_refs = dict(self._ref_map)
            new_refs = dict(self._candidate_ref_map or {})
            old_bindings = dict(self._imperative_bindings)
            new_bindings = dict(self._candidate_imperative_bindings or {})
            self._ref_map = new_refs
            self._imperative_bindings = new_bindings
            self._accepted_event_registry = self._candidate_event_registry
            self._accepted = _AcceptedState(
                root=self._candidate_root,
                node_index=self._candidate_index or {},
                revision=revision,
                next_node_id=self._next_node_id,
            )
            self._last_ref_transition = (old_refs, new_refs)
            self._last_imperative_transition = (old_bindings, new_bindings)
            self._candidate_root = None
            self._candidate_index = None
            self._candidate_ref_map = None
            self._candidate_event_registry = None
            self._candidate_imperative_bindings = None
        elif self._accepted is not None:
            # Effect-only: update revision on accepted state.
            self._accepted = _AcceptedState(
                root=self._accepted.root,
                node_index=self._accepted.node_index,
                revision=revision,
                next_node_id=self._next_node_id,
            )

        # Clear pending state.
        self._in_flight_revision = 0
        return True

    def reject_known(self, revision: int) -> bool:
        """Known rejection: discard the candidate, preserve accepted.

        Returns True if the rejection was for the current in-flight revision.
        Stale rejections (wrong revision) are ignored.
        """
        if revision != self._in_flight_revision:
            return False

        self._discard_candidate()
        self._in_flight_revision = 0
        self._provisional = False
        self._held_ack_revision = None
        return True

    def _discard_candidate(self) -> None:
        self._candidate_root = None
        self._candidate_index = None
        self._candidate_ref_map = None
        self._candidate_event_registry = None
        self._candidate_imperative_bindings = None
        self._next_node_id = (
            self._accepted.next_node_id if self._accepted is not None else 1
        )

    def take_ref_transition(self) -> tuple[dict[int, Any], dict[int, Any]] | None:
        transition = self._last_ref_transition
        self._last_ref_transition = None
        return transition

    def take_imperative_transition(
        self,
    ) -> tuple[dict[Any, Any], dict[Any, Any]] | None:
        transition = self._last_imperative_transition
        self._last_imperative_transition = None
        return transition

    def report_unknown(self) -> None:
        """Native state is unknown after a sent candidate.

        The candidate remains as the desired Python state. The Runtime
        recovery state selects a complete snapshot for the next publication;
        this coordinator only clears the in-flight transport identity.
        """
        self._in_flight_revision = 0

    def reset_accepted(self) -> None:
        """Clear the accepted state (e.g., on error commit that resets the tree).

        This discards both accepted and candidate state and starts fresh.
        All pending refs are invalidated via the caller.
        """
        self._accepted = None
        self._discard_candidate()
        self._accepted_event_registry = None
        self._ref_map.clear()
        self._imperative_bindings.clear()
        self._last_ref_transition = None
        self._last_imperative_transition = None
        self._in_flight_revision = 0
        self._provisional = False
        self._held_ack_revision = None

    # ---- ref management -----------------------------------------------------

    def clear_all_refs(self) -> list[Any]:
        """Clear all refs and return them for invalidation."""
        refs = list(self._ref_map.values())
        self._ref_map.clear()
        self._candidate_ref_map = None
        return refs

    def clear_all_imperative_bindings(self) -> list[Any]:
        """Clear accepted bindings and return their controller targets."""
        targets = list(self._imperative_bindings)
        self._imperative_bindings.clear()
        self._candidate_imperative_bindings = None
        self._last_imperative_transition = None
        return targets


# ---- schema-driven acknowledgement extraction -------------------------------


# Maps event name -> list of (payload_field, canonical_prop_name) pairs.
# This is generated from the authoritative EVENT_SPECS and replaces the
# hardcoded _record_acknowledgement in Runtime.
_ACK_EXTRACTORS: dict[str, list[tuple[str, str]]] = {}


def _build_ack_extractors() -> dict[str, list[tuple[str, str]]]:
    """Build ack extractors from the event schema.

    For each event that carries a controlled-value payload, we extract
    the field->prop mapping from the authoritative EVENT_SPECS so the
    runtime can record native-value acknowledgements without hardcoding
    event names.
    """
    from vyne.spec.schema_v2 import EVENT_SPECS
    extractors: dict[str, list[tuple[str, str]]] = {}

    for event_name, spec in EVENT_SPECS.items():
        if spec.controlled_props:
            extractors[event_name] = list(spec.controlled_props.items())

    return extractors


_ACK_EXTRACTORS = _build_ack_extractors()


def extract_acknowledgements(
    event_name: str,
    target: int,
    payload: dict[str, Any],
    ack_map: AcknowledgementMap,
) -> None:
    """Extract native-value acknowledgements from an event and record them.

    This is the single entry point for schema-driven ack extraction.
    It replaces the previous hardcoded _record_acknowledgement method.

    Args:
        event_name: The canonical event name (e.g., "text_change").
        target: The target node ID.
        payload: The event payload dict.
        ack_map: The AcknowledgementMap to record values into.
    """
    extractors = _ACK_EXTRACTORS.get(event_name)
    if extractors is None:
        return
    for payload_field, prop_name in extractors:
        value = payload.get(payload_field)
        if value is not None:
            ack_map.acknowledge(target, prop_name, value)
