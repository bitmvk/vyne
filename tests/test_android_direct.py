from __future__ import annotations

from types import SimpleNamespace

import vyne.android as android
import vyne.direct_transport as direct_transport
from vyne import Text
from vyne.events import Event
from vyne.launch import LaunchData
from vyne.runtime import Runtime


class RecordingRuntime:
    def __init__(self) -> None:
        self.events = None
        self.root_argument_count = 1
        self.pre_launch_hooks = ()

    def dispatch_native_events(self, events) -> None:
        self.events = events

    def handle_native_apply_result(self, result, revision, session) -> None:
        self.receipt = (result, revision, session)

    def build_root_context(self, launch):
        return launch

    def update_root_arguments(self, *args) -> None:
        self.root_arguments = args


class JavaArray:
    def __init__(self, values) -> None:
        self.values = values

    def __iter__(self):
        return iter(self.values)


class JavaKeySet:
    def __init__(self, keys) -> None:
        self.keys = keys

    def toArray(self) -> JavaArray:
        return JavaArray(self.keys)


class JavaMap:
    def __init__(self, values) -> None:
        self.values = values

    def keySet(self) -> JavaKeySet:
        return JavaKeySet(list(self.values))

    def get(self, key):
        return self.values[key]


class JavaList:
    def __init__(self, values) -> None:
        self.values = values

    def size(self) -> int:
        return len(self.values)

    def get(self, index):
        return self.values[index]


class AndroidHost:
    def __init__(self) -> None:
        self.current_activity = object()
        self.created_callbacks = []

    def getActivity(self):
        return self.current_activity

    def createCallback(self, subscription, delivery, sample_interval_ms):
        record = (subscription, delivery, sample_interval_ms)
        self.created_callbacks.append(record)
        return ("native-callback", *record)


class ExternalTask:
    def __init__(self, kind, callback, payload=None) -> None:
        self.kind = kind
        self.callback = callback
        self.payload = payload

    def getKind(self):
        return self.kind

    def getCallback(self):
        return self.callback

    def getPayload(self):
        return self.payload


class StartedRuntime(RecordingRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.disposed = False
        self._on_initial_promotion = None
        self._on_initial_rejection = None

    def dispose(self) -> None:
        self.disposed = True


def make_session(host=None, runtime=None):
    """Build one _DirectSession aggregate for monkeypatching."""
    return android._DirectSession(
        host=host if host is not None else AndroidHost(),
        runtime=runtime if runtime is not None else StartedRuntime(),
        transport=object(),
        dispatcher=None,
    )


class StartedTransport:
    def __init__(self, host, session_id=None) -> None:
        self.host = host
        self.session_id = session_id or "test-session"
        self.send_count = 1


def test_activity_returns_the_current_android_activity(monkeypatch) -> None:
    host = AndroidHost()
    monkeypatch.setattr(android, "_session", make_session(host=host))

    assert android.activity() is host.current_activity


def test_callback_delegates_callable_wrapping_to_android_host(monkeypatch) -> None:
    host = AndroidHost()
    runtime = Runtime(lambda: Text(text="callback test"))
    runtime.mount()
    received = []

    def function(payload):
        received.append(payload)

    monkeypatch.setattr(android, "_session", make_session(host=host, runtime=runtime))

    wrapped = android.callback(
        function,
        delivery="latest",
        sample_interval_ms=25,
    )

    assert wrapped[0] == "native-callback"
    subscription = wrapped[1]
    assert host.created_callbacks == [(subscription, "latest", 25)]

    android.dispatch_external_callbacks_direct(
        JavaList(
            [
                ExternalTask(
                    "call",
                    subscription,
                    JavaMap(
                        {
                            "enabled": True,
                            "samples": JavaList([3, 5]),
                        }
                    ),
                )
            ]
        )
    )

    assert received == [{"enabled": True, "samples": [3, 5]}]


def test_external_callback_disposal_crosses_the_typed_bridge(monkeypatch) -> None:
    host = AndroidHost()
    runtime = Runtime(lambda: Text(text="callback disposal"))
    runtime.mount()
    received = []
    monkeypatch.setattr(android, "_session", make_session(host=host, runtime=runtime))
    subscription = android.callback(received.append)[1]

    android.dispatch_external_callbacks_direct(
        JavaList(
            [
                ExternalTask("dispose", subscription),
                ExternalTask("call", subscription, "ignored"),
            ]
        )
    )

    assert received == []
    assert subscription.active is False


def test_callback_validates_delivery_policy(monkeypatch) -> None:
    runtime = Runtime(lambda: Text(text="callback validation"))
    runtime.mount()
    monkeypatch.setattr(android, "_session", make_session(runtime=runtime))

    for arguments, message in (
        ({"delivery": "newest"}, "delivery"),
        ({"sample_interval_ms": 0}, "sample_interval_ms"),
        ({"sample_interval_ms": True}, "sample_interval_ms"),
    ):
        try:
            android.callback(lambda _: None, **arguments)
        except ValueError as error:
            assert message in str(error)
        else:
            raise AssertionError("callback() should reject invalid policy")


def test_android_escape_hatch_requires_a_started_host(monkeypatch) -> None:
    monkeypatch.setattr(android, "_session", None)

    for operation in (android.activity, lambda: android.callback(lambda _: None)):
        try:
            operation()
        except RuntimeError as error:
            assert str(error) == "Android host is not started"
        else:
            raise AssertionError("operation should require a started Android host")


def test_callback_rejects_non_callable_values(monkeypatch) -> None:
    monkeypatch.setattr(android, "_session", make_session())

    try:
        android.callback("not callable")
    except TypeError as error:
        assert str(error) == "callback() requires a callable"
    else:
        raise AssertionError("callback() should reject non-callable values")


def test_android_host_is_available_during_initial_app_execution(monkeypatch) -> None:
    host = AndroidHost()
    runtime = StartedRuntime()
    observed = []

    def start_app(module_name, *, transport, launch_data, session_id=None):
        observed.append(
            (module_name, android.activity(), transport, launch_data, session_id)
        )
        return runtime

    monkeypatch.setattr(android, "_session", None)
    monkeypatch.setattr(android, "_start_registered_app", start_app)
    monkeypatch.setattr(direct_transport, "DirectTransport", StartedTransport)

    android.start_direct("extension_app", host)

    assert observed[0][:4] == (
        "extension_app",
        host.current_activity,
        android._session.transport,
        LaunchData(sequence=0),
    )
    assert observed[0][4] == android._session.transport.session_id
    assert android._session.runtime is runtime
    assert android._session.host is host


def test_failed_start_restores_the_previous_android_host(monkeypatch) -> None:
    previous_host = AndroidHost()
    candidate_host = AndroidHost()

    def fail_start(module_name, *, transport, launch_data, session_id=None):
        assert android.activity() is candidate_host.current_activity
        raise ValueError("bad app")

    monkeypatch.setattr(android, "_session", make_session(host=previous_host))
    monkeypatch.setattr(android, "_start_registered_app", fail_start)
    monkeypatch.setattr(direct_transport, "DirectTransport", StartedTransport)

    try:
        android.start_direct("broken_app", candidate_host)
    except ValueError as error:
        assert str(error) == "bad app"
    else:
        raise AssertionError("start_direct should propagate startup errors")

    assert android._session.host is previous_host


def test_single_direct_event_uses_typed_arguments(monkeypatch) -> None:
    runtime = RecordingRuntime()
    monkeypatch.setattr(android, "_session", make_session(runtime=runtime))

    android.dispatch_event_direct(
        12,
        4,
        "click",
        9,
        {"x": 15, "nested": {"ok": True}},
    )

    assert runtime.events == [
        Event(
            name="click",
            target=4,
            handler=9,
            payload={"x": 15, "nested": {"ok": True}},
            sequence=12,
        )
    ]


def test_java_collections_cross_the_direct_event_boundary(monkeypatch) -> None:
    runtime = RecordingRuntime()
    monkeypatch.setattr(android, "_session", make_session(runtime=runtime))

    android.dispatch_event_direct(
        13,
        5,
        "pointer_move",
        10,
        JavaMap(
            {
                "x": 15.5,
                "history": JavaList(
                    [JavaMap({"x": 10, "y": 20}), JavaMap({"x": 12, "y": 22})]
                ),
            }
        ),
    )

    assert runtime.events[0].payload == {
        "x": 15.5,
        "history": [{"x": 10, "y": 20}, {"x": 12, "y": 22}],
    }


def test_apply_receipt_uses_typed_runtime_entry_point(monkeypatch) -> None:
    runtime = RecordingRuntime()
    monkeypatch.setattr(android, "_session", make_session(runtime=runtime))

    android.dispatch_apply_result_direct(
        "ok",
        17,
        "vyne-runtime-session",
    )

    assert runtime.receipt == ("ok", 17, "vyne-runtime-session")


def test_warm_launch_uses_typed_immutable_root_input(monkeypatch) -> None:
    runtime = RecordingRuntime()
    monkeypatch.setattr(android, "_session", make_session(runtime=runtime))

    android.deliver_launch_direct(
        "dev.vyne.OPEN",
        "vyne://conversation/42",
        JavaMap(
            {
                "route": "conversation",
                "ids": JavaList([4, 8]),
            }
        ),
        5,
    )

    assert runtime.root_arguments == (
        LaunchData(
            action="dev.vyne.OPEN",
            uri="vyne://conversation/42",
            extras={"route": "conversation", "ids": [4, 8]},
            sequence=5,
            origin="warm",
        ),
    )


def test_warm_launch_is_ignored_for_zero_argument_app(monkeypatch) -> None:
    runtime = RecordingRuntime()
    runtime.root_argument_count = 0
    monkeypatch.setattr(android, "_session", make_session(runtime=runtime))

    android.deliver_launch_direct(None, None, {}, 2)

    assert not hasattr(runtime, "root_arguments")


# ---------------------------------------------------------------------------
# Named surface sessions (RenderSurface)
# ---------------------------------------------------------------------------

class SurfaceRuntime(RecordingRuntime):
    """RecordingRuntime + the launch context a surface app receives."""

    def __init__(self) -> None:
        super().__init__()
        self.external_callbacks = None
        self.external_disposed = None

    def build_root_context(self, launch):
        return SimpleNamespace(launch=launch)

    def dispatch_external_callbacks(self, callbacks, disposed) -> None:
        self.external_callbacks = callbacks
        self.external_disposed = disposed


def make_surface_sessions(monkeypatch) -> dict:
    sessions = {}
    monkeypatch.setattr(android, "_sessions", sessions)
    return sessions


def test_surface_start_mounts_an_independent_session(monkeypatch) -> None:
    host = AndroidHost()
    runtime = StartedRuntime()
    started = []

    def start_app(module_name, *, transport, launch_data, session_id=None):
        started.append((module_name, transport, launch_data, session_id))
        return runtime

    monkeypatch.setattr(android, "_session", None)
    monkeypatch.setattr(android, "_start_registered_app", start_app)
    monkeypatch.setattr(direct_transport, "DirectTransport", StartedTransport)
    make_surface_sessions(monkeypatch)

    android.start_surface("sms_overlay", "second_surface", host, {"sender": "A"})

    module_name, transport, launch_data, session_id = started[0]
    assert module_name == "second_surface"
    assert transport is android._sessions["sms_overlay"].transport
    assert launch_data.action == "vyne_surface"
    assert dict(launch_data.extras) == {"sender": "A"}
    assert launch_data.sequence == 1
    assert session_id == transport.session_id
    assert android._sessions["sms_overlay"].host is host
    assert android._sessions["sms_overlay"].runtime is runtime
    # Cold launch consumed sequence 1; warm deliveries continue from 2.
    assert android._sessions["sms_overlay"].surface_sequence == 2


def test_surface_start_rejects_duplicate_names(monkeypatch) -> None:
    runtime = StartedRuntime()
    monkeypatch.setattr(android, "_start_registered_app",
                        lambda *a, **k: runtime)
    monkeypatch.setattr(direct_transport, "DirectTransport", StartedTransport)
    sessions = make_surface_sessions(monkeypatch)
    sessions["sms_overlay"] = make_session(host=AndroidHost(), runtime=runtime)

    try:
        android.start_surface("sms_overlay", "second_surface", AndroidHost())
    except RuntimeError as error:
        assert "already started" in str(error)
    else:
        raise AssertionError("start_surface should reject duplicate names")


def test_surface_start_failure_removes_the_candidate(monkeypatch) -> None:
    def fail_start(module_name, *, transport, launch_data, session_id=None):
        raise ValueError("bad surface app")

    monkeypatch.setattr(android, "_start_registered_app", fail_start)
    monkeypatch.setattr(direct_transport, "DirectTransport", StartedTransport)
    sessions = make_surface_sessions(monkeypatch)

    try:
        android.start_surface("bad", "bad_module", AndroidHost())
    except ValueError as error:
        assert str(error) == "bad surface app"
    else:
        raise AssertionError("start_surface should propagate startup errors")

    assert "bad" not in sessions


def test_surface_start_validates_name_and_data(monkeypatch) -> None:
    make_surface_sessions(monkeypatch)

    try:
        android.start_surface("", "m", AndroidHost())
    except TypeError as error:
        assert "surface name" in str(error)
    else:
        raise AssertionError("start_surface should reject an empty name")

    try:
        android.start_surface("ok", "m", AndroidHost(), data=[1, 2])
    except TypeError as error:
        assert "mapping" in str(error)
    else:
        raise AssertionError("start_surface should reject non-mapping data")


def test_deliver_surface_data_updates_root_arguments(monkeypatch) -> None:
    runtime = SurfaceRuntime()
    session = make_session(host=AndroidHost(), runtime=runtime)
    sessions = make_surface_sessions(monkeypatch)
    sessions["sms_overlay"] = session

    android.deliver_surface_data("sms_overlay", {"show": False})

    assert runtime.root_arguments is not None
    assert runtime.root_arguments[0].launch.sequence == 1
    assert dict(runtime.root_arguments[0].launch.extras) == {"show": False}
    assert session.surface_sequence == 2


def test_deliver_surface_data_requires_a_started_surface(monkeypatch) -> None:
    make_surface_sessions(monkeypatch)

    try:
        android.deliver_surface_data("ghost", {"show": True})
    except RuntimeError as error:
        assert "not started" in str(error)
    else:
        raise AssertionError("deliver_surface_data should require a started surface")


def test_surface_event_routes_to_its_own_runtime(monkeypatch) -> None:
    runtime = SurfaceRuntime()
    session = make_session(host=AndroidHost(), runtime=runtime)
    sessions = make_surface_sessions(monkeypatch)
    sessions["sms_overlay"] = session

    android.dispatch_event_surface(
        "sms_overlay",
        12,
        4,
        "click",
        9,
        JavaMap({"x": 15, "nested": JavaMap({"ok": True})}),
    )

    assert runtime.events == [
        Event(
            name="click",
            target=4,
            handler=9,
            payload={"x": 15, "nested": {"ok": True}},
            sequence=12,
        )
    ]


def test_surface_apply_receipt_routes_to_its_own_runtime(monkeypatch) -> None:
    runtime = SurfaceRuntime()
    session = make_session(host=AndroidHost(), runtime=runtime)
    sessions = make_surface_sessions(monkeypatch)
    sessions["sms_overlay"] = session

    android.dispatch_apply_result_surface("sms_overlay", "ok", 7, "sess-1")

    assert runtime.receipt == ("ok", 7, "sess-1")


def test_surface_external_callbacks_route_to_its_own_runtime(monkeypatch) -> None:
    runtime = SurfaceRuntime()
    session = make_session(host=AndroidHost(), runtime=runtime)
    sessions = make_surface_sessions(monkeypatch)
    sessions["sms_overlay"] = session
    subscription = object()

    android.dispatch_external_callbacks_surface(
        "sms_overlay",
        JavaList(
            [
                ExternalTask("call", subscription, JavaMap({"enabled": True})),
                ExternalTask("dispose", subscription),
            ]
        ),
    )

    assert runtime.external_callbacks == [(subscription, {"enabled": True})]
    assert runtime.external_disposed == [subscription]


def test_unmount_surface_disposes_runtime_and_drops_session(monkeypatch) -> None:
    runtime = StartedRuntime()
    host = AndroidHost()
    session = make_session(host=host, runtime=runtime)
    sessions = make_surface_sessions(monkeypatch)
    sessions["sms_overlay"] = session

    android.unmount_surface("sms_overlay", expected_host=host)

    assert runtime.disposed is True
    assert "sms_overlay" not in sessions


def test_unmount_surface_is_gated_by_host_identity(monkeypatch) -> None:
    runtime = StartedRuntime()
    session = make_session(host=AndroidHost(), runtime=runtime)
    sessions = make_surface_sessions(monkeypatch)
    sessions["sms_overlay"] = session

    android.unmount_surface("sms_overlay", expected_host=object())

    assert runtime.disposed is False
    assert "sms_overlay" in sessions


def test_callback_resolves_the_bound_surface_session(monkeypatch) -> None:
    host = AndroidHost()
    runtime = Runtime(lambda: Text(text="surface callback"))
    runtime.mount()
    session = make_session(host=host, runtime=runtime)
    sessions = make_surface_sessions(monkeypatch)
    sessions["sms_overlay"] = session

    monkeypatch.setattr(android._bridge_thread, "session_name", "sms_overlay", raising=False)
    wrapped = android.callback(lambda payload: None)

    assert wrapped[0] == "native-callback"
    assert host.created_callbacks[0][0] is not None
    assert host.created_callbacks[0][1] == "all"


def test_callback_defaults_to_the_main_session(monkeypatch) -> None:
    host = AndroidHost()
    runtime = Runtime(lambda: Text(text="main callback"))
    runtime.mount()
    monkeypatch.setattr(android, "_session", make_session(host=host, runtime=runtime))
    make_surface_sessions(monkeypatch)
    if hasattr(android._bridge_thread, "session_name"):
        del android._bridge_thread.session_name

    wrapped = android.callback(lambda payload: None)

    assert wrapped[0] == "native-callback"
    assert host.created_callbacks[0][1] == "all"


# ---------------------------------------------------------------------------
# Shared dispatch seam (main + surface through one decoder / dispatcher)
# ---------------------------------------------------------------------------

class JavaEvent:
    """Minimal Java wrapper for one native event in a batch."""

    def __init__(self, sequence, target, name, handler, payload) -> None:
        self.sequence = sequence
        self.target = target
        self.name = name
        self.handler = handler
        self.payload = payload

    def getSequence(self):
        return self.sequence

    def getTarget(self):
        return self.target

    def getName(self):
        return self.name

    def getHandler(self):
        return self.handler

    def getPayload(self):
        return self.payload


class RecordingDispatcher:
    """Records (function, settle) bridge turns without running them."""

    def __init__(self) -> None:
        self.calls = []

    def call(self, function, settle=None):
        self.calls.append((function, settle))


def _session_with_dispatcher(runtime, dispatcher):
    return android._DirectSession(
        host=AndroidHost(),
        runtime=runtime,
        transport=object(),
        dispatcher=dispatcher,
    )


def test_batch_dispatch_is_isolated_per_session_dispatcher(monkeypatch) -> None:
    """Batch events route through the owning session's dispatcher only.

    Main batches never reach the surface dispatcher and surface batches
    never reach the main dispatcher; the decoded batch still reaches the
    owning runtime when the recorded bridge turn runs.
    """
    main_runtime = RecordingRuntime()
    surface_runtime = SurfaceRuntime()
    main_dispatcher = RecordingDispatcher()
    surface_dispatcher = RecordingDispatcher()
    monkeypatch.setattr(
        android, "_session",
        _session_with_dispatcher(main_runtime, main_dispatcher),
    )
    sessions = make_surface_sessions(monkeypatch)
    sessions["sms_overlay"] = _session_with_dispatcher(
        surface_runtime, surface_dispatcher
    )

    android.dispatch_events_direct(
        JavaList([JavaEvent(1, 4, "click", 9, {})])
    )
    assert len(main_dispatcher.calls) == 1
    assert len(surface_dispatcher.calls) == 0
    function, settle = main_dispatcher.calls[0]
    assert settle is main_runtime
    function()
    assert main_runtime.events == [
        Event(name="click", target=4, handler=9, payload={}, sequence=1)
    ]

    android.dispatch_events_surface(
        "sms_overlay",
        JavaList([JavaEvent(2, 5, "click", 10, {})]),
    )
    assert len(surface_dispatcher.calls) == 1
    assert len(main_dispatcher.calls) == 1
    function, settle = surface_dispatcher.calls[0]
    assert settle is surface_runtime
    function()
    assert surface_runtime.events == [
        Event(name="click", target=5, handler=10, payload={}, sequence=2)
    ]


def test_shared_ingress_reports_unknown_task_and_not_started(monkeypatch) -> None:
    """The shared seam reports identical decode and not-started errors."""
    monkeypatch.setattr(
        android, "_session",
        make_session(runtime=RecordingRuntime()),
    )
    sessions = make_surface_sessions(monkeypatch)
    sessions["sms_overlay"] = make_session(
        host=AndroidHost(), runtime=SurfaceRuntime()
    )

    for entry in (
        lambda: android.dispatch_external_callbacks_direct(
            JavaList([ExternalTask("callbacks", object())])
        ),
        lambda: android.dispatch_external_callbacks_surface(
            "sms_overlay",
            JavaList([ExternalTask("callbacks", object())]),
        ),
    ):
        try:
            entry()
        except ValueError as error:
            assert "Unknown external callback task" in str(error)
        else:
            raise AssertionError("unknown task kind must raise")

    monkeypatch.setattr(android, "_session", None)
    sessions.clear()
    for operation, message in (
        (lambda: android.dispatch_events_direct(JavaList([])),
         "Python runtime is not started"),
        (lambda: android.dispatch_event_direct(1, 1, "click", 1, {}),
         "Python runtime is not started"),
        (lambda: android.dispatch_external_callbacks_direct(JavaList([])),
         "Python runtime is not started"),
        (lambda: android.dispatch_events_surface("ghost", JavaList([])),
         "Surface 'ghost' is not started"),
        (lambda: android.dispatch_event_surface("ghost", 1, 1, "click", 1, {}),
         "Surface 'ghost' is not started"),
        (lambda: android.dispatch_external_callbacks_surface(
             "ghost", JavaList([])),
         "Surface 'ghost' is not started"),
    ):
        try:
            operation()
        except RuntimeError as error:
            assert str(error) == message
        else:
            raise AssertionError("not-started dispatch must raise")
