from __future__ import annotations

import sys

import pytest

from vyne import AppContext, LaunchData, Text, state
from vyne.bootstrap import _accepts_context, _start_registered_app
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport

from tests.support.runtime_helpers import SilentTransport
from vyne.values import FrozenMap


def test_launch_data_is_deeply_immutable() -> None:
    source = {"route": "detail", "nested": {"ids": [1, 2]}}
    launch = LaunchData(
        action="dev.vyne.OPEN",
        uri="vyne://item/4",
        extras=source,
        sequence=7,
    )

    source["route"] = "mutated"
    source["nested"]["ids"].append(3)

    assert isinstance(launch.extras, FrozenMap)
    assert launch.extras["route"] == "detail"
    assert launch.extras["nested"]["ids"] == (1, 2)
    with pytest.raises(AttributeError):
        launch.sequence = 8  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"extras": {"bad": object()}},
        {"extras": {1: "bad"}},
        {"sequence": True},
        {"sequence": -1},
        {"action": 3},
        {"uri": 4},
    ],
)
def test_launch_data_rejects_malformed_values(kwargs) -> None:
    with pytest.raises(TypeError):
        LaunchData(**kwargs)


def test_root_signature_is_zero_or_one_positional_argument() -> None:
    assert not _accepts_context(lambda: Text(text="zero"))
    assert _accepts_context(lambda context: Text(text=str(context.launch.sequence)))

    def keyword_only(*, context):
        return Text(text=str(context.launch.sequence))

    with pytest.raises(TypeError):
        _accepts_context(keyword_only)

    def variadic(*contexts):
        return Text(text=str(len(contexts)))

    with pytest.raises(TypeError):
        _accepts_context(variadic)


def test_bootstrap_supplies_context_before_first_render(tmp_path, monkeypatch) -> None:
    module_name = "vyne_test_initial_launch"
    source = """
from vyne import AppContext, Text, run_app

observed = []

def App(context: AppContext):
    observed.append(context.launch)
    return Text(text=context.launch.extras["route"])

run_app(App)
"""
    (tmp_path / f"{module_name}.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    launch = LaunchData(extras={"route": "notification"}, sequence=1)

    try:
        runtime = _start_registered_app(
            module_name,
            transport=MemoryTransport(),
            launch_data=launch,
        )
        assert sys.modules[module_name].observed == [launch]
        runtime.dispose()
    finally:
        sys.modules.pop(module_name, None)


def test_launch_update_preserves_root_state_cells() -> None:
    cells = []
    observed = []

    def App(context: AppContext):
        count = state(0)
        cells.append(count)
        observed.append(context.launch.sequence)
        return Text(text=f"{context.launch.sequence}:{count.value}")

    runtime = Runtime(App, transport=MemoryTransport())
    runtime.set_context_root(LaunchData(sequence=1))
    runtime.mount()
    first_cell = cells[-1]
    first_cell.set(4)

    runtime.update_root_arguments(
        runtime.build_root_context(LaunchData(sequence=2))
    )

    assert observed[-1] == 2
    assert cells[-1] is first_cell
    assert cells[-1].value == 4


def test_launches_wait_for_in_flight_commit_and_keep_order() -> None:
    observed = []

    def App(context: AppContext):
        observed.append(context.launch.sequence)
        return Text(text=str(context.launch.sequence))

    transport = SilentTransport()
    runtime = Runtime(App, transport=transport)
    runtime.set_context_root(LaunchData(sequence=1))
    runtime.mount()

    runtime.update_root_arguments(
        runtime.build_root_context(LaunchData(sequence=2))
    )
    runtime.update_root_arguments(
        runtime.build_root_context(LaunchData(sequence=3))
    )
    assert observed == [1]

    runtime.acknowledge_native_apply(1)
    assert observed == [1, 2]
    assert len(transport.messages) == 2

    runtime.acknowledge_native_apply(2)
    assert observed == [1, 2, 3]
    assert len(transport.messages) == 3
