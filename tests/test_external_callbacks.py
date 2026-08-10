from __future__ import annotations

import pytest

from vyne import Text, state
from vyne.recovery import RecoveryState
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport


def mounted_runtime():
    cells = {}

    def App():
        value = state(0)
        cells["value"] = value
        return Text(text=f"Value: {value.value}")

    transport = MemoryTransport()
    runtime = Runtime(App, transport=transport)
    runtime.mount()
    return runtime, transport, cells


def test_external_callback_runs_in_runtime_context_and_renders() -> None:
    runtime, transport, cells = mounted_runtime()
    subscription = runtime.subscribe_external_callback(
        lambda payload: cells["value"].set(payload["value"])
    )
    prior_commits = len(transport.messages)

    runtime.dispatch_external_callbacks(
        [(subscription, {"value": 7})],
    )

    assert cells["value"].value == 7
    assert len(transport.messages) == prior_commits + 1


def test_external_callback_disposal_releases_and_rejects_delivery() -> None:
    runtime, transport, cells = mounted_runtime()
    subscription = runtime.subscribe_external_callback(
        lambda payload: cells["value"].set(payload)
    )
    prior_commits = len(transport.messages)

    runtime.dispatch_external_callbacks(
        [(subscription, 5)],
        [subscription],
    )

    assert subscription.active is False
    assert subscription.callback is None
    assert subscription.id not in runtime._external_callbacks
    assert cells["value"].value == 0
    assert len(transport.messages) == prior_commits


def test_runtime_disposal_deactivates_all_external_callbacks() -> None:
    runtime, _, _ = mounted_runtime()
    subscription = runtime.subscribe_external_callback(lambda _: None)
    native_handle = RecordingNativeHandle()
    subscription.attach_native(native_handle)

    runtime.dispose()

    assert runtime.recovery_state is RecoveryState.DISPOSED
    assert subscription.active is False
    assert subscription.callback is None
    assert subscription.native_handle is None
    assert native_handle.dispose_count == 1
    assert runtime._external_callbacks == {}


def test_external_callback_registration_and_entries_are_validated() -> None:
    runtime, _, _ = mounted_runtime()

    with pytest.raises(TypeError, match="callable"):
        runtime.subscribe_external_callback("not callable")
    with pytest.raises(TypeError, match="must be a list"):
        runtime.dispatch_external_callbacks(())
    with pytest.raises(TypeError, match="subscription, payload"):
        runtime.dispatch_external_callbacks([("missing payload",)])


class RecordingNativeHandle:
    def __init__(self) -> None:
        self.dispose_count = 0

    def dispose(self) -> None:
        self.dispose_count += 1
