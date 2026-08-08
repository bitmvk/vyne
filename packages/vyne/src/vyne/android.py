"""Android-facing lifecycle and event entry points.

Chaquopy calls this module from a dedicated Python executor. Commits travel
through typed calls on ``DirectRenderHost`` and native events arrive as direct
Java values; there is no encoded compatibility transport.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any
from uuid import uuid4

from vyne.async_runtime import AsyncRuntimeDispatcher
from vyne.bootstrap import _start_registered_app
from vyne.events import Event
from vyne.launch import LaunchData
from vyne.state import current_runtime


@dataclass
class _DirectSession:
    """ONE aggregate slot for a live direct Android session.

    The five former module globals (_host, _runtime, _transport,
    _runtime_dispatcher, _runtime_dispatcher_owner) collapsed into this
    facade (design-pattern #1): candidate promotion swaps exactly one
    object, and shutdown/rejection restore exactly one object.

    The ``runtime`` slot is filled after the candidate Runtime is created;
    the host slot goes live first so app module code and pre_launch hooks
    can call ``android.activity()`` during the mount window.
    """

    host: Any
    runtime: Any
    transport: Any
    dispatcher: AsyncRuntimeDispatcher | None
    # Per-session launch sequence for surface data deliveries (1 = cold).
    surface_sequence: int = 1


_session: _DirectSession | None = None

# Named surface sessions (RenderSurface): each mounts an independent
# Runtime/transport pair, keyed by the extension-declared surface name.
_sessions: dict[str, _DirectSession] = {}

# Thread-local session binding: each surface's AsyncRuntimeDispatcher thread
# is bound to its session name so session-aware APIs (callback()) resolve
# to the runtime that owns the calling thread.
_bridge_thread = threading.local()


def _resolve_session() -> _DirectSession | None:
    """The session owning the current bridge thread, or the main session."""
    name = getattr(_bridge_thread, "session_name", None)
    if name is not None:
        return _sessions.get(name)
    return _session


def activity() -> Any:
    """Return the live Android Activity for application-owned integrations."""
    session = _session
    if session is None:
        raise RuntimeError("Android host is not started")
    return session.host.getActivity()


def callback(
    function: Any,
    *,
    delivery: str = "all",
    sample_interval_ms: int | None = None,
) -> Any:
    """Return a callback safe to invoke from any Android thread.

    The returned ``VyneCallback`` queues the callable onto Vyne's single-owner
    asyncio runtime. Runtime owns callback execution and rendering; Kotlin only
    applies the requested mechanical delivery policy before queueing.
    """
    if not callable(function):
        raise TypeError("callback() requires a callable")
    if delivery not in {"all", "latest"}:
        raise ValueError("callback delivery must be 'all' or 'latest'")
    if sample_interval_ms is not None and (
        not isinstance(sample_interval_ms, int)
        or isinstance(sample_interval_ms, bool)
        or sample_interval_ms <= 0
    ):
        raise ValueError("sample_interval_ms must be a positive integer")
    session = _resolve_session()
    if session is None:
        raise RuntimeError("Android host is not started")
    runtime = current_runtime() or session.runtime
    if runtime is None:
        raise RuntimeError("Python runtime is not started")
    subscription = runtime.subscribe_external_callback(function)
    try:
        native_callback = session.host.createCallback(
            subscription,
            delivery,
            0 if sample_interval_ms is None else sample_interval_ms,
        )
        subscription.attach_native(native_callback)
        return native_callback
    except BaseException:
        runtime.dispatch_external_callbacks([], [subscription])
        raise


def start_direct(
    module_name: str,
    host: Any,
    action: Any = None,
    uri: Any = None,
    extras: Any = None,
    sequence: Any = 0,
) -> None:
    """Mount an app and publish its commits through the direct host."""
    from vyne.direct_transport import DirectTransport
    from vyne.extensions_registry import sync_from_host

    global _session

    # Single source of truth: learn the extension contract from the host
    # registry before any app element is lowered. The prior tables are
    # snapshotted so a failed start or candidate rejection restores them.
    from vyne.extensions_registry import restore, snapshot

    prior_kinds = snapshot()
    prior_session = _session
    candidate_dispatcher: AsyncRuntimeDispatcher | None = None
    try:
        sync_from_host(_query_extension_kinds(host))
        launch_data = _native_launch_data(action, uri, extras, sequence)
        session_id = uuid4().hex
        candidate_transport = DirectTransport(host, session_id)
        candidate_dispatcher = AsyncRuntimeDispatcher()
        candidate = _DirectSession(
            host=host,
            runtime=None,  # filled once the candidate Runtime exists
            transport=candidate_transport,
            dispatcher=candidate_dispatcher,
        )
        # The candidate host goes live BEFORE app module code runs, so
        # android.activity() works from module scope and pre_launch hooks.
        _session = candidate
        candidate_runtime = candidate_dispatcher.call(
            lambda: _start_registered_app(
                module_name,
                transport=candidate_transport,
                launch_data=launch_data,
                session_id=session_id,
            )
        )
        candidate.runtime = candidate_runtime
        if candidate_transport.send_count == 0:
            candidate_dispatcher.call(
                lambda: _dispose_runtime_safely(candidate_runtime)
            )
            raise RuntimeError(
                f"Candidate Runtime for {module_name!r} produced no initial commit"
            )
    except BaseException:
        if candidate_dispatcher is not None:
            candidate_dispatcher.close()
        _session = prior_session
        restore(prior_kinds)
        raise

    def promote_candidate() -> None:
        nonlocal prior_session
        if (
            prior_session is not None
            and prior_session.runtime is not candidate_runtime
        ):
            prior = prior_session
            if prior.dispatcher is not None:
                prior.dispatcher.call(
                    lambda: _dispose_runtime_safely(prior.runtime)
                )
                prior.dispatcher.close()
            else:
                _dispose_runtime_safely(prior.runtime)
        prior_session = None

    def reject_candidate() -> None:
        global _session
        _dispose_runtime_safely(candidate_runtime)
        candidate_dispatcher.close()
        _session = prior_session
        restore(prior_kinds)

    candidate_runtime._on_initial_promotion = promote_candidate
    candidate_runtime._on_initial_rejection = reject_candidate
    _session = candidate


# ---------------------------------------------------------------------------
# Named surface sessions (RenderSurface)
# ---------------------------------------------------------------------------

# The bootstrap start lock serializes app mounts process-wide; a receiver
# cold start racing a MainActivity start can lose the lock. Retry briefly so
# the surface start survives the race instead of failing the trigger.
_MOUNT_RETRIES = 10
_MOUNT_RETRY_DELAY_S = 0.05


def start_surface(
    name: str,
    module_name: str,
    host: Any,
    data: Any = None,
) -> None:
    """Mount one named surface app and publish its commits through *host*.

    A surface session is fully independent of the main session: it gets its
    own transport, its own Runtime, and its own single-owner dispatcher
    thread (bound to *name* so session-aware APIs resolve to it). The
    surface's launch payload is *data* (a plain mapping), delivered through
    the same AppContext machinery as Android launches.
    """
    from vyne.direct_transport import DirectTransport
    from vyne.extensions_registry import restore, snapshot, sync_from_host

    global _sessions

    if not isinstance(name, str) or not name:
        raise TypeError("surface name must be a non-empty string")
    if name in _sessions:
        raise RuntimeError(f"Surface {name!r} is already started")

    prior_kinds = snapshot()
    candidate_dispatcher: AsyncRuntimeDispatcher | None = None
    try:
        sync_from_host(_query_extension_kinds(host))
        launch_data = _surface_launch_data(data, sequence=1)
        session_id = uuid4().hex
        candidate_transport = DirectTransport(host, session_id)
        candidate_dispatcher = AsyncRuntimeDispatcher(
            thread_setup=lambda: setattr(
                _bridge_thread, "session_name", name
            )
        )
        candidate = _DirectSession(
            host=host,
            runtime=None,  # filled once the candidate Runtime exists
            transport=candidate_transport,
            dispatcher=candidate_dispatcher,
        )
        # The cold launch consumes sequence 1; warm deliveries continue from
        # 2 so every delivery is distinguishable from the start (launch
        # sequence is the standard freshness key for app state).
        candidate.surface_sequence = 2
        _sessions[name] = candidate
        candidate_runtime = _mount_registered_app_with_retry(
            candidate_dispatcher,
            module_name,
            transport=candidate_transport,
            launch_data=launch_data,
            session_id=session_id,
        )
        candidate.runtime = candidate_runtime
        if candidate_transport.send_count == 0:
            candidate_dispatcher.call(
                lambda: _dispose_runtime_safely(candidate_runtime)
            )
            raise RuntimeError(
                f"Surface {name!r} produced no initial commit"
            )
    except BaseException:
        _sessions.pop(name, None)
        if candidate_dispatcher is not None:
            candidate_dispatcher.close()
        restore(prior_kinds)
        raise


def _mount_registered_app_with_retry(
    dispatcher: AsyncRuntimeDispatcher,
    module_name: str,
    *,
    transport: Any,
    launch_data: LaunchData,
    session_id: str,
) -> Any:
    """Mount an app module on the session dispatcher, retrying briefly on
    the process-wide start lock (a receiver cold start can race the main
    Activity's mount)."""
    import time

    last_error: BaseException | None = None
    for _ in range(_MOUNT_RETRIES):
        try:
            return dispatcher.call(
                lambda: _start_registered_app(
                    module_name,
                    transport=transport,
                    launch_data=launch_data,
                    session_id=session_id,
                )
            )
        except RuntimeError as error:
            last_error = error
            time.sleep(_MOUNT_RETRY_DELAY_S)
    raise RuntimeError(
        f"Could not mount {module_name!r} after {_MOUNT_RETRIES} attempts: "
        f"{last_error}"
    )


def deliver_surface_data(name: str, data: Any = None) -> None:
    """Deliver a warm data update to a started surface, in order."""
    session = _sessions.get(name)
    if session is None or session.runtime is None:
        raise RuntimeError(f"Surface {name!r} is not started")
    launch_data = _surface_launch_data(data, sequence=session.surface_sequence)
    session.surface_sequence += 1
    _call_runtime_for(
        session,
        lambda: _deliver_launch(session.runtime, launch_data),
    )


def unmount_surface(name: str, expected_host: Any = None) -> None:
    """Dispose one surface runtime and drop its session slot.

    *expected_host* gates teardown by host identity so a stale surface
    bridge can never dispose a newer session under the same name.
    """
    global _sessions
    session = _sessions.get(name)
    if session is None:
        return
    if expected_host is not None and session.host is not expected_host:
        return
    if session.dispatcher is not None:
        session.dispatcher.call(
            lambda: _dispose_runtime_safely(session.runtime)
        )
        session.dispatcher.close()
    else:
        _dispose_runtime_safely(session.runtime)
    _sessions.pop(name, None)


def dispatch_events_surface(name: str, events: Any) -> None:
    """Dispatch a Java list of native events to one surface runtime."""
    session = _sessions.get(name)
    if session is None or session.runtime is None:
        raise RuntimeError(f"Surface {name!r} is not started")
    decoded = []
    for index in range(int(events.size())):
        event = events.get(index)
        decoded.append(
            _native_event(
                event.getSequence(),
                event.getTarget(),
                event.getName(),
                event.getHandler(),
                event.getPayload(),
            )
        )
    _call_runtime_for(
        session,
        lambda: session.runtime.dispatch_native_events(decoded),
        settle=True,
    )


def dispatch_event_surface(
    name: str,
    sequence: int,
    target: int,
    event_name: str,
    handler: int,
    payload: Any,
) -> None:
    """Dispatch the common single-event case for one surface runtime."""
    session = _sessions.get(name)
    if session is None or session.runtime is None:
        raise RuntimeError(f"Surface {name!r} is not started")
    event = _native_event(sequence, target, event_name, handler, payload)
    _call_runtime_for(
        session,
        lambda: session.runtime.dispatch_native_events([event]),
        settle=True,
    )


def dispatch_apply_result_surface(
    name: str,
    result: str,
    revision: int,
    session_id: str,
) -> None:
    """Handle the receipt-only path for one surface runtime."""
    session = _sessions.get(name)
    if session is None or session.runtime is None:
        raise RuntimeError(f"Surface {name!r} is not started")
    decoded = (str(result), int(revision), str(session_id))
    _call_runtime_for(
        session,
        lambda: session.runtime.handle_native_apply_result(*decoded),
    )


def dispatch_external_callbacks_surface(name: str, tasks: Any) -> None:
    """Decode queued Android extension work for one surface runtime."""
    session = _sessions.get(name)
    if session is None or session.runtime is None:
        raise RuntimeError(f"Surface {name!r} is not started")

    callbacks = []
    disposed = []
    for index in range(int(tasks.size())):
        task = tasks.get(index)
        subscription = task.getCallback()
        if task.getKind() == "dispose":
            disposed.append(subscription)
        elif task.getKind() == "call":
            callbacks.append((subscription, _java_value(task.getPayload())))
        else:
            raise ValueError(
                f"Unknown external callback task: {task.getKind()!r}"
            )
    _call_runtime_for(
        session,
        lambda: session.runtime.dispatch_external_callbacks(callbacks, disposed),
        settle=True,
    )


def _surface_launch_data(data: Any, sequence: int) -> LaunchData:
    """Wrap one surface data payload as a LaunchData (action + extras)."""
    decoded = {} if data is None else _java_value(data)
    if not isinstance(decoded, dict):
        raise TypeError("Surface data must be a mapping")
    return LaunchData.from_native(
        "vyne_surface",
        None,
        decoded,
        sequence,
    )


def _call_runtime_for(
    session: _DirectSession | None,
    function: Any,
    *,
    settle: bool = False,
) -> Any:
    """Run one bridge turn on a specific session's single-owner loop."""
    if session is not None and session.dispatcher is not None:
        return session.dispatcher.call(
            function,
            settle=session.runtime if settle else None,
        )
    return function()


def deliver_launch_direct(
    action: Any,
    uri: Any,
    extras: Any,
    sequence: Any,
) -> None:
    """Deliver a later Android launch to the live root app, in order.

    The pre_launch chain runs first (capture hook, errors logged); the root
    re-render follows only when the app function accepts an AppContext
    argument (zero-argument apps keep today's capture-only behavior).
    """
    session = _session
    if session is None or session.runtime is None:
        raise RuntimeError("Python runtime is not started")
    launch_data = _native_launch_data(action, uri, extras, sequence)
    _call_runtime(lambda: _deliver_launch(session.runtime, launch_data))


def _deliver_launch(runtime: Any, launch_data: LaunchData) -> None:
    """One ordered warm delivery: pre_launch chain, then root re-render.

    The chain travels with the Runtime (set at cold start), so warm
    deliveries always use exactly the hooks the cold start used. Hooks
    and root both receive the AppContext built from this launch.
    """
    from vyne.bootstrap import _run_pre_launch_chain

    context = runtime.build_root_context(launch_data)
    _run_pre_launch_chain(runtime.pre_launch_hooks, context)
    if runtime.root_argument_count == 0:
        return
    runtime.update_root_arguments(context)


def back_press_query() -> bool:
    """Host query: should this system back press be consumed?

    Runs the app's back handlers (LIFO) on the runtime loop, ordered
    with everything else the loop owns. ``True`` means the host must not
    perform its default (finish the activity).
    """
    session = _session
    if session is None or session.runtime is None:
        return False
    return bool(_call_runtime(lambda: session.runtime.handle_back_press()))


def dispatch_events_direct(events: Any) -> None:
    """Dispatch a Java list of native events in one Python render batch."""
    session = _session
    if session is None or session.runtime is None:
        raise RuntimeError("Python runtime is not started")

    decoded = []
    for index in range(int(events.size())):
        event = events.get(index)
        decoded.append(
            _native_event(
                event.getSequence(),
                event.getTarget(),
                event.getName(),
                event.getHandler(),
                event.getPayload(),
            )
        )
    _call_runtime(
        lambda: session.runtime.dispatch_native_events(decoded),
        settle=True,
    )


def dispatch_event_direct(
    sequence: int,
    target: int,
    name: str,
    handler: int,
    payload: Any,
) -> None:
    """Dispatch the common single-event case without an encoded payload."""
    session = _session
    if session is None or session.runtime is None:
        raise RuntimeError("Python runtime is not started")
    event = _native_event(sequence, target, name, handler, payload)
    _call_runtime(
        lambda: session.runtime.dispatch_native_events([event]),
        settle=True,
    )


def dispatch_apply_result_direct(
    result: str,
    revision: int,
    session: str,
) -> None:
    """Handle the common receipt-only path without a synthetic Event."""
    session_agg = _session
    if session_agg is None or session_agg.runtime is None:
        raise RuntimeError("Python runtime is not started")
    decoded = (str(result), int(revision), str(session))
    _call_runtime(
        lambda: session_agg.runtime.handle_native_apply_result(*decoded)
    )


def dispatch_external_callbacks_direct(tasks: Any) -> None:
    """Decode queued Android extension work into one Runtime-owned batch."""
    session = _session
    if session is None or session.runtime is None:
        raise RuntimeError("Python runtime is not started")

    callbacks = []
    disposed = []
    for index in range(int(tasks.size())):
        task = tasks.get(index)
        subscription = task.getCallback()
        if task.getKind() == "dispose":
            disposed.append(subscription)
        elif task.getKind() == "call":
            callbacks.append((subscription, _java_value(task.getPayload())))
        else:
            raise ValueError(f"Unknown external callback task: {task.getKind()!r}")
    _call_runtime(
        lambda: session.runtime.dispatch_external_callbacks(callbacks, disposed),
        settle=True,
    )


def _native_event(
    sequence: Any,
    target: Any,
    name: Any,
    handler: Any,
    payload: Any,
) -> Event:
    decoded_payload = _java_value(payload)
    if not isinstance(decoded_payload, dict):
        raise TypeError("Native event payload must be a mapping")
    return Event(
        name=str(name),
        target=int(target),
        handler=int(handler),
        payload=decoded_payload,
        sequence=int(sequence),
    )


def _native_launch_data(
    action: Any,
    uri: Any,
    extras: Any,
    sequence: Any,
) -> LaunchData:
    decoded_extras = {} if extras is None else _java_value(extras)
    if not isinstance(decoded_extras, dict):
        raise TypeError("Native launch extras must be a mapping")
    return LaunchData.from_native(
        action,
        uri,
        decoded_extras,
        sequence,
    )


def _query_extension_kinds(host: Any) -> dict[str, Any]:
    """Query the host registry: kind -> raw bridge value, decoded.

    The raw value is the full ``[props, events, [container]]`` shape —
    `ExtensionKindInfo.from_bridge` is the ONLY adapter and validates it.
    Pure-Python hosts (tests, MemoryTransport) may not implement the query;
    they simply have no extensions.
    """
    query = getattr(host, "extensionKinds", None)
    if query is None:
        return {}
    kinds = query()
    if kinds is None:
        return {}
    return {str(kind): value for kind, value in _java_value(kinds).items()}


def _java_value(value: Any) -> Any:
    """Convert Java collection values to ordinary Python containers."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _java_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_java_value(item) for item in value]

    key_set = getattr(value, "keySet", None)
    java_get = getattr(value, "get", None)
    if key_set is not None and java_get is not None:
        result: dict[str, Any] = {}
        for key in key_set().toArray():
            result[str(key)] = _java_value(java_get(key))
        return result

    size = getattr(value, "size", None)
    if size is not None and java_get is not None:
        return [_java_value(java_get(index)) for index in range(int(size()))]

    return value


def shutdown_runtime(expected_host: Any = None) -> None:
    """Dispose the live Runtime and clear the Android module globals.

    *expected_host* gates the shutdown by host identity: a destroyed
    Activity racing a newer session must never dispose the newer session
    (its executor is separate, but the Python slot is shared).
    """
    global _session
    session = _session
    if session is None:
        return
    if expected_host is not None and session.host is not expected_host:
        return
    if session.dispatcher is not None:
        session.dispatcher.call(lambda: _dispose_runtime_safely(session.runtime))
    else:
        _dispose_runtime_safely(session.runtime)
    if session.dispatcher is not None:
        session.dispatcher.close()
    _session = None


def _call_runtime(function: Any, *, settle: bool = False) -> Any:
    """Run one bridge turn on the Runtime's single-owner asyncio loop."""
    session = _session
    if session is not None and session.dispatcher is not None:
        return session.dispatcher.call(
            function,
            settle=session.runtime if settle else None,
        )
    return function()


def _dispose_runtime_safely(runtime: Any) -> None:
    try:
        runtime.dispose()
    except Exception:
        pass
