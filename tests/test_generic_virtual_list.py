"""M2 tests for the generic Python ``VirtualList`` engine.

These tests exercise the public ``vyne.lists.VirtualList`` surface and the
single public ``ListController`` end to end through the real Runtime:
mount, movement, the no-frame coverage path, bounded projection, dynamic
sources, reorder, lazy custom ``VirtualData``, grids, measurement feedback
(keyed dedup, stable-key reorder, anchor preservation), flattened sticky
sections, controller commands, the full binding acceptance/rejection/
unknown-reset/unmount matrix, and failure recovery that preserves the
accepted tree.
"""

from __future__ import annotations

import unittest

from vyne import Column, Text, state
from vyne._lists import (
    VirtualListSpec,
    compose_generic_window,
    render_generic_virtual_list,
)
from vyne.events import latest
from vyne.lists import (
    FixedLinearLayout,
    ListController,
    VirtualData,
    VirtualList,
    VirtualLayout,
)
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport

from tests.support.list_conformance import (
    SectionedLayout,
    StaggeredLayout,
    UniformGridLayout,
    VariableLinearLayout,
)
from tests.support.runtime_helpers import SilentTransport


def _cell(item: int, index: int) -> Text:
    return Text(
        text=str(item),
        content_description=f"item-{item}",
    )


def _fixed_app(
    data=tuple(range(1000)),
    *,
    controller=None,
    axis: str = "vertical",
    item_extent: float = 10,
    layout=None,
    render_item=None,
    **scroll_props,
):
    def app() -> Column:
        data_cell = state(data)
        return Column(
            VirtualList(
                data_cell.value,
                render_item=render_item or _cell,
                layout=layout or FixedLinearLayout(item_extent, axis),
                key_for_item=lambda item, index: item,
                axis=axis,
                controller=controller,
                width=scroll_props.pop("width", 300),
                height=scroll_props.pop("height", 100),
                **scroll_props,
            )
        )

    return app


def _scroll_payload(
    offset: float,
    *,
    extent: float = 100,
    axis: str = "vertical",
    cross_extent: float = 300,
    velocity: float = 0.0,
    projected_offset: float | None = None,
) -> dict:
    projected = offset if projected_offset is None else projected_offset
    if axis == "vertical":
        return {
            "offset_x": 0.0,
            "offset_y": offset,
            "viewport_width": cross_extent,
            "viewport_height": extent,
            "content_width": cross_extent,
            "content_height": 10_000_000.0,
            "velocity_x": 0.0,
            "velocity_y": velocity,
            "projected_offset_x": 0.0,
            "projected_offset_y": projected,
            "event_time": 10,
        }
    return {
        "offset_x": offset,
        "offset_y": 0.0,
        "viewport_width": extent,
        "viewport_height": cross_extent,
        "content_width": 10_000_000.0,
        "content_height": cross_extent,
        "velocity_x": velocity,
        "velocity_y": 0.0,
        "projected_offset_x": projected,
        "projected_offset_y": 0.0,
        "event_time": 10,
    }


def _emit_scroll(
    runtime: Runtime,
    *,
    offset: float,
    seq: int = 1,
    axis: str = "vertical",
    extent: float = 100,
    cross_extent: float = 300,
    velocity: float = 0.0,
    projected_offset: float | None = None,
) -> None:
    scroll = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if "scroll_metrics" in node.listeners
    )
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": seq,
            "target": scroll.id,
            "event": "scroll_metrics",
            "handler": scroll.listeners["scroll_metrics"],
            "payload": _scroll_payload(
                offset,
                extent=extent,
                axis=axis,
                cross_extent=cross_extent,
                velocity=velocity,
                projected_offset=projected_offset,
            ),
        }
    )


def _emit_layout(
    runtime: Runtime,
    key: object,
    *,
    width: float,
    height: float,
    seq: int = 1,
) -> None:
    cell = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if node.kind == "Box"
        and node.key is not None
        and node.key[0] == "__vyne_virtual_cell__"
        and node.key[1] == key
    )
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": seq,
            "target": cell.id,
            "event": "layout_metrics",
            "handler": cell.listeners["layout_metrics"],
            "payload": {
                "x": 0.0,
                "y": 0.0,
                "width": width,
                "height": height,
            },
        }
    )


def _cell_keys(runtime: Runtime) -> set:
    return {
        node.key[1]
        for node in runtime._coordinator.accepted_index.values()
        if node.kind == "Box"
        and node.key is not None
        and node.key[0] == "__vyne_virtual_cell__"
    }


def _cell_props(runtime: Runtime, key: object) -> dict:
    return next(
        node.props
        for node in runtime._coordinator.accepted_index.values()
        if node.kind == "Box"
        and node.key is not None
        and node.key[0] == "__vyne_virtual_cell__"
        and node.key[1] == key
    )


def _scroll_ops(runtime: Runtime) -> list[dict]:
    commit = runtime.latest_commit
    if commit is None:
        return []
    return [op for op in commit.get("ops", []) if op.get("op") == "scroll_to"]


class _CountingSource:
    """Custom lazy VirtualData source with access counters."""

    def __init__(self, items):
        self._items = items
        self.key_accesses = 0
        self.item_accesses = 0

    @property
    def item_count(self) -> int:
        return len(self._items)

    def item_at(self, index):
        self.item_accesses += 1
        return self._items[index]

    def key_at(self, index):
        self.key_accesses += 1
        return self._items[index]

    def index_for_key(self, key):
        if type(key) is not int or key < 0 or key >= len(self._items):
            return None
        return key


class _BrokenLayout:
    """Fails after the first successful render."""

    def __init__(self) -> None:
        self.renders = 0

    def place(self, request):
        self.renders += 1
        if self.renders > 1:
            raise RuntimeError("layout exploded")
        return FixedLinearLayout(10, "vertical").place(request)

    def offset_for_index(self, index, *, measurement_for_index):
        return (0.0, float(index) * 10.0)


# ---------------------------------------------------------------------------
# Public surface and validation
# ---------------------------------------------------------------------------


class VirtualListPublicSurfaceTests(unittest.TestCase):
    def test_imports_and_signatures(self) -> None:
        self.assertEqual(VirtualList.__module__, "vyne.lists")
        import vyne.lists as lists_module

        self.assertIs(lists_module.VirtualList, VirtualList)
        self.assertIs(lists_module.ListController, ListController)
        self.assertFalse(hasattr(lists_module, "VirtualListController"))
        # The public controller owns the private generic engine; the engine
        # stays private to the facade.
        import vyne._lists.generic as generic_engine

        controller = ListController()
        self.assertIsInstance(controller._generic, generic_engine.GenericVirtualListController)
        import inspect

        sig = inspect.signature(VirtualList)
        params = list(sig.parameters)
        self.assertEqual(params[0], "data")
        self.assertIn("render_item", params)
        self.assertIn("layout", params)
        self.assertIn("key_for_item", params)
        self.assertEqual(sig.parameters["axis"].default, "vertical")
        self.assertEqual(sig.parameters["overscan"].default, 1.0)
        self.assertEqual(sig.parameters["max_render_ahead_viewports"].default, 3.0)
        self.assertEqual(sig.parameters["max_offscreen_items"].default, 64)
        self.assertEqual(sig.parameters["initial_item_count"].default, 5)
        index_sig = inspect.signature(ListController.scroll_to_index)
        self.assertIn("alignment", index_sig.parameters)
        self.assertIn("animated", index_sig.parameters)
        key_sig = inspect.signature(ListController.scroll_to_key)
        self.assertIn("alignment", key_sig.parameters)

    def test_layout_and_data_protocols_are_runtime_checkable(self) -> None:
        self.assertIsInstance(FixedLinearLayout(10), VirtualLayout)
        source = _CountingSource(tuple(range(5)))
        self.assertIsInstance(source, VirtualData)

    def test_validation_rejects_bad_inputs(self) -> None:
        layout = FixedLinearLayout(10)
        with self.assertRaisesRegex(TypeError, "non-string Sequence"):
            VirtualList("abc", render_item=_cell, layout=layout)
        with self.assertRaisesRegex(TypeError, "non-string Sequence"):
            VirtualList(123, render_item=_cell, layout=layout)
        with self.assertRaises(TypeError):
            VirtualList(tuple(range(5)), render_item="not-callable", layout=layout)
        with self.assertRaises(TypeError):
            VirtualList(tuple(range(5)), render_item=_cell, layout=object())
        with self.assertRaisesRegex(TypeError, "own their keys"):
            VirtualList(
                _CountingSource(tuple(range(5))),
                render_item=_cell,
                layout=layout,
                key_for_item=lambda item, index: item,
            )
        with self.assertRaises(ValueError):
            VirtualList(tuple(range(5)), render_item=_cell, layout=layout, axis="diag")
        with self.assertRaises(ValueError):
            VirtualList(
                tuple(range(5)),
                render_item=_cell,
                layout=layout,
                overscan=-1,
            )
        with self.assertRaises(ValueError):
            VirtualList(
                tuple(range(5)),
                render_item=_cell,
                layout=layout,
                max_render_ahead_viewports=-1,
            )
        with self.assertRaises(TypeError):
            VirtualList(
                tuple(range(5)),
                render_item=_cell,
                layout=layout,
                max_offscreen_items=1.5,
            )
        with self.assertRaises(ValueError):
            VirtualList(
                tuple(range(5)),
                render_item=_cell,
                layout=layout,
                max_offscreen_items=-1,
            )
        with self.assertRaises(TypeError):
            VirtualList(
                tuple(range(5)),
                render_item=_cell,
                layout=layout,
                initial_item_count=2.0,
            )
        with self.assertRaises(TypeError):
            VirtualList(
                tuple(range(5)),
                render_item=_cell,
                layout=layout,
                controller=object(),
            )
        with self.assertRaisesRegex(ValueError, "controller owns"):
            VirtualList(
                tuple(range(5)),
                render_item=_cell,
                layout=layout,
                on_scroll_metrics=latest(lambda event: None),
            )
        with self.assertRaisesRegex(ValueError, "controller owns"):
            VirtualList(tuple(range(5)), render_item=_cell, layout=layout, ref=None)

    def test_engine_spec_validation(self) -> None:
        controller = ListController()._generic
        with self.assertRaises(TypeError):
            VirtualListSpec(
                source=_CountingSource(tuple(range(5))),
                controller=object(),
                render_item=lambda item, index, key: Text(text=str(item)),
                layout=FixedLinearLayout(10),
                axis="vertical",
                initial_item_count=5,
                overscan=1.0,
                max_render_ahead_viewports=3.0,
                max_offscreen_items=64,
            )
        with self.assertRaises(ValueError):
            VirtualListSpec(
                source=_CountingSource(tuple(range(5))),
                controller=controller,
                render_item=lambda item, index, key: Text(text=str(item)),
                layout=FixedLinearLayout(10),
                axis="vertical",
                initial_item_count=5,
                overscan=1.0,
                max_render_ahead_viewports=3.0,
                max_offscreen_items=64,
                scroll_props={"on_scroll_metrics": None},
            )
        with self.assertRaises(TypeError):
            VirtualListSpec(
                source=object(),
                controller=controller,
                render_item=lambda item, index, key: Text(text=str(item)),
                layout=FixedLinearLayout(10),
                axis="vertical",
                initial_item_count=5,
                overscan=1.0,
                max_render_ahead_viewports=3.0,
                max_offscreen_items=64,
            )

    def test_reserved_props_are_rejected_by_engine(self) -> None:
        controller = ListController()._generic
        with self.assertRaisesRegex(ValueError, "controller owns"):
            VirtualListSpec(
                source=_CountingSource(tuple(range(5))),
                controller=controller,
                render_item=lambda item, index, key: Text(text=str(item)),
                layout=FixedLinearLayout(10),
                axis="vertical",
                initial_item_count=5,
                overscan=1.0,
                max_render_ahead_viewports=3.0,
                max_offscreen_items=64,
                scroll_props={"ref": None},
            )


# ---------------------------------------------------------------------------
# Fixed-linear engine through the Runtime
# ---------------------------------------------------------------------------


class VirtualListEngineTests(unittest.TestCase):
    def test_mount_uses_declared_viewport(self) -> None:
        runtime = Runtime(_fixed_app(), transport=MemoryTransport())
        runtime.mount()
        self.assertEqual(len(_cell_keys(runtime)), 20)
        content = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Box" and node.key == ("__vyne_virtual_content__",)
        )
        self.assertEqual(content.props["height"], 10_000.0)
        # The declared cross size is retained as a number.
        self.assertEqual(content.props["width"], 300.0)
        self.assertEqual(content.props["_virtual_content_width"], 300.0)
        self.assertEqual(content.props["_virtual_content_height"], 10_000.0)

    def test_content_extent_is_semantic_without_sentinel_child(self) -> None:
        """The content Box publishes host-neutral extent props directly."""
        runtime = Runtime(_fixed_app(), transport=MemoryTransport())
        runtime.mount()
        content = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Box" and node.key == ("__vyne_virtual_content__",)
        )
        self.assertEqual(content.props["_virtual_content_width"], 300.0)
        self.assertEqual(content.props["_virtual_content_height"], 10_000.0)
        self.assertFalse(
            any(
                node.key == ("__vyne_virtual_extent__",)
                for node in runtime._coordinator.accepted_index.values()
            )
        )
        insert_ops = [
            op
            for op in runtime.latest_commit.get("ops", [])
            if op.get("op") == "insert_child" and op.get("parent") == content.id
        ]
        self.assertTrue(insert_ops)
        self.assertEqual(min(op["index"] for op in insert_ops), 0)

    def test_scroll_moves_window(self) -> None:
        runtime = Runtime(_fixed_app(), transport=MemoryTransport())
        runtime.mount()
        _emit_scroll(runtime, offset=500, seq=1)
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(40, 70)},
        )

    def test_scroll_inside_coverage_does_not_commit(self) -> None:
        runtime = Runtime(_fixed_app(), transport=MemoryTransport())
        transport = runtime.transport
        runtime.mount()
        _emit_scroll(runtime, offset=500, seq=1)
        send_count = transport.send_count
        _emit_scroll(runtime, offset=500, seq=2)
        _emit_scroll(runtime, offset=520, seq=3)
        self.assertEqual(transport.send_count, send_count)

    def test_outrunning_coverage_replans(self) -> None:
        runtime = Runtime(_fixed_app(), transport=MemoryTransport())
        runtime.mount()
        _emit_scroll(runtime, offset=500, seq=1)
        _emit_scroll(runtime, offset=5_000, seq=2)
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(490, 520)},
        )

    def test_forward_projection_is_bounded(self) -> None:
        runtime = Runtime(
            _fixed_app(max_render_ahead_viewports=3.0),
            transport=MemoryTransport(),
        )
        runtime.mount()
        _emit_scroll(
            runtime,
            offset=0,
            projected_offset=50_000.0,
            velocity=50_000.0,
            seq=1,
        )
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(0, 50)},
        )

    def test_reverse_projection_is_bounded(self) -> None:
        runtime = Runtime(
            _fixed_app(max_render_ahead_viewports=3.0),
            transport=MemoryTransport(),
        )
        runtime.mount()
        _emit_scroll(
            runtime,
            offset=9_900,
            projected_offset=0.0,
            velocity=-50_000.0,
            seq=1,
        )
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(950, 1000)},
        )

    def test_zero_render_ahead_stays_unbounded(self) -> None:
        controller = ListController()
        runtime = Runtime(
            _fixed_app(max_render_ahead_viewports=0.0, controller=controller),
            transport=MemoryTransport(),
        )
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        _emit_scroll(
            runtime,
            offset=0,
            projected_offset=50_000.0,
            velocity=50_000.0,
            seq=1,
        )
        runtime.acknowledge_native_apply(runtime.revision)
        # With cap 0 the planning viewport reaches the full projection, but
        # it is clamped to the accepted content scroll bounds (content 10,000
        # minus the 100-unit viewport); the layout candidate set still spans
        # the whole fling path.
        self.assertEqual(
            controller._generic._binding.window_state.value.viewport.y,
            9_900.0,
        )
        # The strict offscreen budget (64) still bounds composed cells.
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(0, 74)},
        )

    def test_budget_drop_replans_when_actual_jumps_into_span(self) -> None:
        controller = ListController()
        runtime = Runtime(
            _fixed_app(max_render_ahead_viewports=0.0, controller=controller),
            transport=MemoryTransport(),
        )
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        # Unbounded projection plus a strict offscreen budget: the accepted
        # render clamped the planning viewport to the content end but
        # realized only the 74 cells nearest the actual viewport, so the
        # safe accepted coverage is just the local band around offset 0.
        _emit_scroll(
            runtime,
            offset=0,
            projected_offset=50_000.0,
            velocity=50_000.0,
            seq=1,
        )
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(0, 74)},
        )
        # The actual viewport jumps deep into the projected span.  The
        # realization rect is not safe coverage here, so this must replan
        # and realize the actual cells instead of no-oping blank.
        _emit_scroll(runtime, offset=8_000, seq=2)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(790, 820)},
        )
        # After the replan the whole realization band is mounted again, so
        # ordinary same-window scrolls stay commit-free.
        transport = runtime.transport
        send_count = transport.send_count
        _emit_scroll(runtime, offset=8_000, seq=3)
        _emit_scroll(runtime, offset=8_020, seq=4)
        self.assertEqual(transport.send_count, send_count)

    def test_dynamic_source_replacement(self) -> None:
        replacement = tuple(range(10_000, 11_000))

        def app():
            data_cell = state(tuple(range(1000)))

            def extend(event):
                data_cell.set(replacement)

            return Column(
                VirtualList(
                    data_cell.value,
                    render_item=lambda item, index: Text(
                        text=str(item),
                        content_description=f"item-{item}",
                        on_click=extend,
                    ),
                    layout=FixedLinearLayout(10, "vertical"),
                    key_for_item=lambda item, index: item,
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
        keys = _cell_keys(runtime)
        self.assertEqual(min(keys), 10_000)
        content = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Box" and node.key == ("__vyne_virtual_content__",)
        )
        self.assertEqual(content.props["height"], 10_000.0)

    def test_reorder_keeps_cells_and_state(self) -> None:
        base = tuple(range(100))
        rotated = tuple(range(1, 100)) + (0,)
        counts: dict[int, int] = {}

        def app():
            data_cell = state(base)

            def rotate(event):
                data_cell.set(rotated)

            def count(item, index):
                counts[item] = counts.get(item, 0) + 1

            return Column(
                Text(
                    text="rotate",
                    key="btn",
                    on_click=rotate,
                ),
                VirtualList(
                    data_cell.value,
                    render_item=lambda item, index: Text(
                        text=str(item),
                        content_description=f"item-{item}",
                        on_click=lambda event, item=item: count(item, index),
                    ),
                    layout=FixedLinearLayout(10, "vertical"),
                    key_for_item=lambda item, index: item,
                    width=300,
                    height=100,
                ),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and node.props.get("content_description") == "item-1"
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
        self.assertEqual(counts, {1: 1})
        rotate_cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and node.key == "btn"
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 2,
                "target": rotate_cell.id,
                "event": "click",
                "handler": rotate_cell.listeners["click"],
                "payload": {},
            }
        )
        runtime.acknowledge_native_apply(runtime.revision)
        # The same window now shows the rotated data; key 0 left the window
        # and key 20 entered it, while keys 1-19 stayed mounted.
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(1, 21)},
        )
        cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and node.props.get("content_description") == "item-1"
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 3,
                "target": cell.id,
                "event": "click",
                "handler": cell.listeners["click"],
                "payload": {},
            }
        )
        # The stable key preserved the cell state across the reorder.
        self.assertEqual(counts, {1: 2})

    def test_custom_lazy_source_requires_no_keys_callback(self) -> None:
        source = _CountingSource(tuple(range(1000)))
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    source,
                    render_item=_cell,
                    layout=FixedLinearLayout(10, "vertical"),
                    width=300,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        self.assertGreater(len(_cell_keys(runtime)), 0)
        _emit_scroll(runtime, offset=500, seq=1)
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(40, 70)},
        )
        # Only realized cells were read; the 1000-item source was never
        # scanned or copied.
        self.assertLess(source.key_accesses + source.item_accesses, 500)

    def test_horizontal_mount_and_scroll(self) -> None:
        runtime = Runtime(
            _fixed_app(axis="horizontal", width=100, height=50),
            transport=MemoryTransport(),
        )
        runtime.mount()
        scroll = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if "scroll_metrics" in node.listeners
        )
        self.assertEqual(scroll.kind, "HorizontalScroll")
        _emit_scroll(
            runtime,
            offset=500,
            axis="horizontal",
            extent=100,
            cross_extent=50,
            seq=1,
        )
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(40, 70)},
        )


# ---------------------------------------------------------------------------
# Grids, staggered content, and flattened sections
# ---------------------------------------------------------------------------


class VirtualListLayoutTests(unittest.TestCase):
    def test_grid_composition_positions_and_sizes(self) -> None:
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(1000)),
                    render_item=_cell,
                    layout=UniformGridLayout(columns=2, cell_size=50),
                    key_for_item=lambda item, index: item,
                    width=100,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        keys = sorted(_cell_keys(runtime))
        self.assertEqual(keys, list(range(8)))
        expected = {
            0: (0.0, 0.0),
            1: (50.0, 0.0),
            2: (0.0, 50.0),
            3: (50.0, 50.0),
            4: (0.0, 100.0),
            5: (50.0, 100.0),
            6: (0.0, 150.0),
            7: (50.0, 150.0),
        }
        for key, (x, y) in expected.items():
            props = _cell_props(runtime, key)
            self.assertEqual(props["translation_x"], x)
            self.assertEqual(props["translation_y"], y)
            self.assertEqual(props["width"], 50.0)
            self.assertEqual(props["height"], 50.0)
        content = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Box" and node.key == ("__vyne_virtual_content__",)
        )
        self.assertEqual(content.props["width"], 100.0)
        self.assertEqual(content.props["height"], 25_000.0)

    def test_grid_scroll_moves_rows(self) -> None:
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(1000)),
                    render_item=_cell,
                    layout=UniformGridLayout(columns=2, cell_size=50),
                    key_for_item=lambda item, index: item,
                    width=100,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        _emit_scroll(runtime, offset=250, seq=1)
        self.assertLessEqual(len(_cell_keys(runtime)), 24)
        props = _cell_props(runtime, 10)
        self.assertEqual(props["translation_y"], 250.0)

    def test_staggered_uses_measurements(self) -> None:
        layout = StaggeredLayout(lanes=2, width=100, default_height=50)
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(100)),
                    render_item=_cell,
                    layout=layout,
                    key_for_item=lambda item, index: item,
                    width=200,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        self.assertLessEqual(len(_cell_keys(runtime)), 8)
        _emit_layout(runtime, 0, width=100, height=100, seq=1)
        runtime.acknowledge_native_apply(runtime.revision)
        # The first cell grew; the masonry scan now reports its measured
        # height and the fourth cell lands below it on the first lane.
        props = _cell_props(runtime, 3)
        self.assertEqual(props["translation_y"], 100.0)
        self.assertEqual(props["translation_x"], 0.0)

    def test_section_header_and_footer_retained_together(self) -> None:
        layout = SectionedLayout(
            section_size=8,
            header_extent=30,
            row_extent=20,
            footer_extent=40,
        )
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(30)),
                    render_item=_cell,
                    layout=layout,
                    key_for_item=lambda item, index: item,
                    width=300,
                    height=60,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        _emit_scroll(runtime, offset=300, extent=60, seq=1)
        # The whole active section is realized: its sticky header (10) and
        # footer (19) are retained together with the visible body rows.
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(10, 20)},
        )
        self.assertEqual(_cell_props(runtime, 10)["translation_y"], 230.0)
        self.assertEqual(_cell_props(runtime, 19)["translation_y"], 420.0)

    def test_section_header_beyond_actual_is_mounted_via_realization_boundary(
        self,
    ) -> None:
        # Reviewer regression: at offset 230 the section-0 header (key 0)
        # lies above the actual viewport but its boundary interval [0, 230)
        # intersects the realization viewport, so the layout returns it and
        # the filter retains it.  Moving to 190 (inside the accepted
        # coverage) is therefore a no-frame scroll: the header stays mounted
        # without a commit.
        layout = SectionedLayout(
            section_size=8,
            header_extent=30,
            row_extent=20,
            footer_extent=40,
        )
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(30)),
                    render_item=_cell,
                    layout=layout,
                    key_for_item=lambda item, index: item,
                    width=300,
                    height=60,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        _emit_scroll(runtime, offset=230, extent=60, seq=1)
        self.assertIn(0, _cell_keys(runtime))
        self.assertEqual(_cell_props(runtime, 0)["translation_y"], 0.0)

        send_count = runtime.transport.send_count
        _emit_scroll(runtime, offset=190, extent=60, seq=2)
        # The accepted coverage at offset 230 (realization [170, 350)) still
        # contains the actual viewport [190, 250), so no commit happens and
        # the header stays mounted.
        self.assertEqual(runtime.transport.send_count, send_count)
        self.assertIn(0, _cell_keys(runtime))

    def test_cross_axis_nested_lists_mount_and_scroll_independently(self) -> None:
        """A cell may contain another VirtualList with independent identity,
        viewport state, and controller.  Cross-axis nesting (outer vertical,
        inner horizontal) is the documented first supported target."""

        def inner_rows(item: int) -> Element:
            return Column(
                VirtualList(
                    tuple(range(20)),
                    render_item=lambda inner_item, inner_index: Text(
                        text=f"{item}-{inner_item}",
                        content_description=f"cell-{item}-{inner_item}",
                    ),
                    layout=FixedLinearLayout(10, "horizontal"),
                    key_for_item=lambda inner_item, inner_index, item=item: (
                        item,
                        inner_item,
                    ),
                    axis="horizontal",
                    width=100,
                    height=10,
                )
            )

        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(50)),
                    render_item=lambda item, index: inner_rows(item),
                    layout=FixedLinearLayout(20, "vertical"),
                    key_for_item=lambda item, index: item,
                    width=300,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        # One outer vertical Scroll host; every realized outer cell mounts an
        # inner horizontal list (cells 0..9 at mount, so 10 inner hosts).
        outer_scrolls = [
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Scroll"
        ]
        inner_scrolls = [
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "HorizontalScroll"
        ]
        self.assertEqual(len(outer_scrolls), 1)
        self.assertEqual(len(inner_scrolls), 10)

        outer_keys = sorted(
            key for key in _cell_keys(runtime) if isinstance(key, int)
        )
        self.assertEqual(outer_keys, list(range(0, 10)))
        inner_keys = [
            key for key in _cell_keys(runtime) if isinstance(key, tuple)
        ]
        # Each inner list realizes its full 20-item horizontal window.
        self.assertEqual(len(inner_keys), 10 * 20)
        for outer_item in range(10):
            self.assertTrue(
                {(outer_item, i) for i in range(20)} <= set(inner_keys)
            )

        # The outer list scrolls its own window (offset 300 -> the window
        # leaves the accepted [0, 200) coverage and replans to items 10..24)
        # while the inner lists keep independent viewport state.
        outer = outer_scrolls[0]
        runtime.dispatch_event({
            "type": "event",
            "seq": 1,
            "target": outer.id,
            "event": "scroll_metrics",
            "handler": outer.listeners["scroll_metrics"],
            "payload": _scroll_payload(300),
        })
        outer_keys = sorted(
            key for key in _cell_keys(runtime) if isinstance(key, int)
        )
        self.assertNotIn(0, outer_keys)
        self.assertGreaterEqual(outer_keys[0], 10)
        self.assertIn(24, outer_keys)
        # Each realized outer cell mounts an inner horizontal list, so the
        # inner hosts follow the new outer window.
        self.assertEqual(
            len([
                node
                for node in runtime._coordinator.accepted_index.values()
                if node.kind == "HorizontalScroll"
            ]),
            len(outer_keys),
        )


# ---------------------------------------------------------------------------
# Measurement feedback
# ---------------------------------------------------------------------------


class VirtualListMeasurementTests(unittest.TestCase):
    def test_identical_measurement_is_noop(self) -> None:
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(20)),
                    render_item=_cell,
                    layout=VariableLinearLayout(default_extent=50),
                    key_for_item=lambda item, index: item,
                    width=300,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        transport = runtime.transport
        runtime.mount()
        _emit_layout(runtime, 0, width=300, height=50, seq=1)
        send_count = transport.send_count
        _emit_layout(runtime, 0, width=300, height=50, seq=2)
        self.assertEqual(transport.send_count, send_count)

    def test_invalid_measurement_is_ignored(self) -> None:
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(20)),
                    render_item=_cell,
                    layout=VariableLinearLayout(default_extent=50),
                    key_for_item=lambda item, index: item,
                    width=300,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        transport = runtime.transport
        runtime.mount()
        send_count = transport.send_count
        cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Box"
            and node.key is not None
            and node.key[0] == "__vyne_virtual_cell__"
            and node.key[1] == 0
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 1,
                "target": cell.id,
                "event": "layout_metrics",
                "handler": cell.listeners["layout_metrics"],
                "payload": {"x": 0.0, "y": 0.0, "width": -5.0, "height": 50.0},
            }
        )
        self.assertEqual(transport.send_count, send_count)

    def test_measurement_follows_stable_key_across_reorder(self) -> None:
        controller = ListController()
        base = tuple(range(20))
        rotated = tuple(range(1, 20)) + (0,)

        def app():
            data_cell = state(base)

            def rotate(event):
                data_cell.set(rotated)

            return Column(
                VirtualList(
                    data_cell.value,
                    render_item=lambda item, index: Text(
                        text=str(item),
                        content_description=f"item-{item}",
                        on_click=rotate,
                    ),
                    layout=VariableLinearLayout(default_extent=50),
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    width=300,
                    height=100,
                )
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        _emit_layout(runtime, 2, width=300, height=100, seq=1)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(
            controller._generic._binding.window_state.value.measurements.get(2).height,
            100.0,
        )
        rotate_cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and "click" in node.listeners
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 2,
                "target": rotate_cell.id,
                "event": "click",
                "handler": rotate_cell.listeners["click"],
                "payload": {},
            }
        )
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(
            controller._generic._binding.window_state.value.measurements.get(2).height,
            100.0,
        )

    def test_measurement_survives_leave_window_and_return(self) -> None:
        controller = ListController()
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(1000)),
                    render_item=_cell,
                    layout=VariableLinearLayout(default_extent=50),
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    width=300,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        _emit_layout(runtime, 2, width=300, height=120, seq=1)
        runtime.acknowledge_native_apply(runtime.revision)
        # Leave the window far away: key 2 leaves the realized set.
        _emit_scroll(runtime, offset=40_000, seq=2)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertNotIn(2, _cell_keys(runtime))
        # The bounded insertion-order cache retained the off-window measurement.
        self.assertEqual(
            controller._generic._binding.window_state.value.measurements.get(2).height,
            120.0,
        )
        # Returning reuses the cached size without a re-measurement.
        _emit_scroll(runtime, offset=0, seq=3)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertIn(2, _cell_keys(runtime))
        self.assertEqual(
            controller._generic._binding.window_state.value.measurements.get(2).height,
            120.0,
        )

    def test_measurement_cache_retains_measured_keys_across_windows(self) -> None:
        controller = ListController()
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(5000)),
                    render_item=_cell,
                    layout=VariableLinearLayout(default_extent=50),
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    width=300,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        # Measure the initial realized window (keys 0-3), then scroll far
        # away and measure the new window.  The bounded insertion-order cache
        # keeps both sets
        # instead of discarding off-window sizes.
        for key in (0, 1, 2, 3):
            _emit_layout(runtime, key, width=300, height=60, seq=key + 1)
        runtime.acknowledge_native_apply(runtime.revision)
        _emit_scroll(runtime, offset=40_000, seq=10)
        runtime.acknowledge_native_apply(runtime.revision)
        far_keys = sorted(_cell_keys(runtime))
        self.assertTrue(far_keys)
        for index, key in enumerate(far_keys[:3]):
            _emit_layout(runtime, key, width=300, height=60, seq=50 + index)
        runtime.acknowledge_native_apply(runtime.revision)
        cache = controller._generic._binding.window_state.value.measurements
        self.assertIn(0, cache)
        self.assertIn(far_keys[0], cache)
        self.assertEqual(
            len(cache),
            len({0, 1, 2, 3, *far_keys[:3]}),
        )


# ---------------------------------------------------------------------------
# Anchor preservation
# ---------------------------------------------------------------------------


class VirtualListAnchorTests(unittest.TestCase):
    def _anchored_runtime(self, *, offset: float = 500.0):
        controller = ListController()
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(20)),
                    render_item=_cell,
                    layout=VariableLinearLayout(default_extent=50),
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    width=300,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        _emit_scroll(runtime, offset=offset, seq=1)
        runtime.acknowledge_native_apply(runtime.revision)
        return runtime, controller

    def test_measurement_drift_queues_anchor_correction(self) -> None:
        runtime, controller = self._anchored_runtime(offset=500)
        self.assertEqual(
            controller._generic._binding.window_state.value.anchor_index,
            10,
        )
        self.assertEqual(
            controller._generic._binding.window_state.value.anchor_offset,
            500.0,
        )

        _emit_layout(runtime, 8, width=300, height=100, seq=2)

        ops = _scroll_ops(runtime)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["offset_y"], 550.0)
        self.assertEqual(ops[0]["animated"], False)
        self.assertEqual(
            controller._generic._binding.window_state.value.viewport.y,
            550.0,
        )

    def test_fractional_in_cell_viewport_keeps_its_fraction(self) -> None:
        # 475 sits 25 units into item 9; the anchor is item 9 placed at 450.
        runtime, controller = self._anchored_runtime(offset=475)
        self.assertEqual(
            controller._generic._binding.window_state.value.anchor_index,
            9,
        )
        self.assertEqual(
            controller._generic._binding.window_state.value.anchor_offset,
            450.0,
        )

        _emit_layout(runtime, 8, width=300, height=100, seq=2)

        ops = _scroll_ops(runtime)
        self.assertEqual(ops[-1]["offset_y"], 525.0)
        self.assertEqual(
            controller._generic._binding.window_state.value.viewport.y,
            525.0,
        )

    def test_multiple_measurements_coalesce_into_one_target(self) -> None:
        runtime, controller = self._anchored_runtime(offset=500)

        for key, height, seq in ((8, 100, 2), (9, 60, 3)):
            cell = next(
                node
                for node in runtime._coordinator.accepted_index.values()
                if node.kind == "Box"
                and node.key is not None
                and node.key[0] == "__vyne_virtual_cell__"
                and node.key[1] == key
            )
            runtime.dispatch_event(
                {
                    "type": "event",
                    "seq": seq,
                    "target": cell.id,
                    "event": "layout_metrics",
                    "handler": cell.listeners["layout_metrics"],
                    "payload": {
                        "x": 0.0,
                        "y": 0.0,
                        "width": 300.0,
                        "height": height,
                    },
                }
            )
        ops = _scroll_ops(runtime)
        # Each handler recomputes the drift from the latest stored anchor
        # position, so the effects accumulate to the total correction and the
        # last effect in the batch carries it.
        self.assertEqual(ops[-1]["offset_y"], 560.0)
        self.assertEqual(
            controller._generic._binding.window_state.value.viewport.y,
            560.0,
        )

    def test_layouts_without_index_near_reflow_without_correction(self) -> None:
        controller = ListController()
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(100)),
                    render_item=_cell,
                    layout=StaggeredLayout(lanes=2, width=100),
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    width=200,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        _emit_layout(runtime, 0, width=100, height=100, seq=1)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(_scroll_ops(runtime), [])
        # Reflow happened without a scroll correction: the fourth cell now
        # lands below the measured first cell on the first lane.
        self.assertEqual(
            _cell_props(runtime, 3)["translation_y"],
            100.0,
        )
        self.assertEqual(
            _cell_props(runtime, 3)["translation_x"],
            0.0,
        )


class _FixedAnchorLayout:
    """Fixed linear delegate with a configurable optional anchor result."""

    def __init__(self, anchor_result):
        self._inner = FixedLinearLayout(10, "vertical")
        self._anchor_result = anchor_result

    def place(self, request):
        return self._inner.place(request)

    def offset_for_index(self, index, *, measurement_for_index):
        return self._inner.offset_for_index(
            index, measurement_for_index=measurement_for_index
        )

    def index_near_offset(self, offset, *, measurement_for_index):
        return self._anchor_result


class VirtualListAnchorValidationTests(unittest.TestCase):
    def _runtime(self, layout, *, controller=None):
        controller = controller or ListController()
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(1000)),
                    render_item=_cell,
                    layout=layout,
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    width=300,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        return runtime, controller

    def test_index_near_offset_none_disables_anchor(self) -> None:
        runtime, controller = self._runtime(_FixedAnchorLayout(None))
        _emit_scroll(runtime, offset=500, seq=1)
        runtime.acknowledge_native_apply(runtime.revision)
        # None means no anchor; the scroll still replanned normally and the
        # anchor is cleared instead of raising.
        self.assertIsNone(controller._generic._binding.window_state.value.anchor_index)
        self.assertIsNone(controller._generic._binding.window_state.value.anchor_offset)
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(40, 70)},
        )

    def test_malformed_index_near_offset_raises_clear_error(self) -> None:
        for bad, message in (
            (1.5, "must return an integer or None"),
            (10_000, "out-of-range"),
        ):
            with self.subTest(bad=bad):
                runtime, _ = self._runtime(_FixedAnchorLayout(bad))
                _emit_scroll(runtime, offset=500, seq=1)
                self.assertIn(message, runtime._last_error)
                # The accepted tree is preserved.
                self.assertIn(0, _cell_keys(runtime))

    def test_actual_offset_beyond_content_is_clamped_before_anchor(self) -> None:
        runtime, controller = self._runtime(
            _FixedAnchorLayout(990), controller=ListController()
        )
        # The scroll node payload reports 40,000, far past the 10,000-unit
        # content; the engine clamps before resolving the anchor.
        _emit_scroll(runtime, offset=40_000, seq=1)
        runtime.acknowledge_native_apply(runtime.revision)
        state_value = controller._generic._binding.window_state.value
        self.assertEqual(state_value.actual_viewport.y, 9_900.0)
        self.assertEqual(state_value.viewport.y, 9_900.0)
        self.assertEqual(state_value.anchor_index, 990)
        self.assertEqual(state_value.anchor_offset, 9_900.0)


# ---------------------------------------------------------------------------
# Controller commands
# ---------------------------------------------------------------------------


class ListControllerFacadeTests(unittest.TestCase):
    def _runtime(self):
        controller = ListController()
        action = {"name": "none", "index": 0, "alignment": "start"}

        def app():
            def act(event):
                if action["name"] == "offset":
                    controller.scroll_to_offset(
                        500, animated=action.get("animated", False)
                    )
                elif action["name"] == "index":
                    controller.scroll_to_index(
                        action["index"],
                        alignment=action["alignment"],
                        animated=action.get("animated", False),
                    )
                elif action["name"] == "key":
                    controller.scroll_to_key(
                        action["key"],
                        alignment=action["alignment"],
                        animated=action.get("animated", False),
                    )

            return Column(
                VirtualList(
                    tuple(range(1000)),
                    render_item=lambda item, index: Text(
                        text=str(item),
                        content_description=f"item-{item}",
                        on_click=act,
                    ),
                    layout=FixedLinearLayout(10, "vertical"),
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    width=300,
                    height=100,
                )
            )

        runtime = Runtime(app, transport=SilentTransport())
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        _emit_scroll(runtime, offset=0, seq=1)
        runtime.acknowledge_native_apply(runtime.revision)
        return runtime, controller, action

    @staticmethod
    def _click(runtime: Runtime, *, sequence: int) -> None:
        cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and "click" in node.listeners
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": sequence,
                "target": cell.id,
                "event": "click",
                "handler": cell.listeners["click"],
                "payload": {},
            }
        )

    def test_scroll_to_offset_queues_effect_and_realizes_window(self) -> None:
        runtime, _, action = self._runtime()
        action["name"] = "offset"
        self._click(runtime, sequence=2)
        ops = _scroll_ops(runtime)
        self.assertEqual(ops[-1]["op"], "scroll_to")
        self.assertEqual(ops[-1]["offset_y"], 500.0)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(40, 70)},
        )

    def test_scroll_to_index_alignments(self) -> None:
        for index, alignment, expected in (
            (50, "start", 500.0),
            (50, "center", 455.0),
            (50, "end", 410.0),
            (0, "end", 0.0),
        ):
            with self.subTest(index=index, alignment=alignment):
                runtime, _, action = self._runtime()
                action.update(
                    {
                        "name": "index",
                        "index": index,
                        "alignment": alignment,
                    }
                )
                self._click(runtime, sequence=2)
                ops = _scroll_ops(runtime)
                self.assertEqual(ops[-1]["op"], "scroll_to")
                self.assertEqual(ops[-1]["offset_y"], expected)

    def test_scroll_to_index_nearest(self) -> None:
        runtime, _, action = self._runtime()
        _emit_scroll(runtime, offset=400, seq=2)
        runtime.acknowledge_native_apply(runtime.revision)
        action.update(
            {
                "name": "index",
                "index": 50,
                "alignment": "nearest",
            }
        )
        self._click(runtime, sequence=3)
        ops = _scroll_ops(runtime)
        self.assertEqual(ops[-1]["offset_y"], 410.0)

    def test_scroll_to_index_offsets_clamped_to_content_bounds(self) -> None:
        # Explicit start/center/end alignments are clamped to
        # [0, content_extent - viewport_extent] before the effect is
        # queued: index 995 at "start" wants 9950 but the last legal offset
        # is 9900, and end-of-list alignments land exactly on 9900.
        for index, alignment, expected in (
            (995, "start", 9900.0),
            (999, "start", 9900.0),
            (998, "end", 9890.0),
            (999, "end", 9900.0),
            (999, "center", 9900.0),
        ):
            with self.subTest(index=index, alignment=alignment):
                runtime, _, action = self._runtime()
                action.update(
                    {
                        "name": "index",
                        "index": index,
                        "alignment": alignment,
                    }
                )
                self._click(runtime, sequence=2)
                ops = _scroll_ops(runtime)
                self.assertEqual(ops[-1]["op"], "scroll_to")
                self.assertEqual(ops[-1]["offset_y"], expected)

    def test_nearest_uses_accepted_viewport_after_programmatic_scroll(self) -> None:
        # After an accepted non-animated scroll the accepted window state
        # reports the destination, and nearest alignment reads that state
        # instead of a stale controller cache: item 50 is already fully
        # visible at offset 500, so no new scroll is emitted.
        runtime, _, action = self._runtime()
        action["name"] = "offset"
        self._click(runtime, sequence=2)
        runtime.acknowledge_native_apply(runtime.revision)
        ops = _scroll_ops(runtime)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[-1]["offset_y"], 500.0)

        action.update(
            {
                "name": "index",
                "index": 50,
                "alignment": "nearest",
            }
        )
        self._click(runtime, sequence=3)
        self.assertEqual(len(_scroll_ops(runtime)), 1)
        self.assertIsNone(runtime._last_error)

    def test_in_flight_commit_does_not_leak_into_nearest_command(self) -> None:
        # A non-animated jump to 500 is staged but not yet acknowledged; a
        # nearest command issued while that commit is in flight must compute
        # from the last accepted actual viewport (0), where item 5 is
        # already fully visible, not from the un-acked destination (500).
        runtime, _, action = self._runtime()
        action["name"] = "offset"
        self._click(runtime, sequence=2)
        action.update(
            {
                "name": "index",
                "index": 5,
                "alignment": "nearest",
            }
        )
        self._click(runtime, sequence=3)
        # Resolve the in-flight commit: the nearest command was a no-op
        # computed from the accepted viewport (0), so no additional scroll
        # is published.  A nearest computed from the un-acked destination
        # (500) would have deferred a spurious scroll_to 50 here.
        runtime.acknowledge_native_apply(runtime.revision)
        ops = _scroll_ops(runtime)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[-1]["offset_y"], 500.0)
        self.assertIsNone(runtime._last_error)

    def test_in_flight_animated_scroll_keeps_accepted_actual_for_commands(
        self,
    ) -> None:
        # An animated commit stages its planning destination but leaves the
        # accepted actual viewport untouched; a chained command while it is
        # in flight must still compute from that accepted actual viewport.
        runtime, _, action = self._runtime()
        action.update(
            {
                "name": "index",
                "index": 500,
                "alignment": "start",
                "animated": True,
            }
        )
        self._click(runtime, sequence=2)
        action.update(
            {
                "name": "index",
                "index": 50,
                "alignment": "nearest",
                "animated": False,
            }
        )
        self._click(runtime, sequence=3)
        # Item 50 is not visible at the accepted viewport 0, so nearest
        # scrolls it into view instead of assuming the animated destination
        # already reached it.  The effect is deferred while the animated
        # commit is in flight and is published once it resolves.
        runtime.acknowledge_native_apply(runtime.revision)
        ops = _scroll_ops(runtime)
        self.assertEqual(ops[-1]["offset_y"], 410.0)
        self.assertIsNone(runtime._last_error)

    def test_known_rejection_retains_accepted_viewport_for_commands(
        self,
    ) -> None:
        # A rejected commit never promoted its binding: the accepted actual
        # viewport snapshot still reports the pre-command position, and
        # later commands compute from it.
        runtime, controller, action = self._runtime()
        action["name"] = "offset"
        self._click(runtime, sequence=2)
        rejected = runtime.revision
        runtime.report_native_failure(revision=rejected, unknown=False)
        self.assertEqual(controller._generic._binding.actual_viewport.y, 0.0)
        # Item 50 is only visible at the rejected destination; a nearest
        # command must scroll to it from the accepted viewport (0).
        action.update(
            {
                "name": "index",
                "index": 50,
                "alignment": "nearest",
            }
        )
        self._click(runtime, sequence=3)
        ops = _scroll_ops(runtime)
        self.assertEqual(ops[-1]["op"], "scroll_to")
        self.assertEqual(ops[-1]["offset_y"], 410.0)

    def test_no_commit_scroll_updates_physical_observation_for_nearest(
        self,
    ) -> None:
        # A native scroll fully inside the accepted coverage emits no render
        # and no acknowledgement, so the promoted binding snapshot stays
        # stale.  The observed physical viewport still advances, and a
        # nearest command must compute from it instead of the snapshot.
        runtime, controller, action = self._runtime()
        send_count = len(runtime.transport.messages)
        _emit_scroll(runtime, offset=100, seq=2)
        self.assertEqual(len(runtime.transport.messages), send_count)
        self.assertEqual(controller._generic._viewport.y, 100.0)
        self.assertEqual(
            controller._generic._binding.actual_viewport.y,
            0.0,
        )
        # Item 5 spans [50, 60), above the observed window [100, 200): a
        # nearest command scrolls to 50 instead of treating it as already
        # visible at the stale snapshot 0.
        action.update(
            {
                "name": "index",
                "index": 5,
                "alignment": "nearest",
            }
        )
        self._click(runtime, sequence=3)
        ops = _scroll_ops(runtime)
        self.assertEqual(ops[-1]["op"], "scroll_to")
        self.assertEqual(ops[-1]["offset_y"], 50.0)
        self.assertIsNone(runtime._last_error)

    def test_unrelated_measurement_ack_preserves_newer_no_commit_observation(
        self,
    ) -> None:
        # A measurement event rerenders and acknowledges with the same
        # accepted actual snapshot; the newer no-commit native observation
        # must survive the unrelated ack.
        runtime, controller, _ = self._runtime()
        _emit_scroll(runtime, offset=100, seq=2)
        self.assertEqual(controller._generic._viewport.y, 100.0)
        _emit_layout(runtime, key=0, width=300, height=100, seq=3)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(controller._generic._viewport.y, 100.0)
        self.assertEqual(
            controller._generic._binding.actual_viewport.y,
            0.0,
        )

    def test_animated_command_stages_observed_actual_viewport(self) -> None:
        # An animated command keeps the observed physical actual (100) as
        # the accepted actual viewport once acknowledged, not the stale
        # snapshot (0).
        runtime, controller, action = self._runtime()
        _emit_scroll(runtime, offset=100, seq=2)
        self.assertEqual(controller._generic._viewport.y, 100.0)
        action.update(
            {
                "name": "index",
                "index": 500,
                "alignment": "start",
                "animated": True,
            }
        )
        self._click(runtime, sequence=3)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(
            controller._generic._binding.actual_viewport.y,
            100.0,
        )
        self.assertEqual(controller._generic._viewport.y, 100.0)
        self.assertIsNone(runtime._last_error)

    def test_scroll_to_key_realized_and_source_resolved(self) -> None:
        runtime, _, action = self._runtime()
        action.update(
            {
                "name": "key",
                "key": 5,
                "alignment": "start",
            }
        )
        self._click(runtime, sequence=2)
        ops = _scroll_ops(runtime)
        self.assertEqual(ops[-1]["offset_y"], 50.0)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(0, 25)},
        )

        source = _CountingSource(tuple(range(1000)))
        controller = ListController()
        runtime2 = Runtime(
            lambda: Column(
                VirtualList(
                    source,
                    render_item=lambda item, index: Text(
                        text=str(item),
                        content_description=f"item-{item}",
                        on_click=lambda event: controller.scroll_to_key(
                            250,
                            alignment="start",
                            animated=False,
                        ),
                    ),
                    layout=FixedLinearLayout(10, "vertical"),
                    controller=controller,
                    width=300,
                    height=100,
                )
            ),
            transport=SilentTransport(),
        )
        runtime2.mount()
        runtime2.acknowledge_native_apply(1)
        _emit_scroll(runtime2, offset=0, seq=1)
        runtime2.acknowledge_native_apply(runtime2.revision)
        cell = next(
            node
            for node in runtime2._coordinator.accepted_index.values()
            if node.kind == "Text" and "click" in node.listeners
        )
        runtime2.dispatch_event(
            {
                "type": "event",
                "seq": 2,
                "target": cell.id,
                "event": "click",
                "handler": cell.listeners["click"],
                "payload": {},
            }
        )
        ops = _scroll_ops(runtime2)
        self.assertEqual(ops[-1]["offset_y"], 2500.0)
        # index_for_key resolution never scans the source.
        self.assertLess(source.key_accesses, 200)

    def test_scroll_to_key_default_index_keys_on_plain_sequence(self) -> None:
        runtime, controller, action = self._runtime()
        # The runtime uses key_for_item=lambda item, index: item, which is a
        # custom callback; use a plain default-index-key list instead.
        source = tuple(range(1000))
        controller2 = ListController()
        action2 = {"name": "key", "key": 42, "alignment": "start"}

        def app():
            def act(event):
                controller2.scroll_to_key(
                    action2["key"],
                    alignment=action2["alignment"],
                    animated=False,
                )

            return Column(
                VirtualList(
                    source,
                    render_item=lambda item, index: Text(
                        text=str(item),
                        content_description=f"dflt-{item}",
                        on_click=act,
                    ),
                    layout=FixedLinearLayout(10, "vertical"),
                    controller=controller2,
                    width=300,
                    height=100,
                )
            )

        runtime2 = Runtime(app, transport=SilentTransport())
        runtime2.mount()
        runtime2.acknowledge_native_apply(1)
        cell = next(
            node
            for node in runtime2._coordinator.accepted_index.values()
            if node.kind == "Text" and "click" in node.listeners
        )
        runtime2.dispatch_event({
            "type": "event",
            "seq": 1,
            "target": cell.id,
            "event": "click",
            "handler": cell.listeners["click"],
            "payload": {},
        })
        ops = _scroll_ops(runtime2)
        self.assertEqual(ops[-1]["offset_y"], 420.0)

    def test_scroll_to_key_unknown_raises_without_scanning(self) -> None:
        source = _CountingSource(tuple(range(10)))
        controller = ListController()
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    source,
                    render_item=lambda item, index: Text(
                        text=str(item),
                        content_description=f"item-{item}",
                        on_click=lambda event: controller.scroll_to_key(
                            900,
                            alignment="start",
                            animated=False,
                        ),
                    ),
                    layout=FixedLinearLayout(10, "vertical"),
                    controller=controller,
                    width=300,
                    height=100,
                )
            ),
            transport=SilentTransport(),
        )
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and "click" in node.listeners
        )
        before = source.key_accesses
        self.assertEqual(before, 10)  # mount realized the tiny source
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
        self.assertIn("not realized", runtime._last_error)
        # The failed lookup itself performed no source reads.
        self.assertEqual(source.key_accesses, before)

    def test_controller_requires_mounted_list(self) -> None:
        controller = ListController()
        with self.assertRaisesRegex(RuntimeError, "not mounted"):
            controller.scroll_to_offset(10, animated=False)
        with self.assertRaisesRegex(RuntimeError, "not mounted"):
            controller.scroll_to_index(5, alignment="start", animated=False)
        with self.assertRaisesRegex(RuntimeError, "not mounted"):
            controller.scroll_to_key(5, alignment="start", animated=False)

    def test_controller_validates_inputs(self) -> None:
        runtime, controller, _ = self._runtime()
        with self.assertRaises(IndexError):
            controller.scroll_to_index(1000, alignment="start", animated=False)
        with self.assertRaises(ValueError):
            controller.scroll_to_index(0, alignment="middle", animated=False)
        with self.assertRaises(TypeError):
            controller.scroll_to_index(0, alignment="start", animated=1)
        with self.assertRaises(ValueError):
            controller.scroll_to_offset(-1, animated=False)
        with self.assertRaises(TypeError):
            controller.scroll_to_offset("x", animated=False)
        with self.assertRaises(TypeError):
            controller.scroll_to_key(object(), alignment="start", animated=False)

    def test_alignment_requires_viewport_metrics(self) -> None:
        controller = ListController()

        def app():
            return Column(
                VirtualList(
                    tuple(range(1000)),
                    render_item=lambda item, index: Text(
                        text=str(item),
                        content_description=f"item-{item}",
                        on_click=lambda event: controller.scroll_to_index(
                            50, alignment="center", animated=False
                        ),
                    ),
                    layout=FixedLinearLayout(10, "vertical"),
                    key_for_item=lambda item, index: item,
                    controller=controller,
                )
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
        # center/end/nearest need native viewport metrics or a declared
        # main-axis size; neither is present here.
        self.assertIn("requires viewport metrics", runtime._last_error)


# ---------------------------------------------------------------------------
# Binding acceptance / rejection / reset / unmount / sibling swaps
# ---------------------------------------------------------------------------


class VirtualListBindingTests(unittest.TestCase):
    def _binding_runtime(self, *, controller=None, scroll_extent=100.0):
        controller = controller or ListController()

        def app():
            extent = state(10.0)

            def act(event):
                extent.set(20.0)

            return Column(
                VirtualList(
                    tuple(range(1000)),
                    render_item=lambda item, index: Text(
                        text=str(item),
                        content_description=f"item-{item}",
                        on_click=act,
                    ),
                    layout=FixedLinearLayout(extent.value, "vertical"),
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    width=300,
                    height=100,
                )
            )

        runtime = Runtime(app, transport=SilentTransport())
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        _emit_scroll(runtime, offset=0, seq=1)
        runtime.acknowledge_native_apply(runtime.revision)
        return runtime, controller

    def test_binding_promotes_only_after_native_ack(self) -> None:
        runtime, controller = self._binding_runtime()
        self.assertEqual(controller._generic._binding.layout.item_extent, 10.0)
        cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and "click" in node.listeners
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 2,
                "target": cell.id,
                "event": "click",
                "handler": cell.listeners["click"],
                "payload": {},
            }
        )
        self.assertEqual(controller._generic._binding.layout.item_extent, 10.0)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(controller._generic._binding.layout.item_extent, 20.0)

    def test_rejected_render_preserves_accepted_binding(self) -> None:
        runtime, controller = self._binding_runtime()
        cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and "click" in node.listeners
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 2,
                "target": cell.id,
                "event": "click",
                "handler": cell.listeners["click"],
                "payload": {},
            }
        )
        rejected = runtime.revision
        runtime.report_native_failure(revision=rejected, unknown=False)
        self.assertEqual(controller._generic._binding.layout.item_extent, 10.0)

    def test_unknown_reset_restores_initial_offset_and_ack(self) -> None:
        controller = ListController()
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(1000)),
                    render_item=_cell,
                    layout=FixedLinearLayout(10, "vertical"),
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    width=300,
                    height=100,
                )
            ),
            transport=SilentTransport(),
        )
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        _emit_scroll(runtime, offset=500, seq=1)
        uncertain = runtime.revision

        runtime.report_native_failure(revision=uncertain, unknown=True)

        snapshot = runtime.transport.latest
        initial_offset = next(
            op["props"]["_virtual_list_initial_offset"]
            for op in snapshot["ops"]
            if op.get("op") == "set_props"
            and "_virtual_list_initial_offset" in op.get("props", {})
        )
        self.assertEqual(initial_offset, 500.0)
        self.assertFalse(any(op.get("op") == "scroll_to" for op in snapshot["ops"]))
        reset_revision = runtime.revision
        self.assertGreater(reset_revision, uncertain)
        runtime.acknowledge_native_apply(reset_revision)
        self.assertIsNotNone(controller._generic._binding)

    def test_controller_unbinds_when_list_is_removed(self) -> None:
        controller = ListController()

        def app():
            visible = state(True)
            if not visible.value:
                return Text(text="gone")
            return Column(
                VirtualList(
                    tuple(range(10)),
                    render_item=lambda item, index: Text(
                        text=str(item),
                        content_description=f"item-{item}",
                        on_click=lambda event: visible.set(False),
                    ),
                    layout=FixedLinearLayout(10, "vertical"),
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    width=300,
                    height=100,
                )
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        self.assertIsNotNone(controller._generic._binding)
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
        self.assertIsNone(controller._generic._binding)
        self.assertIsNone(controller._generic._scroll_ref.current)

    def test_keyed_sibling_swap_keeps_controller_identity(self) -> None:
        first = ListController()
        second = ListController()

        def app():
            order = state(0)

            def flip(event):
                order.set(1)

            a = VirtualList(
                tuple(range(10)),
                render_item=lambda item, index: Text(
                    text=str(item),
                    content_description=f"a-{item}",
                    on_click=flip,
                ),
                layout=FixedLinearLayout(10, "vertical"),
                key_for_item=lambda item, index: item,
                controller=first,
                key="list-a",
                width=300,
                height=100,
            )
            b = VirtualList(
                tuple(range(10, 20)),
                render_item=lambda item, index: Text(
                    text=str(item),
                    content_description=f"b-{item}",
                ),
                layout=FixedLinearLayout(10, "vertical"),
                key_for_item=lambda item, index: item,
                controller=second,
                key="list-b",
                width=300,
                height=100,
            )
            if order.value == 0:
                return Column(a, b)
            return Column(b, a)

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        a_cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text"
            and node.props.get("content_description", "").startswith("a-")
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 1,
                "target": a_cell.id,
                "event": "click",
                "handler": a_cell.listeners["click"],
                "payload": {},
            }
        )
        self.assertIsNotNone(first._generic._binding)
        self.assertIsNotNone(second._generic._binding)
        self.assertIsNotNone(first._generic._scroll_ref.current)
        self.assertIsNotNone(second._generic._scroll_ref.current)
        # The controller still drives its logical list after the swap.
        self.assertEqual(first._generic._binding.source.item_count, 10)
        self.assertEqual(second._generic._binding.source.item_count, 10)


# ---------------------------------------------------------------------------
# Failure recovery and lazy behavior at scale
# ---------------------------------------------------------------------------


class VirtualListFailureTests(unittest.TestCase):
    def test_invalid_layout_preserves_accepted_tree(self) -> None:
        layout = _BrokenLayout()

        def app():
            return Column(
                VirtualList(
                    tuple(range(100)),
                    render_item=_cell,
                    layout=layout,
                    key_for_item=lambda item, index: item,
                    width=300,
                    height=100,
                )
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        self.assertEqual(len(_cell_keys(runtime)), 20)
        _emit_scroll(runtime, offset=500, seq=1)
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(0, 20)},
        )
        self.assertIn("layout exploded", runtime._last_error)

    def test_invalid_render_item_preserves_accepted_tree(self) -> None:
        broken = {"enabled": False}

        def render_item(item, index):
            if broken["enabled"]:
                raise RuntimeError("cell render failed")
            return Text(text=str(item), content_description=f"item-{item}")

        def app():
            return Column(
                VirtualList(
                    tuple(range(100)),
                    render_item=render_item,
                    layout=FixedLinearLayout(10, "vertical"),
                    key_for_item=lambda item, index: item,
                    width=300,
                    height=100,
                )
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        self.assertEqual(len(_cell_keys(runtime)), 20)
        broken["enabled"] = True
        # A replan outside the accepted coverage re-runs the render callback,
        # which raises; the accepted tree stays mounted.
        _emit_scroll(runtime, offset=500, seq=1)
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(0, 20)},
        )
        self.assertIn("cell render failed", runtime._last_error)

    def test_invalid_source_item_count_preserves_accepted_tree(self) -> None:
        class _BrokenCount:
            @property
            def item_count(self):
                return -1

            def item_at(self, index):
                return index

            def key_at(self, index):
                return index

        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    _BrokenCount(),
                    render_item=_cell,
                    layout=FixedLinearLayout(10, "vertical"),
                    width=300,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        self.assertIsNone(runtime._coordinator.accepted_root)
        self.assertIn("item_count", runtime._last_error)

    def test_no_source_wide_scan_at_100k(self) -> None:
        source = _CountingSource(tuple(range(100_000)))
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    source,
                    render_item=_cell,
                    layout=FixedLinearLayout(10, "vertical"),
                    width=300,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        _emit_scroll(runtime, offset=5_000, seq=1)
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(490, 520)},
        )
        self.assertLess(
            source.key_accesses + source.item_accesses,
            500,
        )


# ---------------------------------------------------------------------------
# Target retention, registry staging, and canonical-key validation
# ---------------------------------------------------------------------------


class _TargetTrackingLayout:
    """Records whether requests carried a target_index and delegates."""

    def __init__(self, inner):
        self.inner = inner
        self.last_target = None
        self.place_count = 0

    def place(self, request):
        self.last_target = request.target_index
        self.place_count += 1
        return self.inner.place(request)

    def offset_for_index(self, index, *, measurement_for_index):
        return self.inner.offset_for_index(
            index, measurement_for_index=measurement_for_index
        )


class VirtualListTargetAndRegistryTests(unittest.TestCase):
    def test_animated_scroll_retains_target_outside_realization(self) -> None:
        controller = ListController()
        layout = _TargetTrackingLayout(FixedLinearLayout(10, "vertical"))

        def render_item(item, index):
            return Text(
                text=str(item),
                content_description=f"item-{item}",
                on_click=lambda event: controller.scroll_to_index(
                    500, alignment="start", animated=True
                ),
            )

        def app():
            return Column(
                VirtualList(
                    tuple(range(1000)),
                    render_item=render_item,
                    layout=layout,
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    max_offscreen_items=4,
                    width=300,
                    height=100,
                )
            )

        runtime = Runtime(app, transport=SilentTransport())
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        _emit_scroll(runtime, offset=0, seq=1)
        runtime.acknowledge_native_apply(runtime.revision)

        cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and "click" in node.listeners
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 2,
                "target": cell.id,
                "event": "click",
                "handler": cell.listeners["click"],
                "payload": {},
            }
        )
        # The pending target is carried in the same state transaction.
        self.assertEqual(
            controller._generic._binding.window_state.value.target_index,
            500,
        )
        self.assertEqual(layout.last_target, 500)
        runtime.acknowledge_native_apply(runtime.revision)
        # The target placement is composed even though the actual viewport
        # stays at 0 during the animation and the offscreen budget is 4.
        self.assertIn(500, _cell_keys(runtime))
        # The window follows the destination.
        self.assertEqual(
            controller._generic._binding.window_state.value.viewport.y,
            5000.0,
        )

    def test_target_cleared_once_actual_viewport_reaches_it(self) -> None:
        controller = ListController()

        def render_item(item, index):
            return Text(
                text=str(item),
                content_description=f"item-{item}",
                on_click=lambda event: controller.scroll_to_index(
                    500, alignment="start", animated=True
                ),
            )

        def app():
            return Column(
                VirtualList(
                    tuple(range(1000)),
                    render_item=render_item,
                    layout=FixedLinearLayout(10, "vertical"),
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    width=300,
                    height=100,
                )
            )

        runtime = Runtime(app, transport=SilentTransport())
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        _emit_scroll(runtime, offset=0, seq=1)
        runtime.acknowledge_native_apply(runtime.revision)
        cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and "click" in node.listeners
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 2,
                "target": cell.id,
                "event": "click",
                "handler": cell.listeners["click"],
                "payload": {},
            }
        )
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(
            controller._generic._binding.window_state.value.target_index,
            500,
        )
        # The native scroll catches up; the actual viewport now intersects
        # the target's interval and the pending target is cleared.
        _emit_scroll(runtime, offset=5_000, seq=3)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertIsNone(controller._generic._binding.window_state.value.target_index)
        self.assertIn(500, _cell_keys(runtime))

    def test_pending_target_shrink_renders_and_clears_dead_target(self) -> None:
        controller = ListController()
        layout = _TargetTrackingLayout(FixedLinearLayout(10, "vertical"))

        def app():
            data_cell = state(tuple(range(1000)))

            def shrink(event):
                data_cell.set(tuple(range(10)))

            return Column(
                VirtualList(
                    data_cell.value,
                    render_item=lambda item, index: Text(
                        text=str(item),
                        content_description=f"item-{item}",
                        on_click=lambda event: controller.scroll_to_index(
                            500, alignment="start", animated=True
                        ),
                    ),
                    layout=layout,
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    width=300,
                    height=100,
                ),
                Text(
                    text="shrink",
                    key="shrink-btn",
                    on_click=shrink,
                ),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        _emit_scroll(runtime, offset=0, seq=1)
        runtime.acknowledge_native_apply(runtime.revision)

        def item_cell():
            return next(
                node
                for node in runtime._coordinator.accepted_index.values()
                if node.kind == "Text"
                and node.props.get("content_description", "").startswith("item-")
                and "click" in node.listeners
            )

        # Queue an animated target far ahead, then shrink the source before
        # the animation lands: the dead target (500 >= 10) must be dropped
        # from the render request instead of wedging the list.
        cell = item_cell()
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 2,
                "target": cell.id,
                "event": "click",
                "handler": cell.listeners["click"],
                "payload": {},
            }
        )
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(
            controller._generic._binding.window_state.value.target_index,
            500,
        )

        shrink_cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and node.key == "shrink-btn"
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 3,
                "target": shrink_cell.id,
                "event": "click",
                "handler": shrink_cell.listeners["click"],
                "payload": {},
            }
        )
        # The shrink render succeeded and the request carried no dead target.
        self.assertIsNone(runtime._last_error)
        self.assertIsNone(layout.last_target)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(
            _cell_keys(runtime),
            {index for index in range(0, 10)},
        )

        # The next scroll observation clears the dead target from the
        # accepted state; the list keeps scrolling without repeated errors.
        _emit_scroll(runtime, offset=0, seq=4)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertIsNone(controller._generic._binding.window_state.value.target_index)
        self.assertIsNone(runtime._last_error)

    def test_pending_target_cancelled_by_shrink_then_grow_before_scroll(
        self,
    ) -> None:
        controller = ListController()
        layout = _TargetTrackingLayout(FixedLinearLayout(10, "vertical"))

        def app():
            data_cell = state(tuple(range(1000)))

            def swap(event):
                # Shrink, then grow back to a compatible count before any
                # scroll observation: the pending target must not resurrect
                # onto the replacement data.  (The grow uses a different
                # object with different contents so the framework cannot
                # treat the replacement as an unchanged value.)
                data_cell.set(tuple(range(10)))
                data_cell.set(tuple(range(1000, 2000)))

            return Column(
                VirtualList(
                    data_cell.value,
                    render_item=lambda item, index: Text(
                        text=str(item),
                        content_description=f"item-{item}",
                        on_click=lambda event: controller.scroll_to_index(
                            500, alignment="start", animated=True
                        ),
                    ),
                    layout=layout,
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    width=300,
                    height=100,
                ),
                Text(text="swap", key="swap-btn", on_click=swap),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        _emit_scroll(runtime, offset=0, seq=1)
        runtime.acknowledge_native_apply(runtime.revision)

        def target_cell():
            return next(
                node
                for node in runtime._coordinator.accepted_index.values()
                if node.kind == "Text" and "click" in node.listeners
            )

        # Queue an animated target far ahead and let it commit: the target
        # records the identity of the accepted data.
        cell = target_cell()
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 2,
                "target": cell.id,
                "event": "click",
                "handler": cell.listeners["click"],
                "payload": {},
            }
        )
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(
            controller._generic._binding.window_state.value.target_index,
            500,
        )
        self.assertIsNotNone(
            controller._generic._binding.window_state.value.target_source
        )

        # Shrink then grow before any scroll observation: the replacement
        # data is a different object, so the pending target is cancelled and
        # the render request carries no dead target.
        swap_cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and node.key == "swap-btn"
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 3,
                "target": swap_cell.id,
                "event": "click",
                "handler": swap_cell.listeners["click"],
                "payload": {},
            }
        )
        self.assertIsNone(runtime._last_error)
        self.assertIsNone(layout.last_target)
        runtime.acknowledge_native_apply(runtime.revision)

        # The next scroll observation clears every target field together.
        _emit_scroll(runtime, offset=0, seq=4)
        runtime.acknowledge_native_apply(runtime.revision)
        state_value = controller._generic._binding.window_state.value
        self.assertIsNone(state_value.target_index)
        self.assertIsNone(state_value.target_main_start)
        self.assertIsNone(state_value.target_main_end)
        self.assertIsNone(state_value.target_source)

    def test_pending_target_cancelled_by_same_count_replacement(self) -> None:
        controller = ListController()
        layout = _TargetTrackingLayout(FixedLinearLayout(10, "vertical"))

        def app():
            data_cell = state(tuple(range(1000)))

            def replace(event):
                # Same item count, different data object: an index command
                # must not silently retarget a different item on new data.
                data_cell.set(tuple(range(1000, 2000)))

            return Column(
                VirtualList(
                    data_cell.value,
                    render_item=lambda item, index: Text(
                        text=str(item),
                        content_description=f"item-{item}",
                        on_click=lambda event: controller.scroll_to_index(
                            500, alignment="start", animated=True
                        ),
                    ),
                    layout=layout,
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    width=300,
                    height=100,
                ),
                Text(text="replace", key="replace-btn", on_click=replace),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        _emit_scroll(runtime, offset=0, seq=1)
        runtime.acknowledge_native_apply(runtime.revision)

        def target_cell():
            return next(
                node
                for node in runtime._coordinator.accepted_index.values()
                if node.kind == "Text" and "click" in node.listeners
            )

        cell = target_cell()
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 2,
                "target": cell.id,
                "event": "click",
                "handler": cell.listeners["click"],
                "payload": {},
            }
        )
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(
            controller._generic._binding.window_state.value.target_index,
            500,
        )

        # Replace the data with a new object of the same length: the pending
        # target is cancelled even though index 500 is still in range.
        replace_cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and node.key == "replace-btn"
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 3,
                "target": replace_cell.id,
                "event": "click",
                "handler": replace_cell.listeners["click"],
                "payload": {},
            }
        )
        self.assertIsNone(runtime._last_error)
        self.assertIsNone(layout.last_target)
        runtime.acknowledge_native_apply(runtime.revision)

        # The next scroll observation clears the cancelled target fields.
        _emit_scroll(runtime, offset=0, seq=4)
        runtime.acknowledge_native_apply(runtime.revision)
        state_value = controller._generic._binding.window_state.value
        self.assertIsNone(state_value.target_index)
        self.assertIsNone(state_value.target_source)

    def test_rejected_render_does_not_leak_candidate_registry(self) -> None:
        controller = ListController()
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(1000)),
                    render_item=_cell,
                    layout=FixedLinearLayout(10, "vertical"),
                    key_for_item=lambda item, index: item,
                    controller=controller,
                    width=300,
                    height=100,
                )
            ),
            transport=SilentTransport(),
        )
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        accepted_registry = controller._generic._key_registry
        self.assertEqual(
            set(accepted_registry.key_to_index),
            set(range(0, 20)),
        )
        _emit_scroll(runtime, offset=500, seq=1)
        uncertain = runtime.revision
        runtime.report_native_failure(revision=uncertain, unknown=False)
        # The candidate clone mutated a detached registry; the accepted
        # mappings are untouched.
        self.assertEqual(
            set(controller._generic._key_registry.key_to_index),
            set(range(0, 20)),
        )
        self.assertNotIn(50, controller._generic._key_registry.key_to_index)

    def test_duplicate_key_across_windows_is_rejected(self) -> None:
        controller = ListController()
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(1000)),
                    render_item=_cell,
                    layout=FixedLinearLayout(10, "vertical"),
                    key_for_item=lambda item, index: index % 100,
                    controller=controller,
                    width=300,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        # Index 100 repeats key 0, which was realized at index 0.
        _emit_scroll(runtime, offset=1000, seq=1)
        self.assertIn("Duplicate list key", runtime._last_error)
        # The accepted tree is preserved.
        self.assertIn(0, _cell_keys(runtime))

    def test_invalid_source_key_raises_clear_error(self) -> None:
        class _BadKeySource:
            @property
            def item_count(self):
                return 5

            def item_at(self, index):
                return index

            def key_at(self, index):
                return object()

        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    _BadKeySource(),
                    render_item=_cell,
                    layout=FixedLinearLayout(10, "vertical"),
                    width=300,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        self.assertIsNone(runtime._coordinator.accepted_root)
        self.assertIn("list key at index 0", runtime._last_error)

    def test_non_canonical_measurement_key_is_validated(self) -> None:
        class _BadKeySource:
            def __init__(self):
                self.items = list(range(20))

            @property
            def item_count(self):
                return len(self.items)

            def item_at(self, index):
                return self.items[index]

            def key_at(self, index):
                return index if index < 4 else object()

        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    _BadKeySource(),
                    render_item=_cell,
                    layout=FixedLinearLayout(10, "vertical"),
                    width=300,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        # The realized window reaches the first non-canonical key and the
        # engine rejects it with a clear path-scoped error.
        self.assertIn("list key at index 4", runtime._last_error)


if __name__ == "__main__":
    unittest.main()
