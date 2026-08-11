from __future__ import annotations

import pytest

import vyne
from vyne import Column, List, ListController, Text, state
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport

from tests.support.runtime_helpers import SilentTransport


def _list(
    data=tuple(range(1000)),
    *,
    axis: str = "vertical",
    controller: ListController | None = None,
    render_item=None,
):
    return List(
        data,
        render_item=(
            render_item
            or (
                lambda item, index: Text(
                    text=str(item),
                    content_description=f"public-item-{item}",
                )
            )
        ),
        key_for_item=lambda item, index: item,
        item_extent=10,
        axis=axis,
        overscan=1,
        controller=controller,
        width=300 if axis == "vertical" else 100,
        height=100 if axis == "vertical" else 50,
        content_description="public-virtual-list",
    )


def _metrics(
    *,
    axis: str,
    offset: float,
    extent: float = 100,
    projected_offset: float | None = None,
    velocity: float = 0.0,
) -> dict:
    projected = offset if projected_offset is None else projected_offset
    return {
        "offset_x": offset if axis == "horizontal" else 0.0,
        "offset_y": offset if axis == "vertical" else 0.0,
        "viewport_width": extent if axis == "horizontal" else 300.0,
        "viewport_height": extent if axis == "vertical" else 50.0,
        "content_width": 10_000.0 if axis == "horizontal" else 300.0,
        "content_height": 10_000.0 if axis == "vertical" else 50.0,
        "velocity_x": 0.0,
        "velocity_y": velocity if axis == "vertical" else 0.0,
        "projected_offset_x": projected if axis == "horizontal" else 0.0,
        "projected_offset_y": projected if axis == "vertical" else 0.0,
        "event_time": 1,
    }


def _emit_metrics(runtime: Runtime, *, axis: str, offset: float) -> None:
    node = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if "scroll_metrics" in node.listeners
    )
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": 1,
            "target": node.id,
            "event": "scroll_metrics",
            "handler": node.listeners["scroll_metrics"],
            "payload": _metrics(axis=axis, offset=offset),
        }
    )


def _emit_projected_scroll(
    runtime: Runtime,
    *,
    offset: float,
    projected: float,
    velocity: float = 0.0,
) -> None:
    """Emit one vertical projected scroll on the mounted list's host."""
    node = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if "scroll_metrics" in node.listeners
    )
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": 1,
            "target": node.id,
            "event": "scroll_metrics",
            "handler": node.listeners["scroll_metrics"],
            "payload": _metrics(
                axis="vertical",
                offset=offset,
                projected_offset=projected,
                velocity=velocity,
            ),
        }
    )


def _texts(runtime: Runtime) -> dict[str, int]:
    return {
        str(node.props.get("content_description")): node.id
        for node in runtime._coordinator.accepted_index.values()
        if node.kind == "Text" and node.props.get("content_description")
    }


def test_public_surface_is_experimental_and_replaced() -> None:
    assert List.__name__ == "List"
    assert ListController.__name__ == "ListController"
    assert vyne.VirtualList is not List
    import vyne.lists as lists_module
    from vyne.experimental.lists import VirtualList, ListController as ExpController

    # The experimental names alias the real public API; there is exactly one
    # controller type and no stale VirtualListController name.
    assert VirtualList is lists_module.VirtualList
    assert VirtualList is vyne.VirtualList
    assert ExpController is lists_module.ListController
    assert not hasattr(lists_module, "VirtualListController")
    assert not hasattr(vyne.experimental.lists, "VirtualListController")


def test_root_exports_list_virtual_list_and_controller() -> None:
    assert vyne.List is List
    assert vyne.VirtualList is not None
    assert vyne.ListController is ListController
    assert "VirtualList" in vyne.__all__
    import vyne.lists as lists_module

    assert set(
        {"List", "ListController", "VirtualList", "VirtualListController"}
    ).intersection(lists_module.__all__) == {"List", "ListController", "VirtualList"}


def test_initial_public_list_covers_declared_viewport_and_overscan() -> None:
    rendered: list[int] = []

    def render_item(item, index):
        rendered.append(index)
        return Text(text=str(item))

    runtime = Runtime(
        lambda: _list(render_item=render_item),
        transport=MemoryTransport(),
    )
    runtime.mount()

    assert rendered == list(range(20))
    assert (
        len(
            [
                node
                for node in runtime._coordinator.accepted_index.values()
                if node.kind == "Text"
            ]
        )
        == 20
    )
    assert len(runtime._coordinator.accepted_index) < 50


@pytest.mark.parametrize(
    ("axis", "expected_kind"),
    [("vertical", "Scroll"), ("horizontal", "HorizontalScroll")],
)
def test_public_list_windows_on_both_axes(axis: str, expected_kind: str) -> None:
    runtime = Runtime(lambda: _list(axis=axis), transport=MemoryTransport())
    runtime.mount()

    _emit_metrics(runtime, axis=axis, offset=500)

    scroll = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if "scroll_metrics" in node.listeners
    )
    assert scroll.kind == expected_kind
    assert set(_texts(runtime)) == {f"public-item-{index}" for index in range(40, 70)}


def test_two_public_controllers_can_swap_mounted_lists() -> None:
    first = ListController()
    second = ListController()
    controls = {}

    def mounted_list(data, controller, item_extent, key):
        return List(
            data,
            render_item=lambda item, index: Text(text=str(item)),
            key_for_item=lambda item, index: item,
            item_extent=item_extent,
            axis="vertical",
            controller=controller,
            key=key,
            height=100,
        )

    def app():
        swapped = state(False)
        controls["swapped"] = swapped
        first_controller, second_controller = (
            (second, first) if swapped.value else (first, second)
        )
        return Column(
            mounted_list(tuple(range(10)), first_controller, 10, "first-list"),
            mounted_list(tuple(range(100, 110)), second_controller, 20, "second-list"),
            Text(
                text="first",
                content_description="first-controller",
                on_click=lambda event: first.scroll_to_index(
                    5,
                    alignment="start",
                    animated=False,
                ),
            ),
            Text(
                text="second",
                content_description="second-controller",
                on_click=lambda event: second.scroll_to_index(
                    5,
                    alignment="start",
                    animated=False,
                ),
            ),
        )

    runtime = Runtime(app, transport=MemoryTransport())
    runtime.mount()
    first_node = first._fixed._scroll_ref.current.node_id
    second_node = second._fixed._scroll_ref.current.node_id

    controls["swapped"].set(True)

    assert first._fixed._scroll_ref.current.node_id == second_node
    assert second._fixed._scroll_ref.current.node_id == first_node
    assert first._fixed._binding.layout.item_extent == 20.0
    assert second._fixed._binding.layout.item_extent == 10.0

    for description, expected_offset in (
        ("first-controller", 100.0),
        ("second-controller", 0.0),
    ):
        button = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.props.get("content_description") == description
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 1,
                "target": button.id,
                "event": "click",
                "handler": button.listeners["click"],
                "payload": {},
            }
        )
        assert runtime.latest_commit["ops"][-1]["offset_y"] == expected_offset


def test_public_controller_jump_replaces_window() -> None:
    controller = ListController()

    def app():
        return Column(
            _list(controller=controller),
            Text(
                text="jump",
                content_description="jump",
                on_click=lambda event: controller.scroll_to_index(
                    50,
                    alignment="start",
                    animated=False,
                ),
            ),
        )

    runtime = Runtime(app, transport=MemoryTransport())
    runtime.mount()
    button = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if node.props.get("content_description") == "jump"
    )
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": 1,
            "target": button.id,
            "event": "click",
            "handler": button.listeners["click"],
            "payload": {},
        }
    )

    assert "public-item-50" in _texts(runtime)
    assert runtime.latest_commit["ops"][-1]["op"] == "scroll_to"
    assert runtime.latest_commit["ops"][-1]["offset_y"] == 500.0


def test_programmatic_window_rebounds_when_data_shrinks_before_metrics() -> None:
    controller = ListController()
    controls = {}

    def app():
        data = state(tuple(range(100)))
        controls["data"] = data
        return Column(
            _list(data=data.value, controller=controller),
            Text(
                text="jump",
                content_description="pre-metrics-jump",
                on_click=lambda event: controller.scroll_to_index(
                    50,
                    alignment="start",
                    animated=False,
                ),
            ),
        )

    runtime = Runtime(app, transport=MemoryTransport())
    runtime.mount()
    button = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if node.props.get("content_description") == "pre-metrics-jump"
    )
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": 1,
            "target": button.id,
            "event": "click",
            "handler": button.listeners["click"],
            "payload": {},
        }
    )
    assert "public-item-50" in _texts(runtime)

    controls["data"].set(tuple(range(20)))

    assert "public-item-19" in _texts(runtime)
    assert "public-item-50" not in _texts(runtime)


def test_unknown_shrink_snapshot_restores_bounded_offset() -> None:
    controls = {}

    def app():
        data = state(tuple(range(100)))
        controls["data"] = data
        return _list(data=data.value)

    transport = SilentTransport()
    runtime = Runtime(app, transport=transport)
    runtime.mount()
    runtime.acknowledge_native_apply(runtime.revision)
    _emit_metrics(runtime, axis="vertical", offset=500)
    runtime.acknowledge_native_apply(runtime.revision)

    controls["data"].set(tuple(range(20)))
    uncertain_revision = runtime.revision
    runtime.report_native_failure(revision=uncertain_revision, unknown=True)

    root_props = next(
        operation["props"]
        for operation in transport.messages[-1]["ops"]
        if operation.get("op") == "set_props" and operation.get("id") == 1
    )
    assert root_props["_virtual_list_initial_offset"] == 100.0


def test_public_list_recovers_window_when_scrolled_data_shrinks() -> None:
    controls = {}

    def app():
        data = state(tuple(range(1000)))
        controls["data"] = data
        return _list(data=data.value)

    runtime = Runtime(app, transport=MemoryTransport())
    runtime.mount()
    _emit_metrics(runtime, axis="vertical", offset=500)
    assert "public-item-50" in _texts(runtime)

    controls["data"].set(tuple(range(20)))

    assert set(_texts(runtime)) == {f"public-item-{index}" for index in range(20)}
    assert len(runtime._coordinator.accepted_index) < 50


def test_animated_jump_plans_the_full_path_and_destination() -> None:
    controller = ListController()

    def app():
        return Column(
            _list(controller=controller),
            Text(
                text="animate",
                content_description="animated-list-jump",
                on_click=lambda event: controller.scroll_to_offset(
                    500,
                    animated=True,
                ),
            ),
        )

    runtime = Runtime(app, transport=MemoryTransport())
    runtime.mount()
    _emit_metrics(runtime, axis="vertical", offset=0)
    button = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if node.props.get("content_description") == "animated-list-jump"
    )
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": 2,
            "target": button.id,
            "event": "click",
            "handler": button.listeners["click"],
            "payload": {},
        }
    )

    assert {key for key in _texts(runtime) if key.startswith("public-item-")} == {
        f"public-item-{index}" for index in range(70)
    }
    assert runtime.latest_commit["ops"][-1] == {
        "op": "scroll_to",
        "id": controller._fixed._scroll_ref.current.node_id,
        "offset_x": 0.0,
        "offset_y": 500.0,
        "animated": True,
    }


def test_public_controller_scroll_to_offset_uses_effect_lane() -> None:
    controller = ListController()
    runtime = Runtime(
        lambda: _list(
            controller=controller,
            render_item=lambda item, index: Text(
                text=str(item),
                content_description=f"public-item-{item}",
                on_click=lambda event: controller.scroll_to_offset(
                    250,
                    animated=False,
                ),
            ),
        ),
        transport=MemoryTransport(),
    )
    runtime.mount()
    item = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if node.kind == "Text" and "click" in node.listeners
    )
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": 1,
            "target": item.id,
            "event": "click",
            "handler": item.listeners["click"],
            "payload": {},
        }
    )

    assert runtime.latest_commit["ops"][-1]["op"] == "scroll_to"
    assert runtime.latest_commit["ops"][-1]["offset_y"] == 250.0
    assert "public-item-25" in _texts(runtime)


def test_public_list_preserves_keyed_items_during_reorder() -> None:
    controls = {}

    def app():
        data = state(tuple(range(10)))
        controls["data"] = data
        return _list(data=data.value)

    runtime = Runtime(app, transport=MemoryTransport())
    runtime.mount()
    before = _texts(runtime)

    controls["data"].set((4, 3, 2, 1, 0, 5, 6, 7, 8, 9))

    after = _texts(runtime)
    assert set(after) == {f"public-item-{index}" for index in range(10)}
    for index in range(10):
        description = f"public-item-{index}"
        assert after[description] == before[description]


def test_owned_controller_state_follows_keyed_list_reorder() -> None:
    controls = {}

    def list_for(name):
        return List(
            tuple(range(100 if name == "a" else 5)),
            render_item=lambda item, index: Text(
                text=f"{name}{item}",
                content_description=f"{name}-item-{item}",
            ),
            key_for_item=lambda item, index: (name, item),
            item_extent=10,
            axis="vertical",
            key=name,
            height=100,
            content_description=f"list-{name}",
        )

    def app():
        order = state(("a", "b"))
        controls["order"] = order
        return Column(*(list_for(name) for name in order.value))

    runtime = Runtime(app, transport=MemoryTransport())
    runtime.mount()
    list_a = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if node.props.get("content_description") == "list-a"
    )
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": 1,
            "target": list_a.id,
            "event": "scroll_metrics",
            "handler": list_a.listeners["scroll_metrics"],
            "payload": _metrics(axis="vertical", offset=500),
        }
    )
    assert "a-item-50" in _texts(runtime)

    controls["order"].set(("b", "a"))

    descriptions = set(_texts(runtime))
    assert "a-item-50" in descriptions
    assert "a-item-0" not in descriptions
    assert {f"b-item-{index}" for index in range(5)} <= descriptions


def test_item_extent_change_replans_from_accepted_viewport() -> None:
    controls = {}

    def app():
        item_extent = state(10)
        controls["item_extent"] = item_extent
        return List(
            tuple(range(100)),
            render_item=lambda item, index: Text(
                text=str(item),
                content_description=f"geometry-item-{item}",
            ),
            key_for_item=lambda item, index: item,
            item_extent=item_extent.value,
            axis="vertical",
            height=100,
        )

    runtime = Runtime(app, transport=MemoryTransport())
    runtime.mount()
    _emit_metrics(runtime, axis="vertical", offset=500)
    assert "geometry-item-50" in _texts(runtime)

    controls["item_extent"].set(100)

    assert set(_texts(runtime)) == {
        "geometry-item-4",
        "geometry-item-5",
        "geometry-item-6",
    }


def test_axis_change_resets_to_initial_window() -> None:
    controls = {}

    def app():
        axis = state("vertical")
        controls["axis"] = axis
        return List(
            tuple(range(100)),
            render_item=lambda item, index: Text(
                text=str(item),
                content_description=f"axis-item-{item}",
            ),
            key_for_item=lambda item, index: item,
            item_extent=10,
            axis=axis.value,
            width=100,
            height=100,
        )

    runtime = Runtime(app, transport=MemoryTransport())
    runtime.mount()
    _emit_metrics(runtime, axis="vertical", offset=500)
    assert "axis-item-50" in _texts(runtime)

    controls["axis"].set("horizontal")

    scroll = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if "scroll_metrics" in node.listeners
    )
    assert scroll.kind == "HorizontalScroll"
    assert set(_texts(runtime)) == {f"axis-item-{index}" for index in range(20)}


def test_empty_and_short_public_lists_mount_without_extra_cells() -> None:
    empty = Runtime(lambda: _list(data=()), transport=MemoryTransport())
    empty.mount()
    assert not [
        node
        for node in empty._coordinator.accepted_index.values()
        if node.kind == "Text"
    ]

    short = Runtime(lambda: _list(data=(0, 1)), transport=MemoryTransport())
    short.mount()
    assert set(_texts(short)) == {"public-item-0", "public-item-1"}


def test_public_list_rejects_bad_inputs_and_duplicate_keys() -> None:
    with pytest.raises(TypeError, match="Sequence"):
        _list(data={"bad": "mapping"})
    with pytest.raises(TypeError, match="render_item"):
        _list(render_item=3)

    duplicate = Runtime(
        lambda: List(
            ("a", "b"),
            render_item=lambda item, index: Text(text=item),
            key_for_item=lambda item, index: "same",
            item_extent=10,
            axis="vertical",
        ),
        transport=MemoryTransport(),
    )
    duplicate.mount()
    assert duplicate._coordinator.accepted_root is None
    assert "Duplicate list key" in str(duplicate.latest_commit)


def test_omitted_key_for_item_defaults_to_item_index() -> None:
    rendered: list[tuple[int, int]] = []

    def render_item(item, index):
        rendered.append((item, index))
        return Text(text=str(item))

    runtime = Runtime(
        lambda: List(
            ("a", "b", "c"),
            render_item=render_item,
            item_extent=10,
            width=100,
            height=100,
        ),
        transport=MemoryTransport(),
    )
    runtime.mount()

    assert rendered == [("a", 0), ("b", 1), ("c", 2)]
    # The whole (tiny) list mounts; index-keyed cells render by position.
    assert {
        n.props["text"]
        for n in runtime._coordinator.accepted_index.values()
        if n.kind == "Text"
    } == {"a", "b", "c"}


def test_max_render_ahead_caps_the_projected_window() -> None:
    rendered: list[int] = []

    def render_item(item, index):
        rendered.append(index)
        return Text(text=str(item))

    runtime = Runtime(
        lambda: List(
            tuple(range(1000)),
            render_item=render_item,
            item_extent=10,
            overscan=1,
            max_render_ahead_viewports=3,
            width=300,
            height=100,
        ),
        transport=MemoryTransport(),
    )
    runtime.mount()
    rendered.clear()
    _emit_projected_scroll(runtime, offset=0, projected=5000)

    # A projection 5000dp away is capped to 3 viewports ahead of the actual
    # viewport: span [0 .. 0 + 3*100 + overscan] = [0 .. 500) = 50 items.
    assert min(rendered) == 0
    assert max(rendered) == 49
    assert len(rendered) == 50


def test_public_list_validation_for_new_defaults() -> None:
    with pytest.raises(TypeError, match="overscan"):
        List(
            (1, 2),
            render_item=lambda item, index: Text(text=str(item)),
            item_extent=10,
            overscan="wide",
        )
    with pytest.raises(TypeError, match="max_render_ahead"):
        List(
            (1, 2),
            render_item=lambda item, index: Text(text=str(item)),
            item_extent=10,
            max_render_ahead_viewports="far",
        )
    with pytest.raises(TypeError, match="key_for_item"):
        List(
            (1, 2),
            render_item=lambda item, index: Text(text=str(item)),
            item_extent=10,
            key_for_item=3,
        )


def test_public_list_validates_numeric_domains_eagerly() -> None:
    """Domain errors raise at the ``List(...)`` call, before any mount.

    A valid value renders normally; every invalid value below raises directly
    instead of producing a runtime mount with ``accepted_root=None``.
    """

    def list_with(**kwargs):
        item_extent = kwargs.pop("item_extent", 10)
        return List(
            (1, 2),
            render_item=lambda item, index: Text(text=str(item)),
            item_extent=item_extent,
            **kwargs,
        )

    # item_extent: finite and at least 1 logical unit.
    with pytest.raises(ValueError, match="item_extent"):
        list_with(item_extent=0)
    with pytest.raises(ValueError, match="item_extent"):
        list_with(item_extent=0.5)
    with pytest.raises(ValueError, match="finite"):
        list_with(item_extent=float("nan"))
    with pytest.raises(ValueError, match="finite"):
        list_with(item_extent=float("inf"))
    with pytest.raises(TypeError, match="item_extent"):
        list_with(item_extent=True)

    # overscan: finite and non-negative.
    with pytest.raises(ValueError, match="overscan"):
        list_with(overscan=-1)
    with pytest.raises(ValueError, match="overscan"):
        list_with(overscan=float("inf"))
    with pytest.raises(TypeError, match="overscan"):
        list_with(overscan=True)

    # max_render_ahead_viewports: finite and non-negative.
    with pytest.raises(ValueError, match="max_render_ahead"):
        list_with(max_render_ahead_viewports=-1)
    with pytest.raises(ValueError, match="max_render_ahead"):
        list_with(max_render_ahead_viewports=float("nan"))
    with pytest.raises(TypeError, match="max_render_ahead"):
        list_with(max_render_ahead_viewports=True)

    # A zero overscan and zero render-ahead remain valid: the same inputs
    # mount with a real accepted root instead of raising.
    valid = Runtime(
        lambda: List(
            (1, 2),
            render_item=lambda item, index: Text(text=str(item)),
            item_extent=10,
            overscan=0,
            max_render_ahead_viewports=0,
        ),
        transport=MemoryTransport(),
    )
    valid.mount()
    assert valid._coordinator.accepted_root is not None


def test_default_render_ahead_is_bounded() -> None:
    rendered: list[int] = []

    def render_item(item, index):
        rendered.append(index)
        return Text(text=str(item))

    runtime = Runtime(
        lambda: List(
            tuple(range(1000)),
            render_item=render_item,
            item_extent=10,
            overscan=0,
            width=300,
            height=100,
        ),
        transport=MemoryTransport(),
    )
    runtime.mount()
    rendered.clear()
    _emit_projected_scroll(runtime, offset=0, projected=5000)

    # Default (bounded, 3 viewports): the projection 5000dp away is clamped
    # to the current viewport plus 3*100dp, so only the near path mounts.
    assert min(rendered) == 0
    assert max(rendered) == 39
    assert len(rendered) == 40


def test_explicit_zero_render_ahead_is_unbounded() -> None:
    rendered: list[int] = []

    def render_item(item, index):
        rendered.append(index)
        return Text(text=str(item))

    runtime = Runtime(
        lambda: List(
            tuple(range(1000)),
            render_item=render_item,
            item_extent=10,
            overscan=0,
            max_render_ahead_viewports=0,
            width=300,
            height=100,
        ),
        transport=MemoryTransport(),
    )
    runtime.mount()
    rendered.clear()
    _emit_projected_scroll(runtime, offset=0, projected=5000)

    # Explicit 0 keeps the opt-in unbounded projection: the full path to the
    # projected landing is mounted in one commit.
    assert len(rendered) > 400


def test_max_render_ahead_caps_reverse_projection() -> None:
    rendered: list[int] = []

    def render_item(item, index):
        rendered.append(index)
        return Text(text=str(item))

    runtime = Runtime(
        lambda: List(
            tuple(range(1000)),
            render_item=render_item,
            item_extent=10,
            overscan=0,
            max_render_ahead_viewports=3,
            width=300,
            height=100,
        ),
        transport=MemoryTransport(),
    )
    runtime.mount()
    # Move the window deep into the list first (no projection divergence).
    _emit_projected_scroll(runtime, offset=900, projected=900)
    rendered.clear()

    # Reverse fling from deep toward the top: the projected landing is 0 but
    # the cap must bound the backward reach to 3 viewports behind the actual
    # viewport (offset 900 -> 600), not mount items 0..100.
    _emit_projected_scroll(runtime, offset=900, projected=0, velocity=-10000)

    assert min(rendered) >= 60
    assert max(rendered) <= 100
    assert len(rendered) <= 40


def test_large_public_list_computes_keys_only_for_realized_cells() -> None:
    key_calls: list[int] = []

    def key_for_item(item, index):
        key_calls.append(index)
        return index

    runtime = Runtime(
        lambda: List(
            tuple(range(1_000_000)),
            render_item=lambda item, index: Text(text=str(item)),
            key_for_item=key_for_item,
            item_extent=10,
            width=300,
            height=100,
        ),
        transport=MemoryTransport(),
    )
    runtime.mount()

    # A million-item list computes keys only for the realized window, never
    # the full sequence.
    assert len(runtime._coordinator.accepted_index) < 200
    assert max(key_calls) < 50
    assert len(key_calls) < 50


def test_duplicate_key_across_windows_rejects_and_preserves_tree() -> None:
    def key_for_item(item, index):
        return index % 100

    runtime = Runtime(
        lambda: List(
            tuple(range(1000)),
            render_item=lambda item, index: Text(
                text=str(item),
                content_description=f"dup-item-{item}",
            ),
            key_for_item=key_for_item,
            item_extent=10,
            overscan=0,
            width=300,
            height=100,
        ),
        transport=MemoryTransport(),
    )
    runtime.mount()
    initial = _texts(runtime)
    assert "dup-item-0" in initial

    # Scrolling to item 100 re-realizes key 0 (index % 100) at a different
    # index. The per-list registry must reject the duplicate instead of
    # reusing the first cell's node and state.
    _emit_metrics(runtime, axis="vertical", offset=1000)

    assert "Duplicate list key" in (runtime._last_error or "")
    assert _texts(runtime) == initial
    assert "dup-item-100" not in _texts(runtime)


def test_data_replacement_resets_registry_for_reorder() -> None:
    controls = {}

    def app():
        data = state(tuple(range(200)))
        controls["data"] = data
        return List(
            data.value,
            render_item=lambda item, index: Text(
                text=str(item),
                content_description=f"reset-item-{item}",
            ),
            key_for_item=lambda item, index: item,
            item_extent=10,
            overscan=0,
            width=300,
            height=100,
        )

    runtime = Runtime(app, transport=MemoryTransport())
    runtime.mount()
    _emit_metrics(runtime, axis="vertical", offset=1500)
    assert "reset-item-150" in _texts(runtime)

    # A new state-derived sequence is a new data object, so the registry
    # resets: the same keys at different indices are a valid reorder, not a
    # false duplicate.
    controls["data"].set(tuple(range(150)) + tuple(reversed(range(150, 200))))

    window = set(_texts(runtime))
    assert "reset-item-199" in window
    assert "reset-item-190" in window
    assert runtime._last_error is None


def test_in_place_shrink_replans_and_drops_stale_cells() -> None:
    data = list(range(1000))
    runtime = Runtime(
        lambda: List(
            data,
            render_item=lambda item, index: Text(
                text=str(item),
                content_description=f"shrink-item-{item}",
            ),
            key_for_item=lambda item, index: item,
            item_extent=10,
            overscan=1,
            width=300,
            height=100,
        ),
        transport=MemoryTransport(),
    )
    runtime.mount()
    _emit_metrics(runtime, axis="vertical", offset=500)
    assert "shrink-item-50" in _texts(runtime)

    # Shrink the mutable sequence in place, then a metrics event must replan
    # because the accepted mask is stale beyond the new item count.
    del data[6:]
    _emit_metrics(runtime, axis="vertical", offset=500)

    assert set(_texts(runtime)) == {f"shrink-item-{index}" for index in range(6)}


def test_in_place_shrink_to_empty_drops_all_cells() -> None:
    data = list(range(100))
    runtime = Runtime(
        lambda: List(
            data,
            render_item=lambda item, index: Text(
                text=str(item),
                content_description=f"empty-item-{item}",
            ),
            key_for_item=lambda item, index: item,
            item_extent=10,
            overscan=1,
            width=300,
            height=100,
        ),
        transport=MemoryTransport(),
    )
    runtime.mount()
    _emit_metrics(runtime, axis="vertical", offset=300)
    assert "empty-item-30" in _texts(runtime)

    data.clear()
    _emit_metrics(runtime, axis="vertical", offset=300)

    assert not _texts(runtime)
    assert runtime._last_error is None


def test_out_of_range_offset_after_shrink_realizes_end_window() -> None:
    """A metrics offset beyond the shrunken content end must be treated as
    the clamped end window, not skipped as an already-covered empty span."""
    data = list(range(1000))
    runtime = Runtime(
        lambda: List(
            data,
            render_item=lambda item, index: Text(
                text=str(item),
                content_description=f"end-window-item-{item}",
            ),
            key_for_item=lambda item, index: item,
            item_extent=10,
            overscan=0,
            width=300,
            height=100,
        ),
        transport=MemoryTransport(),
    )
    runtime.mount()
    _emit_metrics(runtime, axis="vertical", offset=850)
    assert "end-window-item-85" in _texts(runtime)
    assert "end-window-item-94" in _texts(runtime)
    assert "end-window-item-95" not in _texts(runtime)

    # Shrink the sequence in place to 100 items (total 1000, max scroll 900)
    # while the accepted window still covers items 85..95.
    del data[100:]

    # An out-of-range offset (1000 >= content end) must still replan to the
    # clamped end window instead of vacuous-skipping on an empty span.
    _emit_metrics(runtime, axis="vertical", offset=1000)

    assert "end-window-item-90" in _texts(runtime)
    assert "end-window-item-99" in _texts(runtime)
    assert "end-window-item-85" not in _texts(runtime)
    assert runtime._last_error is None


# ---------------------------------------------------------------------------
# M4 — one public controller for both components
# ---------------------------------------------------------------------------


def test_list_controller_scroll_to_key_default_index_keys() -> None:
    """A plain Sequence with default index keys resolves keys in O(1)."""
    controller = ListController()

    def app():
        return Column(
            _list(controller=controller),
            Text(
                text="key",
                content_description="list-key-jump",
                on_click=lambda event: controller.scroll_to_key(
                    5, alignment="start", animated=False
                ),
            ),
        )

    runtime = Runtime(app, transport=MemoryTransport())
    runtime.mount()
    button = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if node.props.get("content_description") == "list-key-jump"
    )
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": 1,
            "target": button.id,
            "event": "click",
            "handler": button.listeners["click"],
            "payload": {},
        }
    )

    assert runtime.latest_commit["ops"][-1]["op"] == "scroll_to"
    assert runtime.latest_commit["ops"][-1]["offset_y"] == 50.0


def test_list_controller_scroll_to_key_realized_custom_key() -> None:
    """An explicit key callback consults the accepted registry, no scan."""
    controller = ListController()
    key_calls: list[int] = []

    def key_for_item(item, index):
        key_calls.append(index)
        return item

    def app():
        return Column(
            List(
                tuple(range(1000)),
                render_item=lambda item, index: Text(
                    text=str(item),
                    content_description=f"key-list-{item}",
                    on_click=lambda event: controller.scroll_to_key(
                        5, alignment="start", animated=False
                    ),
                ),
                key_for_item=key_for_item,
                item_extent=10,
                axis="vertical",
                controller=controller,
                width=300,
                height=100,
            )
        )

    runtime = Runtime(app, transport=MemoryTransport())
    runtime.mount()
    cell = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if node.kind == "Text" and "click" in node.listeners
    )
    calls_before = len(key_calls)
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": 1,
            "target": cell.id,
            "event": "click",
            "handler": cell.listeners["click"],
            "payload": {},
        }
    )

    assert runtime.latest_commit["ops"][-1]["offset_y"] == 50.0
    # Resolution came from the accepted registry; the re-render read only
    # the new realized window (far less than the 1000-item source).
    assert len(key_calls) < 100


def test_list_controller_scroll_to_key_unknown_raises() -> None:
    controller = ListController()
    error = {}

    def app():
        return Column(
            _list(
                controller=controller,
                render_item=lambda item, index: Text(
                    text=str(item),
                    content_description=f"unknown-key-{item}",
                    on_click=lambda event: controller.scroll_to_key(
                        900, alignment="start", animated=False
                    ),
                ),
            ),
        )

    runtime = Runtime(app, transport=MemoryTransport())
    runtime.mount()
    cell = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if node.kind == "Text" and "click" in node.listeners
    )
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": 1,
            "target": cell.id,
            "event": "click",
            "handler": cell.listeners["click"],
            "payload": {},
        }
    )
    assert "not realized" in runtime._last_error
    assert not error


def test_single_controller_reused_across_fixed_and_generic_lists() -> None:
    """One ListController drives a List and then a VirtualList (cross-kind)."""
    from vyne.lists import FixedLinearLayout, VirtualList

    controller = ListController()
    fixed_first = {"node": None}

    def app():
        show_generic = state(False)
        fixed_first["setter"] = show_generic
        if show_generic.value:
            return VirtualList(
                tuple(range(1000)),
                render_item=lambda item, index: Text(
                    text=str(item),
                    content_description=f"g-{item}",
                    on_click=lambda event: controller.scroll_to_index(
                        50, alignment="start", animated=False
                    ),
                ),
                layout=FixedLinearLayout(10, "vertical"),
                key_for_item=lambda item, index: item,
                controller=controller,
                width=300,
                height=100,
            )
        return _list(
            controller=controller,
            render_item=lambda item, index: Text(
                text=str(item),
                content_description=f"f-{item}",
            ),
        )

    runtime = Runtime(app, transport=MemoryTransport())
    runtime.mount()
    assert controller._fixed.is_mounted
    assert not controller._generic.is_mounted

    # Swap the same controller to the generic list: the fixed engine unbinds
    # and the generic engine binds.
    fixed_first["setter"].set(True)
    assert not controller._fixed.is_mounted
    assert controller._generic.is_mounted
    assert controller._generic._scroll_ref.current.kind == "Scroll"

    # The command dispatches to the generic engine.
    cell = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if node.kind == "Text" and "click" in node.listeners
    )
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": 1,
            "target": cell.id,
            "event": "click",
            "handler": cell.listeners["click"],
            "payload": {},
        }
    )
    assert runtime.latest_commit["ops"][-1]["op"] == "scroll_to"
    assert runtime.latest_commit["ops"][-1]["offset_y"] == 500.0


def test_controller_bound_to_two_lists_raises_clearly() -> None:
    """A controller bound to a List and a VirtualList in one tree raises."""
    from vyne.lists import FixedLinearLayout, VirtualList

    controller = ListController()

    def app():
        return Column(
            _list(
                controller=controller,
                render_item=lambda item, index: Text(
                    text=str(item),
                    content_description=f"both-f-{item}",
                ),
            ),
            VirtualList(
                tuple(range(100)),
                render_item=lambda item, index: Text(
                    text=str(item),
                    content_description=f"both-g-{item}",
                    on_click=lambda event: controller.scroll_to_offset(
                        10, animated=False
                    ),
                ),
                layout=FixedLinearLayout(10, "vertical"),
                key_for_item=lambda item, index: item,
                controller=controller,
                width=300,
                height=100,
            ),
        )

    runtime = Runtime(app, transport=MemoryTransport())
    runtime.mount()
    cell = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if node.kind == "Text" and "click" in node.listeners
    )
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": 1,
            "target": cell.id,
            "event": "click",
            "handler": cell.listeners["click"],
            "payload": {},
        }
    )
    assert "more than one mounted list" in runtime._last_error


def test_unmounted_controller_raises() -> None:
    controller = ListController()
    with pytest.raises(RuntimeError, match="not mounted"):
        controller.scroll_to_offset(10, animated=False)
    with pytest.raises(RuntimeError, match="not mounted"):
        controller.scroll_to_index(5, alignment="start", animated=False)
    with pytest.raises(RuntimeError, match="not mounted"):
        controller.scroll_to_key(5, alignment="start", animated=False)


def test_list_stays_on_fixed_path_without_generic_sentinel() -> None:
    """List keeps the fixed planner: no generic extent sentinel or FrameLayout
    content Box in its tree, and it mounts through the fixed engine."""
    controller = ListController()
    runtime = Runtime(
        lambda: _list(controller=controller),
        transport=MemoryTransport(),
    )
    runtime.mount()

    keys = {
        node.key
        for node in runtime._coordinator.accepted_index.values()
        if node.key is not None
    }
    assert ("__vyne_virtual_extent__",) not in keys
    assert ("__vyne_virtual_content__",) not in keys
    assert ("__vyne_list_content__",) in keys
    assert controller._fixed.is_mounted
    assert not controller._generic.is_mounted
    assert "Scroll" in {n.kind for n in runtime._coordinator.accepted_index.values()}
