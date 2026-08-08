"""Python runtime, scheduler, and platform-neutral patch generation.

The Runtime is the heart of Vyne.  It owns the entire lifecycle:

1. Calls the user's root component function to produce an Element tree.
2. Diffs the new tree against the previous RenderNode tree to compute
   a minimal set of patch operations (create / set_prop / insert_child / ...).
3. Sends those operations through a Transport to the native Android host.
4. Receives events from the native side and dispatches them to user
   handlers, then re-renders.

A simplified React-like hook model powers state: each explicit component
scope tracks an ordered list of State cells and reassigns them to hook calls
by index across re-renders. Conditional hook calls or reordering within a
component are forbidden.

Reconciliation (CORE-01): uses a pure reconciliation planner with mutable
native-order shadow lists per parent, ensuring sequential move ops use
correct indices after each shadow update.

Commit coordinator (COORD-05): the ``CommitCoordinator`` owns the accepted/
candidate/in-flight state machine.  At most one revision is in flight.
Planning and validation occur on a deep-copied working snapshot; the accepted
state is never mutated before transport acknowledgement.  Matching OK
atomically promotes the candidate; known rejection discards it and preserves
the accepted baseline.  Unknown native state triggers a complete snapshot.

State journal (COORD-05): during a flush (event dispatch + render pass),
State.set() records mutations in the ``StateJournal``.  On flush failure
the journal rolls back every mutated State cell to its pre-flush value.

Render batching: state changes during event dispatch are batched so that
multiple state updates within a single event handler produce only one commit.
The ``dispatch_events()`` method extends this to batches of native events.

Native commands are queued during event dispatch and merged into the next
render commit. Animation and imperative effect commands share the same commit
publication path and can also publish without a tree change (SCHED-01).

Native-value acknowledgements (SCHED-02): every batch acknowledgement is
keyed by (node_id, canonical_prop); equal desired echoes suppress while
Python transforms/resets still emit.  Ack extraction is schema-driven via
``extract_acknowledgements()``.

Render-phase mutation guard (SCHED-03): State.set checks the runtime phase
and raises before changing state during root, nested, or component render.
A bounded pass guard prevents accidental infinite re-render loops.

Scoped reconciliation (SCHED-04): removed in favor of full-tree
reconciliation with component output caching. Dirty components re-execute
but reconciliation always covers the full tree.

Recovery state machine (CORE-02): tracks native synchronization health
via RecoveryState transitions, gates incremental commits on acknowledged
ApplyResult, and handles native-reported failures with snapshot resets.

Ref lifecycle: Ref.attach() is called on mount, Ref.invalidate() on
removal/replacement/disposal.  ViewHandle validity is respected by
animation and imperative access paths.  Ref promotion is gated on
commit acknowledgement (COORD-05).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import deque
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from threading import Event as ThreadEvent
from threading import Lock
from uuid import uuid4
from typing import TYPE_CHECKING, Any
from weakref import ReferenceType, ref

from vyne.async_runtime import AsyncRuntimeDispatcher
from vyne._effects import NativeViewEffect
from vyne.elements import Element, event_name_for_prop, normalize_child
from vyne.motion import (
    Cancel,
    DriverCancel,
    DriverSetTarget,
    MotionCommand,
    PresentationSlot,
    SetTarget,
    motion_command_to_dict,
)
from vyne.events import Event, EventRegistry, _wrap_handler, event_delivery
from vyne.animations import AnimationEvent, AnimationHandle
from vyne.lowering import lower_element, CanonicalElement
from vyne.protocol import (
    MSG_COMMIT,
    MSG_EVENT,
    OP_CREATE,
    OP_INSERT_CHILD,
    OP_LISTEN,
    OP_LISTEN_LATEST,
    OP_SET_PROP,
    OP_SET_PROPS,
    OP_UNLISTEN,
    JsonObject,
    error_commit,
    validate_message,
)
from vyne.reconcile import plan_reconcile
from vyne.recovery import (
    RecoveryState,
    build_snapshot_commit,
)
from vyne.refs import Ref, ViewHandle
from vyne.scheduler import (
    AcknowledgementMap,
    CommitCoordinator,
    PassGuard,
    RenderPhaseMutationError,
    StateJournal,
    extract_acknowledgements,
)
from vyne.state import State, runtime_context
from vyne.transport import MemoryTransport, Transport
from vyne.render_model import RenderNode, RenderSnapshot

if TYPE_CHECKING:
    from vyne.animations import _AnimatedDriver


_ACTIVE_ASYNC_CALLBACKS: ContextVar[Any | None] = ContextVar(
    "vyne_active_async_callbacks",
    default=None,
)


@dataclass(eq=False)
class ComponentScope:
    """Runtime-owned state and cached output for one ``@component`` call."""

    function: Callable[..., Element]
    parent: "ComponentScope | None"
    key: Any | None = None
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    hooks: list[State[Any] | _AnimatedDriver] = field(default_factory=list)
    hook_index: int = 0
    expected_hook_count: int | None = None
    children: list["ComponentScope"] = field(default_factory=list)
    child_index: int = 0
    output: Element | None = None
    # The RenderNode ID of this scope's mounted root element (None if not mounted).
    root_node_id: int | None = None
    dirty: bool = True
    descendant_dirty: bool = False
    mounted: bool = True


@dataclass
class _ComponentChildFrame:
    """One in-progress child-scope reconciliation for a component render."""

    old_children: tuple[ComponentScope, ...]
    next_children: list[ComponentScope] = field(default_factory=list)
    reused: set[ComponentScope] = field(default_factory=set)
    seen_keys: set[Any] = field(default_factory=set)
    keyed_old: dict[Any, ComponentScope] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for child in self.old_children:
            if child.key is None:
                continue
            if child.key in self.keyed_old:
                raise RuntimeError(
                    f"Duplicate existing component key: {child.key!r}"
                )
            self.keyed_old[child.key] = child


# Recovery matrix (design-pattern #5): the only legal directed transitions.
# SYNCED -> AWAITING_APPLY | NEEDS_RESET; AWAITING_APPLY -> SYNCED | NEEDS_RESET;
# NEEDS_RESET -> AWAITING_APPLY | SYNCED; any non-disposed -> FAULTED;
# FAULTED -> NEEDS_RESET; any -> DISPOSED. Self-transitions are idempotent.
_RECOVERY_TRANSITIONS: dict[RecoveryState, frozenset[RecoveryState]] = {
    RecoveryState.SYNCED: frozenset({
        RecoveryState.AWAITING_APPLY,
        RecoveryState.NEEDS_RESET,
        RecoveryState.FAULTED,
        RecoveryState.DISPOSED,
    }),
    RecoveryState.AWAITING_APPLY: frozenset({
        RecoveryState.SYNCED,
        RecoveryState.NEEDS_RESET,
        RecoveryState.FAULTED,
        RecoveryState.DISPOSED,
    }),
    RecoveryState.NEEDS_RESET: frozenset({
        RecoveryState.AWAITING_APPLY,
        RecoveryState.SYNCED,
        RecoveryState.FAULTED,
        RecoveryState.DISPOSED,
    }),
    RecoveryState.FAULTED: frozenset({
        RecoveryState.NEEDS_RESET,
        RecoveryState.DISPOSED,
    }),
    RecoveryState.DISPOSED: frozenset({RecoveryState.DISPOSED}),
}


class _FrameworkTransaction:
    """Own one Runtime's rollback, publication, and recovery state.

    Component execution remains a Runtime responsibility, but all state which
    decides whether a render may be promoted or must be rolled back lives
    here.  This keeps the accepted/candidate tree, State journal, component
    checkpoint, and native recovery phase under one lifecycle owner.
    """

    def transition_to(
        self,
        next_state: RecoveryState,
        *,
        cause: str | None = None,
    ) -> None:
        """The one authorized way to change recovery state.

        Enforces the recovery matrix: illegal transitions fail loudly
        instead of drifting; self-transitions are idempotent no-ops
        (design-pattern #5).
        """
        current = self.recovery_state
        if next_state is current:
            return
        if next_state not in _RECOVERY_TRANSITIONS[current]:
            detail = f" (cause: {cause})" if cause is not None else ""
            raise RuntimeError(
                f"Illegal recovery transition {current.name} -> "
                f"{next_state.name}{detail}"
            )
        self.recovery_state = next_state

    def __init__(self) -> None:
        self.commits = CommitCoordinator()
        self.states = StateJournal()
        self.recovery_state = RecoveryState.SYNCED
        self._component_checkpoint: (
            dict[ComponentScope, tuple[Any, ...]] | None
        ) = None

    def capture_components(self, root_scope: ComponentScope) -> None:
        if self._component_checkpoint is not None:
            return
        states: dict[ComponentScope, tuple[Any, ...]] = {}
        stack = [root_scope]
        while stack:
            scope = stack.pop()
            states[scope] = (
                scope.args, dict(scope.kwargs), list(scope.hooks), scope.hook_index,
                scope.expected_hook_count, list(scope.children), scope.child_index,
                scope.output, scope.root_node_id, scope.dirty,
                scope.descendant_dirty, scope.mounted,
            )
            stack.extend(scope.children)
        self._component_checkpoint = states

    def rollback_components(self) -> None:
        checkpoint = self._component_checkpoint
        self._component_checkpoint = None
        if checkpoint is None:
            return
        for scope, values in checkpoint.items():
            (
                scope.args, scope.kwargs, scope.hooks, scope.hook_index,
                scope.expected_hook_count, scope.children, scope.child_index,
                scope.output, scope.root_node_id, scope.dirty,
                scope.descendant_dirty, scope.mounted,
            ) = values

    def commit_components(self) -> None:
        self._component_checkpoint = None

    def commit_framework(self) -> None:
        self.states.commit()
        self.commit_components()

    def rollback_framework(self) -> None:
        self.states.rollback()
        self.rollback_components()

    def dispose(self) -> None:
        self.states.rollback()
        self._component_checkpoint = None
        self.transition_to(RecoveryState.DISPOSED, cause="renderer disposed")


@dataclass(eq=False)
class ExternalCallbackSubscription:
    """Runtime-owned callable registered for application Android code."""

    id: int
    callback: Callable[[Any], Any] | None
    _runtime: ReferenceType["Runtime"]
    active: bool = True
    native_handle: Any | None = None

    def attach_native(self, native_handle: Any) -> None:
        """Attach the Android ingress handle to this Runtime lifecycle."""
        if not self.active:
            native_handle.dispose()
            return
        self.native_handle = native_handle

    def deactivate(self) -> None:
        """Release the user callable and reject all later deliveries."""
        self.active = False
        self.callback = None
        native_handle = self.native_handle
        self.native_handle = None
        if native_handle is not None:
            try:
                native_handle.dispose()
            except Exception:
                pass


@dataclass
class _DeferredStateMutation:
    """A state write made after an earlier commit was sent."""

    state_cell: State[Any]
    baseline: Any
    value: Any


@dataclass
class _AnimationRegistration:
    """Python lifecycle state for one native-owned animation."""

    handle: AnimationHandle
    command: SetTarget | DriverSetTarget
    on_complete: Callable[[AnimationEvent], Any] | None
    on_cancel: Callable[[AnimationEvent], Any] | None


@dataclass(frozen=True)
class _ImperativeBindingIntent:
    """Candidate controller state anchored to one rendered Ref."""

    target: Any
    value: Any
    anchor_ref: Ref


@dataclass(frozen=True)
class _AnimationCheckpoint:
    """Animation registrations and queued commands at a transaction boundary."""

    animation_ids: frozenset[int]
    pending: tuple[MotionCommand, ...]
    driver_targets: tuple[tuple[int, float], ...]


class _AsyncCallbackManager:
    """Schedule returned awaitables and flush state at suspension boundaries."""

    def __init__(self, runtime: "Runtime") -> None:
        self.runtime = runtime
        self._tasks: set[Any] = set()
        self._task_lock = Lock()
        self._idle = ThreadEvent()
        self._idle.set()
        self._flush_handle: asyncio.Handle | None = None
        self._flush_origin: Event | None = None
        self._flush_error: Exception | None = None
        self._fallback_dispatcher: AsyncRuntimeDispatcher | None = None

    @property
    def active(self) -> bool:
        return _ACTIVE_ASYNC_CALLBACKS.get() is self

    def schedule(self, awaitable: Any, origin: Event | None) -> None:
        """Start one callback awaitable without changing the callback API."""
        with self._task_lock:
            self._idle.clear()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            if self._fallback_dispatcher is None:
                self._fallback_dispatcher = AsyncRuntimeDispatcher()
            future = self._fallback_dispatcher.submit(
                lambda: self._run(awaitable, origin)
            )
            self._track_task(future)
            return

        task = loop.create_task(self._run(awaitable, origin))
        self._track_task(task)

    def _track_task(self, task: Any) -> None:
        with self._task_lock:
            self._tasks.add(task)

        def finished(completed: Any) -> None:
            # Retrieve errors so neither asyncio nor concurrent.futures emits
            # an unhandled-task diagnostic. _run has already reported them.
            try:
                completed.result()
            except (asyncio.CancelledError, Exception):
                pass
            with self._task_lock:
                self._tasks.discard(completed)
                if not self._tasks:
                    self._idle.set()

        task.add_done_callback(finished)

    async def _run(self, awaitable: Any, origin: Event | None) -> None:
        token = _ACTIVE_ASYNC_CALLBACKS.set(self)
        previous_event = self.runtime._current_event
        previous_phase = self.runtime._phase
        self.runtime._current_event = origin
        self.runtime._phase = "event"
        try:
            with runtime_context(self.runtime):
                await awaitable
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.fail(exc, origin)
        finally:
            self.runtime._current_event = previous_event
            self.runtime._phase = previous_phase
            _ACTIVE_ASYNC_CALLBACKS.reset(token)

    def request_flush(self, origin: Event | None) -> None:
        self._flush_origin = origin
        if self._flush_handle is None:
            loop = asyncio.get_running_loop()
            self._flush_handle = loop.call_soon(self.flush_now)

    def fail(self, error: Exception, origin: Event | None) -> None:
        self._flush_error = error
        self.request_flush(origin)

    def flush_now(self) -> None:
        handle = self._flush_handle
        self._flush_handle = None
        if handle is not None and not handle.cancelled():
            handle.cancel()
        origin = self._flush_origin
        error = self._flush_error
        self._flush_origin = None
        self._flush_error = None

        if error is not None:
            self.runtime._handle_async_callback_failure(error)
            return

        try:
            self.runtime._flush_batched_render(origin)
            if not self.runtime._coordinator.in_flight:
                self.runtime._commit_framework()
        except Exception as exc:
            self.runtime._state_journal.rollback()
            self.runtime._send_error_commit(str(exc))

    async def settle(self) -> None:
        """Run newly scheduled callbacks through their first useful yield."""
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        if self._flush_handle is not None or self._flush_error is not None:
            self.flush_now()

    def wait(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout)

    def dispose(self) -> None:
        with self._task_lock:
            tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        fallback = self._fallback_dispatcher
        self._fallback_dispatcher = None
        if fallback is not None:
            fallback.close()


# ---- runtime ----------------------------------------------------------------


class Runtime:
    """Owns user component execution and framework-side event dispatch.

    This is the single-owner orchestrator.  A host (test runner, Android JNI
    bridge, or CLI) creates one Runtime per application and calls ``mount()``.
    After that, the Runtime drives itself: user events trigger renders, which
    produce commits, which flow out through the transport.
    """

    def __init__(
        self,
        root_component: Callable[..., Element],
        *,
        root_args: tuple[Any, ...] = (),
        transport: Transport | None = None,
        pre_launch_hooks: tuple = (),
        session_id: str | None = None,
    ) -> None:
        self.pre_launch_hooks = pre_launch_hooks
        self._phase_context: ContextVar[str | None] = ContextVar(
            f"vyne_runtime_phase_{id(self)}",
            default=None,
        )
        self._event_context: ContextVar[Event | None] = ContextVar(
            f"vyne_runtime_event_{id(self)}",
            default=None,
        )
        # Session identity is part of every native receipt (design-pattern
        # #1): one uuid4 per direct session, generated by start_direct and
        # threaded through the transport into this Runtime, so receipts are
        # session-scoped.  Other hosts (tests, MemoryTransport, CLI) default
        # to a fresh uuid — the old shared literal is gone.
        self.session_id = session_id if session_id is not None else uuid4().hex
        self.root_component = getattr(
            root_component,
            "__vyne_component_function__",
            root_component,
        )
        self.transport = transport or MemoryTransport()
        # Auto-wire MemoryTransport for auto-acknowledgement (CORE-02).
        if hasattr(self.transport, 'set_runtime'):
            self.transport.set_runtime(self)
        self.events = EventRegistry()

        # Accepted/candidate publication, rollback, and recovery have one owner.
        self._transaction = _FrameworkTransaction()

        self.revision = 0
        self._mounted = False
        self._rendering = False
        self._needs_render = False
        self._batching_events = False
        self._batched_origin_event: Event | None = None
        self._root_scope = ComponentScope(
            self.root_component,
            None,
            args=tuple(root_args),
        )
        self._root_argument_count = len(root_args)
        self._pending_root_arguments: deque[tuple[Any, ...]] = deque()
        self._draining_root_arguments = False
        # App lifecycle: the cached state and the app's subscriptions.
        self.current_app_state: str = "active"
        self._app_state_handlers: list[Callable[[str], Any]] = []
        self._back_handlers: list[Callable[[], Any]] = []
        self._current_component_scope: ComponentScope | None = None
        self._component_child_frames: dict[
            ComponentScope, _ComponentChildFrame
        ] = {}
        self._render_imperative_bindings: (
            dict[Any, _ImperativeBindingIntent] | None
        ) = None
        self._render_staged_binding_targets: set[Any] | None = None
        self._hooks = self._root_scope.hooks
        # Render-phase tracking for mutation guard (SCHED-03).
        self._phase: str | None = None
        self._current_event: Event | None = None
        self.latest_commit: JsonObject | None = None
        self._anim_pending: list[MotionCommand] = []
        self._effect_pending: list[NativeViewEffect] = []
        self._effect_checkpoint: tuple[NativeViewEffect, ...] | None = None
        self._next_animation_id = 1
        self._animations: dict[int, _AnimationRegistration] = {}
        self._animation_checkpoint: _AnimationCheckpoint | None = None
        self._animation_ids_by_revision: dict[int, frozenset[int]] = {}
        self._next_animated_driver_id = 1
        self._animated_drivers: dict[int, _AnimatedDriver] = {}
        # Acknowledgement map (SCHED-02).
        self._ack_map = AcknowledgementMap()
        # Pass guard (SCHED-03).
        self._pass_guard = PassGuard()
        # Terminal fault bounding (RE-6): consecutive failures counter.
        self._consecutive_faults: int = 0
        self._max_consecutive_faults: int = 5
        # Last error message for diagnostic purposes.
        self._last_error: str | None = None
        # Elements are immutable. Reused component outputs can therefore reuse
        # their lowered canonical subtrees by object identity.
        self._lower_identity_cache: dict[int, tuple[Element, CanonicalElement]] = {}
        self._on_initial_promotion: Callable[[], None] | None = None
        self._on_initial_rejection: Callable[[], None] | None = None
        self._next_external_callback_id = 1
        self._external_callbacks: dict[int, ExternalCallbackSubscription] = {}
        self._async_callbacks = _AsyncCallbackManager(self)
        self._deferred_async_state: dict[int, _DeferredStateMutation] = {}
        self._deferred_async_origin: Event | None = None

    @property
    def _phase(self) -> str | None:
        return self._phase_context.get()

    @_phase.setter
    def _phase(self, value: str | None) -> None:
        self._phase_context.set(value)

    @property
    def _current_event(self) -> Event | None:
        return self._event_context.get()

    @_current_event.setter
    def _current_event(self, value: Event | None) -> None:
        self._event_context.set(value)

    # Compatibility accessors for framework internals and diagnostic tests.
    # Ownership remains exclusively with _FrameworkTransaction.
    @property
    def _coordinator(self) -> CommitCoordinator:
        return self._transaction.commits

    @property
    def _state_journal(self) -> StateJournal:
        return self._transaction.states

    @property
    def _recovery_state(self) -> RecoveryState:
        return self._transaction.recovery_state

    def dispose(self) -> None:
        self.states.rollback()
        self._component_checkpoint = None
        self.transition_to(RecoveryState.DISPOSED, cause="renderer disposed")    # ---- public API ---------------------------------------------------------

    def mount(self) -> None:
        """Start the runtime: render the root component and emit the first commit.

        After mount, the runtime is live — any event dispatched from the
        native side will trigger re-renders automatically.
        """
        self._mounted = True
        self.request_render()
        self._drain_pending_root_arguments()

    def dispose(self) -> None:
        """Tear down the runtime and release all resources.

        Invalidates all live Refs, clears the node index, listener
        registrations, and the root tree.  After disposal the runtime
        cannot be remounted.
        """
        if self._recovery_state == RecoveryState.DISPOSED:
            return
        self._transaction.dispose()
        self._mounted = False
        self._async_callbacks.dispose()
        self._deferred_async_state.clear()
        self._deferred_async_origin = None

        # Invalidate all live refs (from coordinator).
        for ref in self._coordinator.clear_all_refs():
            try:
                ref.invalidate()
            except Exception:
                pass
        for target in self._coordinator.clear_all_imperative_bindings():
            try:
                target._accept_runtime_binding(None)
            except Exception:
                pass
        # Clear the coordinator.
        self._coordinator.reset_accepted()
        self._anim_pending.clear()
        self._effect_pending.clear()
        self._effect_checkpoint = None
        for registration in self._animations.values():
            registration.handle._finish("cancelled", "runtime_disposed")
        self._animations.clear()
        self._animated_drivers.clear()
        self._animation_checkpoint = None
        self._animation_ids_by_revision.clear()
        self._pending_root_arguments.clear()
        self._needs_render = False
        self._ack_map.clear()
        self.events.clear()
        for subscription in self._external_callbacks.values():
            subscription.deactivate()
        self._external_callbacks.clear()

    # ---- recovery state management (CORE-02) -------------------------------

    def acknowledge_native_apply(self, revision: int) -> None:
        """Confirm that native accepted the commit at *revision*.

        Called by the transport layer when the native side reports a
        successful ApplyResult.  Transitions AWAITING_APPLY → SYNCED
        and promotes the in-flight candidate to accepted (COORD-05).

        If the revision doesn't match the latest commit, the acknowledgement
        is silently ignored (it's for a prior commit).

        If a render was deferred while waiting for this ack (because
        another commit was gated), that render is now scheduled.
        """
        if self._recovery_state == RecoveryState.DISPOSED:
            return
        if type(revision) is not int or revision < 0:
            return
        if self._coordinator.hold_provisional_ack(revision):
            return
        if revision != self.revision:
            return
        if self._recovery_state == RecoveryState.AWAITING_APPLY:
            if not self._promote_candidate(revision):
                return
            self._transaction.transition_to(
                RecoveryState.SYNCED, cause="native ack accepted"
            )
            self._mark_revision_animations_running(revision)
            self._commit_framework()
            deferred_origin = self._adopt_deferred_async_state(rejected=False)
            if self._needs_render:
                previous_event = self._current_event
                self._current_event = deferred_origin
                try:
                    self._schedule_render()
                finally:
                    self._current_event = previous_event
            elif self._anim_pending or self._effect_pending:
                # Commands deferred while this commit was in flight have no
                # render to piggyback on. Publish them without tree changes.
                # The origin event is no longer available (SCHED-01).
                self._send_effect_only_commit(None)
            self._drain_pending_root_arguments()

    def _promote_candidate(self, revision: int) -> bool:
        if not self._coordinator.promote(revision):
            return False
        self._install_promoted_framework()
        callback = self._on_initial_promotion
        self._on_initial_promotion = None
        self._on_initial_rejection = None
        if callback is not None:
            callback()
        return True

    def _install_promoted_framework(self) -> None:
        candidate_events = self._coordinator.accepted_event_registry
        if candidate_events is not None:
            self.events = candidate_events
        transition = self._coordinator.take_ref_transition()
        if transition is not None:
            old_refs, new_refs = transition
            for node_id, ref in old_refs.items():
                if new_refs.get(node_id) is ref:
                    continue
                ref.invalidate()
            index = self._coordinator.accepted_index
            for node_id, ref in new_refs.items():
                if old_refs.get(node_id) is ref:
                    continue
                node = index[node_id]
                ref.attach(ViewHandle(node_id, node.kind))

        binding_transition = self._coordinator.take_imperative_transition()
        if binding_transition is not None:
            old_bindings, new_bindings = binding_transition
            for target in old_bindings.keys() - new_bindings.keys():
                target._accept_runtime_binding(None)
            for target, intent in new_bindings.items():
                target._accept_runtime_binding(intent.value)

    def report_native_failure(
        self,
        message: str = "",
        *,
        revision: int | None = None,
        unknown: bool = False,
    ) -> None:
        """Apply one exactly correlated native transaction outcome."""
        if self._recovery_state == RecoveryState.DISPOSED:
            return
        if type(revision) is not int or revision < 0:
            return
        if revision != self._coordinator.in_flight_revision:
            return
        self._last_error = message
        if unknown:
            self._coordinator.report_unknown()
            self._transaction.transition_to(
                RecoveryState.NEEDS_RESET, cause="native reported unknown"
            )
            # Desired state remains authoritative and is resent as a snapshot.
            self._reject_revision_animations(
                revision,
                reason="native_state_unknown",
            )
            self._commit_framework()
            deferred_origin = self._adopt_deferred_async_state(rejected=False)
            previous_event = self._current_event
            self._current_event = deferred_origin
            try:
                self._schedule_render()
            finally:
                self._current_event = previous_event
            self._drain_pending_root_arguments()
            return

        queued_after_send = tuple(self._effect_pending)
        if self._coordinator.reject_known(revision):
            self._rollback_framework()
            # Effects queued by later events while this revision was in
            # flight belong to the next transaction, not the rejected one.
            self._effect_pending = list(queued_after_send)
            self._effect_checkpoint = (() if queued_after_send else None)
            self._transaction.transition_to(
                RecoveryState.SYNCED, cause="native rejected known"
            )
            deferred_origin = self._adopt_deferred_async_state(rejected=True)
            callback = self._on_initial_rejection
            self._on_initial_promotion = None
            self._on_initial_rejection = None
            if callback is not None:
                callback()
            if self._needs_render:
                previous_event = self._current_event
                self._current_event = deferred_origin
                try:
                    self._schedule_render()
                finally:
                    self._current_event = previous_event
            elif self._effect_pending:
                self._send_effect_only_commit(None)
            self._drain_pending_root_arguments()

    @property
    def recovery_state(self) -> RecoveryState:
        """The current recovery state (read-only)."""
        return self._recovery_state

    def request_render(self) -> None:
        """Schedule a render, either immediately or deferred.

        If we're already inside a render pass or an event batch, we set
        a flag — the outer loop picks it up when it finishes.  Otherwise
        the render runs synchronously right now.

        If a commit is in-flight (COORD-05), the render is deferred.
        The subsequent render will coalesce any pending changes.
        """
        if not self._mounted:
            return
        self._capture_component_checkpoint()
        self._mark_component_tree_dirty(self._root_scope)
        self._schedule_render()

    @property
    def root_argument_count(self) -> int:
        """Number of positional inputs accepted by the hosted root app."""
        return self._root_argument_count

    def update_root_arguments(self, *args: Any) -> None:
        """Deliver one ordered root input update through the render coordinator.

        Updates which arrive while a native commit is in flight remain queued.
        Each update is rendered in delivery order after the preceding commit is
        resolved, so a rapid sequence of Android launches is not collapsed into
        only the final launch.
        """
        if len(args) != self._root_argument_count:
            raise TypeError(
                f"Root app expects {self._root_argument_count} argument(s), "
                f"got {len(args)}"
            )
        if self._recovery_state == RecoveryState.DISPOSED:
            return
        self._pending_root_arguments.append(tuple(args))
        self._drain_pending_root_arguments()

    def set_context_root(self, launch: Any) -> None:
        """Adopt the context-root shape: one AppContext argument per launch.

        The app entry point receives ``AppContext(launch, app_state,
        back_handler)``; the capability objects are stable, and ``launch``
        is replaced on every Android launch.
        """
        from vyne.context import AppContext, AppState, BackHandler

        self._root_argument_count = 1
        self._root_scope.args = (
            AppContext(
                launch=launch,
                app_state=AppState(self),
                back_handler=BackHandler(self),
            ),
        )

    def build_root_context(self, launch: Any) -> Any:
        """Build the root argument for a (warm) launch delivery."""
        from vyne.context import AppContext, AppState, BackHandler

        return AppContext(
            launch=launch,
            app_state=AppState(self),
            back_handler=BackHandler(self),
        )

    def use_state(self, initial: Any) -> State[Any]:
        """Allocate or return a State cell by index, React-style.

        Each call to ``state()`` during a render increments a counter.
        On first render, a new State cell is appended.  On subsequent
        renders, the cell at the same index is reused — which is why
        hooks must never be conditional or reordered.
        """
        if self._phase != "render":
            raise RuntimeError("state() can only be used while rendering a component")
        scope = self._current_component_scope
        if scope is None:
            raise RuntimeError("state() can only be used while rendering a component")
        index = scope.hook_index
        scope.hook_index += 1

        if scope.expected_hook_count is not None and index >= scope.expected_hook_count:
            raise RuntimeError("state() calls must not be conditional or reordered")
        if index == len(scope.hooks):
            scope.hooks.append(
                State(
                    initial,
                    lambda scope=scope: self._invalidate_component(scope),
                    _owner=self,
                )
            )
        hook = scope.hooks[index]
        if not isinstance(hook, State):
            raise RuntimeError("state() calls must not be conditional or reordered")
        return hook

    def set_state(self, state_cell: State[Any], value: Any) -> None:
        """StateHost: the single write path for a bound State cell.

        Render-phase guard (SCHED-03), the async-callback fast path, and
        the state journal (COORD-05) all live here — the cell just calls
        its owner.
        """
        if self.render_phase() == "render":
            raise RenderPhaseMutationError()
        if self._set_state_from_async_callback(state_cell, value):
            return
        if self._state_journal.active:
            self._state_journal.record(state_cell, value)
            state_cell._request_render()
            return
        state_cell._value = value
        state_cell._request_render()

    def render_phase(self) -> str | None:
        """StateHost: the runtime's current phase (None outside a flush)."""
        return self._phase

    def use_animated_value(self, initial: int | float) -> _AnimatedDriver:
        """Allocate or return one persistent Animated.Value hook."""
        if self._phase != "render":
            raise RuntimeError(
                "Animated.Value() can only be used while rendering a component"
            )
        scope = self._current_component_scope
        if scope is None:
            raise RuntimeError(
                "Animated.Value() can only be used while rendering a component"
            )
        index = scope.hook_index
        scope.hook_index += 1
        if scope.expected_hook_count is not None and index >= scope.expected_hook_count:
            raise RuntimeError("hook calls must not be conditional or reordered")
        from vyne.animations import _AnimatedDriver

        if index == len(scope.hooks):
            driver_id = self._next_animated_driver_id
            self._next_animated_driver_id += 1
            driver = _AnimatedDriver(self, driver_id, initial)
            scope.hooks.append(driver)
            self._animated_drivers[driver_id] = driver
        hook = scope.hooks[index]
        if not isinstance(hook, _AnimatedDriver):
            raise RuntimeError("hook calls must not be conditional or reordered")
        return hook

    def render_component(
        self,
        function: Callable[..., Element],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        component_key: Any | None = None,
        keyed: bool = False,
    ) -> Element:
        """Render or reuse one decorated component call in the active scope."""
        if self._phase != "render" or self._current_component_scope is None:
            raise RuntimeError("Components can only be called while rendering")

        parent = self._current_component_scope
        frame = self._component_child_frames.get(parent)
        if frame is None:
            raise RuntimeError("Component child reconciliation is not active")

        index = len(frame.next_children)
        parent.child_index += 1

        scope: ComponentScope | None = None
        if keyed:
            if component_key is None:
                raise TypeError("Keyed component calls require a non-None key")
            if component_key in frame.seen_keys:
                raise ValueError(
                    f"Duplicate component key in "
                    f"{parent.function.__name__}: {component_key!r}"
                )
            frame.seen_keys.add(component_key)
            candidate = frame.keyed_old.get(component_key)
            if (
                candidate is not None
                and candidate.function is function
                and candidate not in frame.reused
            ):
                scope = candidate
        elif index < len(frame.old_children):
            candidate = frame.old_children[index]
            if (
                candidate.key is None
                and candidate.function is function
                and candidate not in frame.reused
            ):
                scope = candidate

        if scope is None:
            scope = ComponentScope(
                function,
                parent,
                key=component_key if keyed else None,
            )
        else:
            frame.reused.add(scope)
        frame.next_children.append(scope)

        inputs_changed = not self._component_inputs_equal(
            scope.args, scope.kwargs, args, kwargs,
        )
        if inputs_changed:
            scope.args = tuple(args)
            scope.kwargs = dict(kwargs)
            scope.dirty = True

        if scope.output is None or scope.dirty or scope.descendant_dirty:
            self._execute_component(scope)
        return scope.output

    # ---- event dispatch -----------------------------------------------------

    def dispatch_event(self, message: JsonObject) -> None:
        """Dispatch a single event from the native side.

        Invalid messages are discarded without clearing a known-good tree.
        """
        self.dispatch_events([message])

    def dispatch_events(self, messages: list[JsonObject]) -> None:
        """Dispatch a batch of native events and render once afterward.

        This is the preferred native path: Android accumulates events between
        commits and sends them together.  All handlers run inside one batching
        window, then a single render produces one commit (SCHED-04).

        COORD-05: the state journal is active during the entire batch so
        that any handler or render failure rolls back all State mutations.
        """
        if not isinstance(messages, list) or not messages:
            return
        try:
            for message in messages:
                if not isinstance(message, dict):
                    raise TypeError("Event batch entries must be objects")
                validate_message(message)
                if message.get("type") != MSG_EVENT:
                    raise ValueError("Only event messages can be dispatched to Python")
        except (TypeError, ValueError):
            return
        self._dispatch_native_events([
            Event.from_message(message) for message in messages
        ])

    def dispatch_native_events(self, events: list[Event]) -> None:
        """Dispatch trusted events already decoded by the direct JNI adapter."""
        if not isinstance(events, list) or not events:
            return
        if not all(isinstance(event, Event) for event in events):
            raise TypeError("Native event batch entries must be Event objects")
        self._dispatch_native_events(events)

    def subscribe_external_callback(
        self,
        callback: Callable[[Any], Any],
    ) -> ExternalCallbackSubscription:
        """Register one application callback under Runtime lifecycle ownership."""
        if not callable(callback):
            raise TypeError("External callback must be callable")
        if self._recovery_state == RecoveryState.DISPOSED:
            raise RuntimeError("Runtime is disposed")
        subscription = ExternalCallbackSubscription(
            id=self._next_external_callback_id,
            callback=callback,
            _runtime=ref(self),
        )
        self._next_external_callback_id += 1
        self._external_callbacks[subscription.id] = subscription
        return subscription

    def dispatch_external_callbacks(
        self,
        callbacks: list[tuple[ExternalCallbackSubscription, Any]],
        disposed: list[ExternalCallbackSubscription] | None = None,
    ) -> None:
        """Dispose subscriptions and run one external callback batch.

        Android has already serialized and mechanically throttled these calls.
        This method owns all Vyne semantics: subscription validation, runtime
        context, state journalling, failure recovery, and one batched render.
        """
        if not isinstance(callbacks, list):
            raise TypeError("External callbacks must be a list")
        if disposed is not None and not isinstance(disposed, list):
            raise TypeError("Disposed external callbacks must be a list")

        for subscription in disposed or ():
            self._dispose_external_callback(subscription)

        if self._recovery_state == RecoveryState.DISPOSED or not callbacks:
            return

        active_callbacks: list[tuple[ExternalCallbackSubscription, Any]] = []
        for entry in callbacks:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise TypeError(
                    "External callback entries must be (subscription, payload) tuples"
                )
            subscription, payload = entry
            if not isinstance(subscription, ExternalCallbackSubscription):
                raise TypeError(
                    "External callback entries require Runtime subscriptions"
                )
            if self._owns_external_callback(subscription):
                active_callbacks.append((subscription, payload))
        if not active_callbacks:
            return

        was_batching = self._batching_events
        previous_origin = self._batched_origin_event
        failure: Exception | None = None
        awaitables: list[tuple[Any, None]] = []

        self._capture_component_checkpoint()
        self._state_journal.begin()
        try:
            self._batching_events = True
            for subscription, payload in active_callbacks:
                result = self._dispatch_external_callback_now(subscription, payload)
                if inspect.isawaitable(result):
                    awaitables.append((result, None))
        except Exception as exc:
            failure = exc
        finally:
            self._batching_events = was_batching

        if failure is not None:
            self._close_awaitables(awaitables)
            self._batched_origin_event = previous_origin
            self._state_journal.rollback()
            self._send_error_commit(str(failure))
            return

        try:
            if not was_batching:
                self._flush_batched_render(None)
                if not self._coordinator.in_flight:
                    self._commit_framework()
        except Exception as exc:
            self._close_awaitables(awaitables)
            awaitables.clear()
            logging.getLogger("vyne").error(
                "render after event batch failed: %s",
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            self._state_journal.rollback()
            self._send_error_commit(str(exc))
        finally:
            self._batched_origin_event = previous_origin
        for awaitable, origin in awaitables:
            self._async_callbacks.schedule(awaitable, origin)

    def _owns_external_callback(
        self,
        subscription: ExternalCallbackSubscription,
    ) -> bool:
        return (
            subscription.active
            and subscription._runtime() is self
            and self._external_callbacks.get(subscription.id) is subscription
        )

    def _dispose_external_callback(
        self,
        subscription: ExternalCallbackSubscription,
    ) -> None:
        if not isinstance(subscription, ExternalCallbackSubscription):
            return
        if subscription._runtime() is not self:
            return
        if self._external_callbacks.get(subscription.id) is subscription:
            del self._external_callbacks[subscription.id]
        subscription.deactivate()

    def _dispatch_external_callback_now(
        self,
        subscription: ExternalCallbackSubscription,
        payload: Any,
    ) -> Any:
        if not self._owns_external_callback(subscription):
            return
        callback = subscription.callback
        if callback is None:
            return
        previous_event = self._current_event
        previous_phase = self._phase
        self._current_event = None
        self._phase = "event"
        try:
            with runtime_context(self):
                return callback(payload)
        finally:
            self._current_event = previous_event
            self._phase = previous_phase

    def _dispatch_native_events(self, events: list[Event]) -> None:
        """Run one ordered event batch after boundary decoding/validation."""

        # Apply receipts close the preceding framework transaction. Android
        # places them before any lifecycle/user events unlocked by that
        # commit. Consume that leading receipt prefix before opening the next
        # event transaction, otherwise an acknowledgement would commit the
        # journal underneath a completion callback in the same native batch.
        receipt_count = 0
        for event in events:
            if (
                event.name == "__vyne_system__"
                and event.payload.get("type") == "native_apply_result"
            ):
                self._dispatch_native_event(event)
                receipt_count += 1
                continue
            break
        events = events[receipt_count:]
        if not events:
            return

        was_batching = self._batching_events
        previous_origin = self._batched_origin_event
        failure: Exception | None = None
        awaitables: list[tuple[Any, Event]] = []

        # Begin one framework/state transaction for this event batch.
        self._capture_component_checkpoint()
        self._state_journal.begin()

        try:
            self._batching_events = True
            for event in events:
                result = self._dispatch_native_event(event)
                if inspect.isawaitable(result):
                    awaitables.append((result, event))
        except Exception as exc:
            failure = exc
            # Observability: a failing handler must never be silent. The
            # traceback goes to the Python log (python.stderr on Android);
            # the error commit below preserves the accepted UI (RE-1).
            logging.getLogger("vyne").error(
                "event handler failed: %s",
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
        finally:
            self._batching_events = was_batching

        if failure is not None:
            self._close_awaitables(awaitables)
            self._batched_origin_event = previous_origin
            # Rollback state mutations (COORD-05).
            self._state_journal.rollback()
            self._send_error_commit(str(failure))
            return

        try:
            if not was_batching:
                self._flush_batched_render(self._batched_origin_event)
                # Keep the journal attached to an in-flight candidate.  Exact
                # OK commits it; failure rolls it back.
                if not self._coordinator.in_flight:
                    self._commit_framework()
        except Exception as exc:
            self._close_awaitables(awaitables)
            awaitables.clear()
            logging.getLogger("vyne").error(
                "render after event batch failed: %s",
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            self._state_journal.rollback()
            self._send_error_commit(str(exc))
        finally:
            self._batched_origin_event = previous_origin
        for awaitable, origin in awaitables:
            self._async_callbacks.schedule(awaitable, origin)

    # ---- internal: render scheduling ----------------------------------------

    def _set_state_from_async_callback(
        self,
        state_cell: State[Any],
        value: Any,
    ) -> bool:
        """Record a state write made by an active async callback task."""
        if not self._async_callbacks.active:
            return False

        if self._coordinator.in_flight:
            self._deferred_async_origin = self._current_event
            state_id = id(state_cell)
            mutation = self._deferred_async_state.get(state_id)
            if mutation is None:
                mutation = _DeferredStateMutation(
                    state_cell=state_cell,
                    baseline=state_cell._value,
                    value=value,
                )
                self._deferred_async_state[state_id] = mutation
            else:
                mutation.value = value
            state_cell._value = value
        else:
            self._capture_component_checkpoint()
            if not self._state_journal.active:
                self._state_journal.begin()
            self._state_journal.record(state_cell, value)

        state_cell._request_render()
        return True

    async def _settle_async_callbacks(self) -> None:
        """Advance newly returned awaitables to a suspension boundary."""
        await self._async_callbacks.settle()

    def wait_for_async_callbacks(self, timeout: float | None = None) -> bool:
        """Wait for currently scheduled callbacks; primarily useful in tests."""
        return self._async_callbacks.wait(timeout)

    def _handle_async_callback_failure(self, error: Exception) -> None:
        if self._coordinator.in_flight:
            for mutation in self._deferred_async_state.values():
                mutation.state_cell._value = mutation.baseline
            self._deferred_async_state.clear()
            self._deferred_async_origin = None
            self._last_error = str(error)
            return
        self._state_journal.rollback()
        self._send_error_commit(str(error))

    def _adopt_deferred_async_state(
        self,
        *,
        rejected: bool,
    ) -> Event | None:
        if not self._deferred_async_state:
            return None
        mutations = tuple(self._deferred_async_state.values())
        self._deferred_async_state.clear()
        origin = self._deferred_async_origin
        self._deferred_async_origin = None
        self._capture_component_checkpoint()
        self._state_journal.begin()
        for mutation in mutations:
            baseline = (
                mutation.state_cell._value
                if rejected
                else mutation.baseline
            )
            self._state_journal.record_from(
                mutation.state_cell,
                baseline,
                mutation.value,
            )
        return origin

    def _schedule_render(self) -> None:
        """Schedule a render pass.

        COORD-05: if a commit is in-flight, the render is deferred.
        The ack handler will schedule it when the in-flight commit is
        acknowledged.
        """
        self._needs_render = True
        if self._async_callbacks.active:
            self._async_callbacks.request_flush(self._current_event)
            return
        if self._batching_events or self._rendering:
            return
        if self._coordinator.in_flight:
            # Defer: the ack handler will pick this up.
            return
        self._render_loop()

    def _drain_pending_root_arguments(self) -> None:
        """Render queued root inputs one at a time in their arrival order."""
        if self._draining_root_arguments:
            return
        self._draining_root_arguments = True
        try:
            while self._pending_root_arguments:
                if (
                    not self._mounted
                    or self._recovery_state
                    in (RecoveryState.DISPOSED, RecoveryState.FAULTED)
                    or self._batching_events
                    or self._rendering
                    or self._coordinator.in_flight
                    or self._needs_render
                ):
                    return

                next_args = self._pending_root_arguments.popleft()
                self._capture_component_checkpoint()
                self._root_scope.args = next_args
                self._root_scope.dirty = True
                self._schedule_render()
        finally:
            self._draining_root_arguments = False

    def _invalidate_component(self, scope: ComponentScope) -> None:
        if not self._mounted or not scope.mounted:
            return
        self._capture_component_checkpoint()
        scope.dirty = True
        if scope is not self._root_scope:
            parent = scope.parent
            while parent is not None:
                parent.descendant_dirty = True
                parent = parent.parent
        self._schedule_render()

    # ---- internal: component execution --------------------------------------

    def _capture_component_checkpoint(self) -> None:
        if self._effect_checkpoint is None:
            self._effect_checkpoint = tuple(self._effect_pending)
        if self._animation_checkpoint is None:
            self._animation_checkpoint = _AnimationCheckpoint(
                animation_ids=frozenset(self._animations),
                pending=tuple(self._anim_pending),
                driver_targets=tuple(
                    (driver_id, driver.target)
                    for driver_id, driver in self._animated_drivers.items()
                ),
            )
        self._transaction.capture_components(self._root_scope)

    def _commit_framework(self) -> None:
        self._transaction.commit_framework()
        self._prune_unmounted_animated_drivers()
        self._animation_checkpoint = None
        self._effect_checkpoint = None

    def _prune_unmounted_animated_drivers(self) -> None:
        from vyne.animations import _AnimatedDriver

        active_driver_ids: set[int] = set()
        stack = [self._root_scope]
        while stack:
            scope = stack.pop()
            if not scope.mounted:
                continue
            stack.extend(scope.children)
            active_driver_ids.update(
                hook.driver_id
                for hook in scope.hooks
                if isinstance(hook, _AnimatedDriver)
            )
        for driver_id in set(self._animated_drivers) - active_driver_ids:
            self._animated_drivers.pop(driver_id, None)

    def _rollback_framework(self) -> None:
        self._transaction.rollback_framework()
        effect_baseline = self._effect_checkpoint
        self._effect_checkpoint = None
        if effect_baseline is not None:
            self._effect_pending = list(effect_baseline)
        baseline = self._animation_checkpoint
        self._animation_checkpoint = None
        if baseline is None:
            return
        self._anim_pending = list(baseline.pending)
        baseline_driver_ids = {
            driver_id for driver_id, _ in baseline.driver_targets
        }
        for driver_id in set(self._animated_drivers) - baseline_driver_ids:
            self._animated_drivers.pop(driver_id, None)
        for driver_id, target in baseline.driver_targets:
            driver = self._animated_drivers.get(driver_id)
            if driver is not None:
                driver._target = target
        rejected = set(self._animations) - set(baseline.animation_ids)
        for animation_id in rejected:
            registration = self._animations.pop(animation_id, None)
            if registration is not None:
                registration.handle._finish("rejected", "framework_rollback")
        for revision, animation_ids in tuple(self._animation_ids_by_revision.items()):
            remaining = animation_ids - rejected
            if remaining:
                self._animation_ids_by_revision[revision] = frozenset(remaining)
            else:
                self._animation_ids_by_revision.pop(revision, None)

    def _mark_revision_animations_running(self, revision: int) -> None:
        for animation_id in self._animation_ids_by_revision.pop(
            revision, frozenset()
        ):
            registration = self._animations.get(animation_id)
            if registration is not None:
                registration.handle._mark_running()

    def _reject_revision_animations(
        self,
        revision: int,
        *,
        reason: str,
    ) -> None:
        """Close handles whose native presentation state cannot be known."""
        for animation_id in self._animation_ids_by_revision.pop(
            revision, frozenset()
        ):
            registration = self._animations.pop(animation_id, None)
            if registration is not None:
                registration.handle._finish("rejected", reason)

    def _execute_component(self, scope: ComponentScope) -> Element:
        previous_scope = self._current_component_scope
        scope.hook_index = 0
        scope.child_index = 0
        self._current_component_scope = scope
        frame = _ComponentChildFrame(tuple(scope.children))
        self._component_child_frames[scope] = frame
        try:
            output = normalize_child(scope.function(*scope.args, **scope.kwargs))
        finally:
            self._component_child_frames.pop(scope, None)
            self._current_component_scope = previous_scope

        if (
            scope.expected_hook_count is not None
            and scope.hook_index != scope.expected_hook_count
        ):
            raise RuntimeError("state() calls must not be conditional or reordered")
        if scope.expected_hook_count is None:
            scope.expected_hook_count = scope.hook_index

        if scope.key is not None:
            output_key = output.props.get("key")
            if output_key is None:
                output = Element(
                    output.kind,
                    output.props.with_item("key", scope.key),
                    output.children,
                )
            elif output_key != scope.key:
                raise ValueError(
                    f"Keyed component {scope.function.__name__} returned root "
                    f"key {output_key!r}, expected {scope.key!r}"
                )

        for child in frame.old_children:
            if child not in frame.reused:
                self._unmount_component(child)
        scope.children = frame.next_children
        scope.output = output
        scope.dirty = False
        scope.descendant_dirty = False
        return output

    def _unmount_component(self, scope: ComponentScope) -> None:
        scope.mounted = False
        scope.root_node_id = None
        for child in scope.children:
            self._unmount_component(child)

    def _mark_component_tree_dirty(self, scope: ComponentScope) -> None:
        scope.dirty = True
        for child in scope.children:
            self._mark_component_tree_dirty(child)


    @staticmethod
    def _component_inputs_equal(
        previous_args: tuple[Any, ...],
        previous_kwargs: dict[str, Any],
        next_args: tuple[Any, ...],
        next_kwargs: dict[str, Any],
    ) -> bool:
        """Structural input equality for component caching.

        Containers compare recursively. Callables compare by code object
        identity plus closure-cell identity: a freshly re-created inline
        lambda with the same code and the same captured objects is the
        same logical input. Cells compare by identity only, so in-place
        mutation of a captured object still counts as "changed"
        conservatively when a NEW object is captured — never stale.
        """
        try:
            return (
                _inputs_equal(previous_args, next_args)
                and _inputs_equal(previous_kwargs, next_kwargs)
            )
        except Exception:
            # Equality probes must never crash caching decisions.
            return False

    # ---- internal: event dispatch -------------------------------------------

    def _dispatch_native_event(self, event: Event) -> Any:
        """Process one decoded event: find its accepted handler and invoke it."""
        # Intercept __vyne_system__ events for native-apply feedback (CORE-02).
        if event.name == "__vyne_system__":
            return self._handle_system_event(event)

        handler_id = self._handler_for_event(event.target, event.name)
        if handler_id is None or event.handler != handler_id:
            # Listener identity is part of the accepted snapshot.  Never bind a
            # delayed event to a replacement callback.
            return

        # Schema-driven acknowledgement extraction (COORD-05 / SCHED-02).
        extract_acknowledgements(event.name, event.target, event.payload, self._ack_map)

        if self._batching_events:
            self._batched_origin_event = event
            return self._dispatch_event_now(event)

        was_batching = self._batching_events
        previous_origin = self._batched_origin_event
        self._batching_events = True
        self._batched_origin_event = event
        try:
            result = self._dispatch_event_now(event)
        finally:
            self._batching_events = was_batching

        if not was_batching:
            self._flush_batched_render(self._batched_origin_event)
            self._batched_origin_event = previous_origin
        return result

    def _handle_system_event(self, event: Event) -> Any:
        """Route __vyne_system__ events to their internal handlers (CORE-02)."""
        payload = event.payload if isinstance(event.payload, dict) else {}
        sys_type = payload.get("type", "")
        if sys_type == "native_apply_result":
            self.handle_native_apply_result(
                payload.get("result"),
                payload.get("revision"),
                payload.get("session"),
            )
            return None
        if sys_type == "animation_lifecycle":
            return self._dispatch_animation_lifecycle(payload)
        if sys_type == "app_state":
            return self.handle_app_state(payload.get("state"))
        return None

    def subscribe_app_state(
        self,
        handler: Callable[[str], Any],
    ) -> Callable[[], None]:
        """Register an app-state handler; fires immediately with the current
        state, then on every transition. The returned callable disposes."""
        if not callable(handler):
            raise TypeError("app-state handler must be callable")
        if handler not in self._app_state_handlers:
            self._app_state_handlers.append(handler)
        result = handler(self.current_app_state)
        if inspect.isawaitable(result):
            self._async_callbacks.schedule(result, None)

        def dispose() -> None:
            if handler in self._app_state_handlers:
                self._app_state_handlers.remove(handler)

        return dispose

    def handle_app_state(self, state: Any) -> Any:
        """Apply one ordered host lifecycle transition."""
        if state not in {"active", "inactive", "background"}:
            return None
        if state == self.current_app_state:
            return None
        self.current_app_state = state
        awaitables = []
        for handler in list(self._app_state_handlers):
            try:
                result = handler(state)
            except Exception as exc:  # noqa: BLE001 - one handler must not break the batch
                logging.getLogger("vyne").error(
                    "app-state handler failed: %s",
                    exc,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
                continue
            if inspect.isawaitable(result):
                awaitables.append(result)
        if len(awaitables) == 1:
            return awaitables[0]
        if len(awaitables) > 1:
            return asyncio.gather(*awaitables)
        return None

    def add_back_handler(self, handler: Callable[[], Any]) -> Callable[[], None]:
        """Register a back-press handler; returns a dispose callable.

        Re-registering the same callable is a no-op (re-renders must not
        stack duplicate handlers).
        """
        if not callable(handler):
            raise TypeError("back handler must be callable")
        if handler not in self._back_handlers:
            self._back_handlers.append(handler)

        def dispose() -> None:
            if handler in self._back_handlers:
                self._back_handlers.remove(handler)

        return dispose

    def handle_back_press(self) -> bool:
        """Run back handlers LIFO; True consumes the press (no default).

        A raising handler is logged and treated as ``False`` so one bad
        handler can neither block the press nor freeze the host.
        """
        for handler in reversed(self._back_handlers):
            try:
                if handler():
                    return True
            except Exception as exc:  # noqa: BLE001 - one handler must not break the batch
                logging.getLogger("vyne").error(
                    "back handler failed: %s",
                    exc,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
        return False

    def _dispatch_animation_lifecycle(self, payload: JsonObject) -> Any:
        animation_id = payload.get("animation_id")
        status = payload.get("status")
        if (
            type(animation_id) is not int
            or animation_id <= 0
            or status not in {"completed", "cancelled"}
        ):
            return None
        registration = self._animations.get(animation_id)
        if registration is None or registration.handle.done:
            return None
        handle = registration.handle
        if (
            payload.get("node_id") != handle.slot.node_id
            or payload.get("property") != handle.slot.property
        ):
            return None
        reason_value = payload.get("reason")
        reason = reason_value if isinstance(reason_value, str) else None
        self._animations.pop(animation_id, None)
        handle._finish(status, reason)
        callback = (
            registration.on_complete
            if status == "completed"
            else registration.on_cancel
        )
        if callback is None:
            return None

        lifecycle = AnimationEvent(
            animation_id=animation_id,
            status=status,
            node_id=handle.slot.node_id,
            property=handle.slot.property,
            reason=reason,
        )
        previous_event = self._current_event
        previous_phase = self._phase
        self._current_event = None
        self._phase = "event"
        try:
            with runtime_context(self):
                return callback(lifecycle)
        finally:
            self._current_event = previous_event
            self._phase = previous_phase

    def handle_native_apply_result(
        self,
        result: Any,
        native_revision: Any,
        session: Any,
    ) -> None:
        """Handle a typed apply receipt from the direct Android bridge."""
        if session != self.session_id:
            return
        if type(native_revision) is not int or native_revision < 0:
            return
        if result == "ok":
            self.acknowledge_native_apply(native_revision)
        elif result in {"rejected_known", "verified_rollback", "partial"}:
            self.report_native_failure(
                f"Native apply failed: {result} (revision {native_revision})",
                revision=native_revision,
                unknown=False,
            )
        elif result == "unknown":
            self.report_native_failure(
                f"Native apply state unknown (revision {native_revision})",
                revision=native_revision,
                unknown=True,
            )

    def _dispatch_event_now(self, event: Event) -> Any:
        previous_event = self._current_event
        previous_phase = self._phase
        self._current_event = event
        self._phase = "event"
        try:
            with runtime_context(self):
                return self.events.dispatch(event)
        finally:
            self._current_event = previous_event
            self._phase = previous_phase

    def _flush_batched_render(self, origin: Event | None) -> None:
        """Flush a batched render: run passes until done, then emit commit.

        COORD-05: If a commit is already in-flight, skips the render — the
        pending state change will be picked up by the ack handler when the
        current in-flight commit resolves.
        """
        self._pass_guard.begin_flush()

        # COORD-05: gate on in-flight commit.
        if self._coordinator.in_flight:
            # Defer the render; the ack handler will schedule it.
            return

        if self._needs_render:
            previous_event = self._current_event
            self._current_event = origin
            try:
                self._render_loop()
            finally:
                self._current_event = previous_event

        # Effect-only path (SCHED-01): commands do not need a synthetic
        # component render when no tree changes are pending.
        if (self._anim_pending or self._effect_pending) and not self._needs_render:
            self._send_effect_only_commit(origin)

        # Clear acknowledgements after commit is sent.
        self._ack_map.clear()

    # ---- internal: render loop ----------------------------------------------

    def _render_loop(self) -> None:
        """Run render passes until no more are requested.

        Uses PassGuard to prevent infinite loops (SCHED-03).  The guard is
        reset at the top of every top-level render loop so direct
        ``request_render()`` flushes get their own pass budget (SCHED-03).
        """
        self._pass_guard.begin_flush()
        self._rendering = True
        try:
            while True:
                self._pass_guard.enter_pass()
                self._needs_render = False
                try:
                    self._render_once()
                except RenderPhaseMutationError:
                    # State.set during render — convert to error commit.
                    self._needs_render = False
                    self._send_error_commit(
                        "State.set() called during render pass. "
                        "Move state mutations to event handlers."
                    )
                    break
                if not self._needs_render:
                    break
        except RuntimeError as exc:
            # Pass guard tripped — controlled recovery.
            if self._coordinator.accepted_root is not None:
                self._send_error_commit(str(exc))
        finally:
            self._rendering = False

    def _render_once(self) -> None:
        """Render and plan with the sole production reconciliation model."""
        self._render_imperative_bindings = (
            self._coordinator.desired_imperative_bindings
        )
        self._render_staged_binding_targets = set()
        try:
            with runtime_context(self):
                self._phase = "render"
                try:
                    root_element = self._execute_component(self._root_scope)
                finally:
                    self._phase = None
            used_lowering_keys: set[int] = set()
            canonical_root = lower_element(
                root_element,
                _identity_cache=self._lower_identity_cache,
                _used_identity_keys=used_lowering_keys,
            )
            self._lower_identity_cache = {
                key: self._lower_identity_cache[key]
                for key in used_lowering_keys
            }

            accepted = RenderSnapshot(
                root=self._coordinator.accepted_root,
                node_index=self._coordinator.accepted_index,
                revision=self._coordinator.accepted_revision,
            )
            first_id = self._coordinator.next_node_id
            plan = plan_reconcile(accepted, canonical_root, next_node_id=first_id)
            candidate_registry = self.events.clone()
            listener_ops, candidate_refs = self._bind_candidate_runtime_intents(
                canonical_root,
                plan.new_snapshot.root,
                candidate_registry,
                candidate_node_ids=set(plan.new_snapshot.node_index),
            )
            active_handlers = {
                handler
                for node in plan.new_snapshot.node_index.values()
                for handler in node.listeners.values()
            }
            for handler_id in candidate_registry.handler_ids - active_handlers:
                candidate_registry.unregister(handler_id)

            ops = [operation.to_wire_op() for operation in plan.ops]
            ops = [
                op for op in ops
                if not (
                    op.get("op") == OP_SET_PROP
                    and self._ack_map.should_suppress(
                        int(op["id"]), str(op["name"]), op.get("value")
                    )
                )
            ]
            ops.extend(listener_ops)
            next_node_id = max(
                [first_id - 1, *plan.new_snapshot.node_index.keys()]
            ) + 1
            candidate_ref_identities = {
                id(candidate_ref) for candidate_ref in candidate_refs.values()
            }
            candidate_bindings = {
                target: intent
                for target, intent in self._render_imperative_bindings.items()
                if id(intent.anchor_ref) in candidate_ref_identities
            }
            self._coordinator.stage_candidate(
                plan.new_snapshot.root,
                plan.new_snapshot.node_index,
                next_node_id,
                ref_map=candidate_refs,
                event_registry=candidate_registry,
                imperative_bindings=candidate_bindings,
            )
            self._send_render_commit(ops)
        except RenderPhaseMutationError:
            raise
        except Exception as exc:
            self._send_error_commit(str(exc))
        finally:
            self._render_imperative_bindings = None
            self._render_staged_binding_targets = None

    def _bind_candidate_runtime_intents(
        self,
        desired: CanonicalElement,
        node: RenderNode | None,
        registry: EventRegistry,
        *,
        candidate_node_ids: set[int],
    ) -> tuple[list[JsonObject], dict[int, Ref]]:
        if node is None:
            raise RuntimeError("Planner produced no candidate root")
        ops: list[JsonObject] = []
        refs: dict[int, Ref] = {
            node_id: ref
            for node_id, ref in self._coordinator.ref_map.items()
            if node_id in candidate_node_ids
        }
        accepted_ref_values = set(map(id, self._coordinator.ref_map.values()))

        def visit(wanted: CanonicalElement, mounted: RenderNode) -> None:
            if mounted.intent_element is wanted:
                return
            next_listeners: dict[str, int] = {}
            next_callbacks: dict[str, Any] = {}
            next_latest: set[str] = set()
            wanted_ref: Ref | None = None

            for prop_name, prop_value in wanted.props.items():
                if prop_name == "ref":
                    if prop_value is not None and not isinstance(prop_value, Ref):
                        raise TypeError("ref prop must be a Ref")
                    wanted_ref = prop_value
                    continue
                event_name = event_name_for_prop(prop_name)
                if event_name is None or prop_value is None:
                    continue
                callback, delivery = event_delivery(prop_value)
                previous_id = mounted.listeners.get(event_name)
                previous_delivery = (
                    "latest" if event_name in mounted.latest_events else "all"
                )
                if previous_id is not None:
                    # A continuously installed listener retains identity while
                    # its closure is refreshed in the detached registry.
                    handler_id = previous_id
                    registry.update(handler_id, callback)
                    if previous_delivery != delivery:
                        ops.append({
                            "op": OP_LISTEN_LATEST if delivery == "latest" else OP_LISTEN,
                            "id": mounted.id,
                            "event": event_name,
                            "handler": handler_id,
                        })
                else:
                    handler_id = registry.register(callback)
                    ops.append({
                        "op": OP_LISTEN_LATEST if delivery == "latest" else OP_LISTEN,
                        "id": mounted.id,
                        "event": event_name,
                        "handler": handler_id,
                    })
                next_listeners[event_name] = handler_id
                next_callbacks[event_name] = callback
                if delivery == "latest":
                    next_latest.add(event_name)

            for event_name, handler_id in mounted.listeners.items():
                if event_name not in next_listeners:
                    registry.unregister(handler_id)
                    ops.append({"op": OP_UNLISTEN, "id": mounted.id, "event": event_name})

            refs.pop(mounted.id, None)
            mounted.listeners = next_listeners
            mounted.listener_callbacks = next_callbacks
            mounted.latest_events = next_latest
            mounted.ref = wanted_ref
            mounted.intent_element = wanted
            if wanted_ref is not None:
                identity = id(wanted_ref)
                if wanted_ref.current is not None and identity not in accepted_ref_values:
                    raise RuntimeError("Ref is already attached to another Runtime")
                refs[mounted.id] = wanted_ref

            if len(wanted.children) != len(mounted.children):
                raise RuntimeError("Planner candidate shape mismatch")
            for wanted_child, mounted_child in zip(wanted.children, mounted.children):
                visit(wanted_child, mounted_child)

        visit(desired, node)
        ref_owners: dict[int, int] = {}
        for node_id, candidate_ref in refs.items():
            identity = id(candidate_ref)
            if identity in ref_owners:
                raise RuntimeError(
                    "A Ref cannot be used by multiple mounted occurrences"
                )
            ref_owners[identity] = node_id
        return ops, refs

    # Runtime reconciliation is implemented exclusively by plan_reconcile.

    def start_animation(
        self,
        cmd: SetTarget | DriverSetTarget,
        *,
        on_complete: Callable[..., Any] | None = None,
        on_cancel: Callable[..., Any] | None = None,
    ) -> AnimationHandle:
        """Register lifecycle callbacks and queue one native timeline."""
        if not isinstance(cmd, (SetTarget, DriverSetTarget)):
            raise TypeError(
                "start_animation requires a SetTarget or DriverSetTarget command"
            )
        if cmd.animation_id != 0:
            raise ValueError("Animation IDs are allocated by Runtime")
        animation_id = self._next_animation_id
        self._next_animation_id += 1
        assigned = replace(cmd, animation_id=animation_id)
        slot = assigned.slot if isinstance(assigned, SetTarget) else assigned.anchor
        handle = AnimationHandle(animation_id, slot, ref(self))
        self._animations[animation_id] = _AnimationRegistration(
            handle=handle,
            command=assigned,
            on_complete=(
                _wrap_handler(on_complete) if on_complete is not None else None
            ),
            on_cancel=(
                _wrap_handler(on_cancel) if on_cancel is not None else None
            ),
        )
        try:
            self.queue_animation_command(assigned)
        except Exception:
            self._animations.pop(animation_id, None)
            handle._finish("rejected", "queue_failed")
            raise
        return handle

    def cancel_animation(self, handle: AnimationHandle) -> bool:
        """Queue cancellation only if *handle* is still the active generation."""
        if not isinstance(handle, AnimationHandle):
            raise TypeError("cancel_animation requires an AnimationHandle")
        registration = self._animations.get(handle.id)
        if registration is None or registration.handle is not handle or handle.done:
            return False
        if isinstance(registration.command, DriverSetTarget):
            command: MotionCommand = DriverCancel(
                driver_id=registration.command.driver_id,
                anchor=registration.command.anchor,
                animation_id=handle.id,
            )
        else:
            command = Cancel(slot=handle.slot, animation_id=handle.id)
        self.queue_animation_command(command)
        return True

    def queue_animation_command(self, cmd: MotionCommand) -> None:
        """Enqueue a unified MotionCommand for the next commit.

        This is the preferred API.  Commands are queued and merged into the
        next commit so they travel alongside any tree changes from the same
        event handler.
        """
        if self._phase not in {"render", "event"}:
            raise RuntimeError(
                "Animation commands can only be used while rendering "
                "or in event handlers"
            )
        if isinstance(cmd, (SetTarget, DriverSetTarget)):
            slot = cmd.slot if isinstance(cmd, SetTarget) else cmd.anchor
            node_index = self._coordinator.accepted_index or {}
            node = node_index.get(slot.node_id)
            if node is None:
                raise ValueError(
                    f"Cannot animate unknown view id {slot.node_id}"
                )
            if isinstance(cmd, DriverSetTarget):
                expected = self.animated_driver_anchor(cmd.driver_id)
                if expected != cmd.anchor:
                    raise ValueError(
                        f"Animated.Value driver {cmd.driver_id} binding changed before start"
                    )
            elif slot.slot_id is None:
                from vyne.animations import ANIMATABLE_VIEW_PROPERTIES
                from vyne.animations import animated_driver_ids
                from vyne.extensions_registry import props_by_kind

                bound_drivers = animated_driver_ids(node.props.get(slot.property))
                if bound_drivers:
                    raise ValueError(
                        f"Property {slot.property!r} is bound to Animated.Value; "
                        "animate the value instead"
                    )
                if (
                    slot.property not in ANIMATABLE_VIEW_PROPERTIES
                    or slot.property not in props_by_kind(node.kind)
                ):
                    raise ValueError(
                        f"Property {slot.property!r} is not animatable "
                        f"for {node.kind}"
                    )
            elif node.kind != "Canvas":
                raise ValueError(
                    "Canvas presentation slots require a Canvas node"
                )
        self._anim_pending.append(cmd)

    def _stage_imperative_binding(
        self,
        target: Any,
        value: Any,
        *,
        anchor_ref: Ref,
    ) -> None:
        """Stage controller state for promotion with the render candidate."""
        bindings = self._render_imperative_bindings
        staged_targets = self._render_staged_binding_targets
        if self._phase != "render" or bindings is None or staged_targets is None:
            raise RuntimeError(
                "Imperative controller bindings can only be staged while rendering"
            )
        if not isinstance(anchor_ref, Ref):
            raise TypeError("Imperative controller binding anchor must be a Ref")
        accept = getattr(target, "_accept_runtime_binding", None)
        if not callable(accept):
            raise TypeError(
                "Imperative controller target must accept Runtime bindings"
            )
        if target in staged_targets:
            raise RuntimeError(
                "An imperative controller cannot bind to multiple occurrences"
            )
        staged_targets.add(target)
        bindings[target] = _ImperativeBindingIntent(target, value, anchor_ref)

    def _queue_native_effect(self, effect: NativeViewEffect) -> None:
        """Queue one accepted view effect for the shared commit pipeline."""
        if not isinstance(effect, NativeViewEffect):
            raise TypeError("effect must implement NativeViewEffect")
        if self._phase != "event":
            raise RuntimeError(
                "Native effects can only be queued from event handlers or "
                "their async callbacks"
            )
        if self._recovery_state in {RecoveryState.DISPOSED, RecoveryState.FAULTED}:
            raise RuntimeError("Cannot queue a native effect on an inactive Runtime")

        target = effect.target
        if not isinstance(target, ViewHandle) or not target.valid:
            raise ValueError("Cannot target an unmounted or stale view")
        node = self._coordinator.accepted_index.get(target.node_id)
        owner_ref = self._coordinator.ref_map.get(target.node_id)
        if (
            node is None
            or owner_ref is None
            or owner_ref.current is not target
            or node.kind != target.kind
            or node.kind != effect.expected_kind
        ):
            raise ValueError(
                f"Native effect requires an accepted {effect.expected_kind} target"
            )

        self._capture_component_checkpoint()
        self._effect_pending.append(effect)
        if self._async_callbacks.active:
            self._async_callbacks.request_flush(self._current_event)

    def animated_driver_anchor(self, driver_id: int) -> PresentationSlot:
        """Find a mounted presentation binding for a persistent driver."""
        from collections.abc import Mapping
        from vyne.animations import animated_driver_ids
        from vyne.motion import CanvasOpIdentity

        for node_id in sorted(self._coordinator.accepted_index):
            node = self._coordinator.accepted_index[node_id]
            for name, value in sorted(node.props.items()):
                if name == "draw" and node.kind == "Canvas":
                    for operation in value:
                        if not isinstance(operation, Mapping):
                            continue
                        op_id = operation.get(CanvasOpIdentity.RESERVED_ID_KEY)
                        if not isinstance(op_id, str) or not op_id:
                            continue
                        for field, field_value in sorted(operation.items()):
                            if driver_id in animated_driver_ids(field_value):
                                return PresentationSlot(
                                    node_id=node_id,
                                    property=field,
                                    slot_id=op_id,
                                )
                    continue
                if driver_id in animated_driver_ids(value):
                    return PresentationSlot(node_id=node_id, property=name)
        raise RuntimeError(
            f"Animated.Value driver {driver_id} is not bound to a mounted property"
        )

    # ---- internal: effect-only commit (SCHED-01) ------------------------------

    def _send_effect_only_commit(self, origin: Event | None) -> None:
        """Emit queued native commands without a synthetic tree render.

        Origin event sequence is preserved. The commit uses the same
        provisional reservation, receipt handling, and recovery transitions
        as a tree-changing commit.
        """
        if self._coordinator.in_flight:
            return

        valid_nodes = self._coordinator.accepted_index
        command_ops = self._drain_anim_ops(
            valid_node_ids=set(valid_nodes)
        )
        command_ops.extend(self._drain_effect_ops(valid_nodes=valid_nodes))
        if not command_ops:
            return

        next_revision = self.revision + 1
        commit: JsonObject = {
            "type": MSG_COMMIT,
            "revision": next_revision,
            "ops": command_ops,
        }
        if origin is not None:
            commit["origin_event_seq"] = origin.sequence
        self._send_commit(commit, command_ops, effect_only=True)

    # ---- internal: commit emission ------------------------------------------

    def _send_render_commit(self, ops: list[JsonObject]) -> None:
        """Validate, provisionally send, and promote only after exact OK."""
        command_ops: list[JsonObject] = []
        if self._recovery_state != RecoveryState.NEEDS_RESET:
            candidate_nodes = self._coordinator.candidate_index
            command_ops.extend(
                self._drain_anim_ops(valid_node_ids=set(candidate_nodes))
            )
            command_ops.extend(
                self._drain_effect_ops(valid_nodes=candidate_nodes)
            )
        if command_ops:
            ops.extend(command_ops)

        if not ops and self._recovery_state != RecoveryState.NEEDS_RESET:
            if self._coordinator.promote_local():
                self._install_promoted_framework()
                self._commit_framework()
            return

        next_revision = self.revision + 1
        if self._recovery_state == RecoveryState.NEEDS_RESET:
            if not self._coordinator.has_candidate() and self._coordinator.accepted_root is not None:
                self._coordinator.stage_candidate(
                    self._coordinator.accepted_root,
                    self._coordinator.accepted_index,
                    self._coordinator.next_node_id,
                    ref_map=self._coordinator.ref_map,
                    event_registry=self.events.clone(),
                )
            root = self._coordinator.desired_root
            if root is None:
                return
            commit = build_snapshot_commit(
                root,
                next_revision,
                origin_event_seq=(
                    self._current_event.sequence
                    if self._current_event is not None else None
                ),
            )
        else:
            commit = {"type": MSG_COMMIT, "revision": next_revision, "ops": ops}
            if self._current_event is not None and self._current_event.sequence is not None:
                commit["origin_event_seq"] = self._current_event.sequence

        self._send_commit(commit, command_ops)

    def _send_commit(
        self,
        commit: JsonObject,
        command_ops: list[dict[str, Any]],
        *,
        effect_only: bool = False,
    ) -> None:
        """Validate, provisionally send, and promote only after exact OK.

        The ONE publish pipeline shared by render and effect-only commits
        (design-pattern #5): same reservation, same acknowledgement handling,
        and same recovery transitions.
        """
        self._validate_commit(commit)
        next_revision = self.revision + 1
        previous_latest = self.latest_commit
        if effect_only:
            self._coordinator.reserve_effect_send(next_revision)
        else:
            self._coordinator.reserve_send(next_revision)
        self._record_animation_revision(next_revision, command_ops)
        try:
            self.transport.send(commit)
        except Exception:
            self._animation_ids_by_revision.pop(next_revision, None)
            self._coordinator.abort_send(next_revision)
            self.latest_commit = previous_latest
            self._rollback_framework()
            raise

        self.revision = next_revision
        self.latest_commit = commit
        self._transaction.transition_to(
            RecoveryState.AWAITING_APPLY, cause="commit sent"
        )
        held_ok = self._coordinator.finish_send(next_revision)
        if held_ok and self._promote_candidate(next_revision):
            self._transaction.transition_to(
                RecoveryState.SYNCED, cause="commit promoted"
            )
            self._mark_revision_animations_running(next_revision)
            self._commit_framework()

    # ---- internal: helpers --------------------------------------------------

    @staticmethod
    def _close_awaitables(awaitables: list[tuple[Any, Any]]) -> None:
        for awaitable, _ in awaitables:
            close = getattr(awaitable, "close", None)
            if close is not None:
                close()

    def _handler_for_event(self, target: int, event_name: str) -> int | None:
        """Find the handler ID for an event on a target node."""
        node = self._coordinator.accepted_index.get(target)
        if node is None:
            return None
        return node.listeners.get(event_name)

    def _drain_anim_ops(
        self,
        *,
        valid_node_ids: set[int] | None = None,
    ) -> list[dict[str, Any]]:
        if not self._anim_pending:
            return []
        commands = self._anim_pending
        self._anim_pending = []
        result: list[dict[str, Any]] = []
        for command in commands:
            if (
                valid_node_ids is not None
                and isinstance(command, (SetTarget, DriverSetTarget))
                and (
                    command.slot.node_id
                    if isinstance(command, SetTarget)
                    else command.anchor.node_id
                )
                not in valid_node_ids
            ):
                registration = self._animations.pop(
                    command.animation_id, None
                )
                if registration is not None:
                    registration.handle._finish(
                        "cancelled", "target_removed_before_start"
                    )
                continue
            result.append(motion_command_to_dict(command))
        return result

    def _drain_effect_ops(
        self,
        *,
        valid_nodes: dict[int, RenderNode],
    ) -> list[JsonObject]:
        if not self._effect_pending:
            return []
        effects = self._effect_pending
        self._effect_pending = []
        operations: list[JsonObject] = []
        for effect in effects:
            target = effect.target
            node = valid_nodes.get(target.node_id)
            if (
                not target.valid
                or node is None
                or node.kind != target.kind
                or node.kind != effect.expected_kind
            ):
                # The same commit removed or replaced the target. The effect
                # cannot be applied and must not make the tree commit fail.
                continue
            operations.append(effect.to_wire_op())
        return operations

    def _record_animation_revision(
        self,
        revision: int,
        operations: list[JsonObject],
    ) -> None:
        animation_ids = frozenset(
            int(operation["animation_id"])
            for operation in operations
            if (
                operation.get("op") in {
                    "motion_set_target", "motion_driver_set_target",
                }
                and type(operation.get("animation_id")) is int
                and operation["animation_id"] > 0
            )
        )
        if animation_ids:
            self._animation_ids_by_revision[revision] = animation_ids

    def _validate_commit(self, commit: JsonObject) -> None:
        """Validate a commit before changing coordinator state."""
        if getattr(self.transport, "preflights_commits", False):
            return
        try:
            validate_message(commit)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"Invalid commit: {exc}") from exc

    def _send_error_commit(self, message: str) -> None:
        """Handle a framework-level error with the correct recovery decision.

        RE-1: If an accepted UI exists, preserve it.  The error is logged
        for diagnostic purposes but the accepted tree, handlers, and refs
        are left intact.  Only state-journal mutations are rolled back.

        When no accepted UI exists (cold start or already reset), emit
        the fallback error commit so the user sees something actionable.

        RE-6: Consecutive fault counter bounds repeated failures.  After
        MAX_CONSECUTIVE_FAULTS, the runtime transitions to FAULTED and
        stops emitting error commits to avoid retry storms.

        COORD-05: when the accepted UI is preserved, the staged candidate
        for the failed render is discarded (overwritten on next successful
        render).  The coordinator's accepted state is never touched.
        """
        # RE-1: Preserve accepted UI when one exists.
        if self._coordinator.accepted_root is not None:
            self._last_error = message
            # Rollback any active state journal (dispatches that failed).
            self._rollback_framework()
            self._coordinator.discard_staged()
            # Reset fault counter — we have a healthy UI.
            self._consecutive_faults = 0
            return

        # No accepted UI: cold start, already reset, or intentional remount.
        self._rollback_framework()
        self._coordinator.discard_staged()
        # If already FAULTED, suppress further error commits.
        if self._recovery_state == RecoveryState.FAULTED:
            return

        # Terminal fault bounding (RE-6).
        self._consecutive_faults += 1
        if self._consecutive_faults > self._max_consecutive_faults:
            self._transaction.transition_to(
                RecoveryState.FAULTED, cause="terminal fault"
            )
            self._last_error = (
                f"Terminal fault after {self._consecutive_faults} "
                f"consecutive errors. Last error: {message}"
            )
            return

        self.revision += 1
        self._last_error = message

        # Invalidate all refs tracked by coordinator.
        for ref in self._coordinator.clear_all_refs():
            try:
                ref.invalidate()
            except Exception:
                pass

        self._coordinator.reset_accepted()
        self._anim_pending.clear()
        self._needs_render = False
        self._batched_origin_event = None
        self._ack_map.clear()
        self._transaction.transition_to(
            RecoveryState.NEEDS_RESET, cause="error commit emitted"
        )
        commit = error_commit(message, revision=self.revision, prefix="Error: ")
        try:
            self._validate_commit(commit)
        except TypeError:
            commit = {
                "type": MSG_COMMIT,
                "revision": self.revision,
                "ops": [
                    {"op": "clear", "id": 0},
                    {"op": OP_CREATE, "id": 1, "kind": "Text"},
                    {"op": OP_SET_PROPS, "id": 1, "props": {"text": f"Error: {message}"}},
                    {"op": OP_INSERT_CHILD, "parent": 0, "child": 1, "index": 0},
                ],
            }
        self.latest_commit = commit
        self.transport.send(commit)


def _inputs_equal(previous: Any, next_: Any) -> bool:
    """Structural equality for component input comparisons.

    Containers compare recursively; callables compare by code identity and
    closure-cell identity; everything else falls back to ``==``. See
    ``Runtime._component_inputs_equal`` for the caching contract.
    """
    if previous is next_:
        return True
    previous_type = type(previous)
    if previous_type is not type(next_):
        return False
    if previous_type in (tuple, list):
        if len(previous) != len(next_):
            return False
        for index in range(len(previous)):
            if not _inputs_equal(previous[index], next_[index]):
                return False
        return True
    if previous_type is dict:
        if previous.keys() != next_.keys():
            return False
        for key in previous:
            if not _inputs_equal(previous[key], next_[key]):
                return False
        return True
    if callable(previous):
        previous_code = getattr(previous, "__code__", None)
        if previous_code is None or previous_code is not getattr(next_, "__code__", None):
            return False
        # Bound methods share their function's code object; the receiver
        # identity is the deciding state, so it must match exactly.
        previous_self = getattr(previous, "__self__", None)
        next_self = getattr(next_, "__self__", None)
        if previous_self is not next_self:
            return False
        previous_closure = getattr(previous, "__closure__", None)
        next_closure = getattr(next_, "__closure__", None)
        if previous_closure is next_closure:
            return True
        if previous_closure is None or next_closure is None:
            return False
        if len(previous_closure) != len(next_closure):
            return False
        for previous_cell, next_cell in zip(previous_closure, next_closure):
            if previous_cell.cell_contents is not next_cell.cell_contents:
                return False
        return True
    try:
        return previous == next_
    except Exception:
        return False
