from __future__ import annotations

import unittest

from vyne import Column, Text, state
from vyne._lists import (
    FixedExtentLayout,
    FixedVirtualListController,
    FixedVirtualListSpec,
    IndexRange,
    KeyRegistry,
    RenderMask,
    SequenceDataSource,
    ViewportMetrics,
    WindowConfig,
    compose_fixed_window,
    render_fixed_virtual_list,
)
from vyne._lists.fixed import (
    _capped_planning_viewport,
    _mask_contains_viewports,
    _preferred_actual,
)
from vyne.events import latest
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport

from tests.support.runtime_helpers import SilentTransport
from vyne.values import FrozenMap


def _source(count: int) -> SequenceDataSource:
    return SequenceDataSource(
        tuple(f"item-{index}" for index in range(count)),
        key_for_item=lambda item, index: f"key-{index}",
    )


def _spec(count: int = 1000) -> FixedVirtualListSpec:
    return FixedVirtualListSpec(
        source=_source(count),
        controller=FixedVirtualListController(),
        render_item=lambda item, index, key: Text(text=item),
        item_extent=10,
        axis="vertical",
        initial_mask=RenderMask.from_ranges(IndexRange(0, 5)),
        retained_mask=RenderMask(),
        window_config=WindowConfig(overscan_viewports=1),
        scroll_props=FrozenMap(
            (
                ("width", 300),
                ("height", 100),
            )
        ),
    )


def _scroll_payload(
    *,
    offset: float,
    extent: float = 100,
    velocity: float = 0,
    projected_offset: float | None = None,
) -> dict:
    projected = offset if projected_offset is None else projected_offset
    return {
        "offset_x": 0.0,
        "offset_y": offset,
        "viewport_width": 300.0,
        "viewport_height": extent,
        "content_width": 300.0,
        "content_height": 10_000.0,
        "velocity_x": 0.0,
        "velocity_y": velocity,
        "projected_offset_x": 0.0,
        "projected_offset_y": projected,
        "event_time": 10,
    }


def _horizontal_scroll_payload(*, offset: float, extent: float = 100) -> dict:
    payload = _scroll_payload(offset=0, extent=100)
    payload.update(
        {
            "offset_x": offset,
            "projected_offset_x": offset,
            "projected_offset_y": 0.0,
            "viewport_width": extent,
            "content_width": 10_000.0,
        }
    )
    return payload


class SequenceDataSourceTests(unittest.TestCase):
    def test_construction_reads_no_items_or_keys(self) -> None:
        items = tuple(range(1_000_000))
        accesses = {"key": 0, "item": 0}

        def key_for_item(item, index):
            accesses["key"] += 1
            return item

        source = SequenceDataSource(items, key_for_item)
        self.assertEqual(source.item_count, 1_000_000)
        self.assertEqual(accesses, {"key": 0, "item": 0})

    def test_index_key_sources_are_marked_unique(self) -> None:
        source = SequenceDataSource(("x", "y"))
        self.assertTrue(source.uses_index_keys)
        self.assertFalse(
            SequenceDataSource(
                ("x", "y"),
                key_for_item=lambda item, index: index,
            ).uses_index_keys
        )

    def test_items_and_keys_are_read_only_for_accessed_indexes(self) -> None:
        def key_for_item(item, index):
            return f"{item}-{index}"

        source = SequenceDataSource(("a", "b", "c"), key_for_item)
        self.assertEqual(source.item_at(1), "b")
        self.assertEqual(source.key_at(1), "b-1")
        self.assertEqual(source.key_at(2), "c-2")

    def test_key_for_item_none_defaults_to_index(self) -> None:
        source = SequenceDataSource(("x", "y"))
        self.assertEqual(source.key_at(0), 0)
        self.assertEqual(source.key_at(1), 1)

    def test_non_canonical_keys_reject_on_access(self) -> None:
        source = SequenceDataSource(
            ("a",),
            key_for_item=lambda item, index: object(),
        )
        with self.assertRaisesRegex(TypeError, "list key at index 0"):
            source.key_at(0)

    def test_composition_rejects_duplicate_keys_in_realized_set(self) -> None:
        spec = FixedVirtualListSpec(
            source=SequenceDataSource(
                ("a", "b"),
                key_for_item=lambda item, index: "same",
            ),
            controller=FixedVirtualListController(),
            render_item=lambda item, index, key: Text(text=item),
            item_extent=10,
            axis="vertical",
            initial_mask=RenderMask.from_ranges(IndexRange(0, 2)),
            retained_mask=RenderMask(),
            window_config=WindowConfig(overscan_viewports=0),
        )
        with self.assertRaisesRegex(ValueError, "Duplicate list key"):
            compose_fixed_window(
                spec,
                RenderMask.from_ranges(IndexRange(0, 2)),
                on_scroll_metrics=latest(lambda event: None),
            )

    def test_duplicate_keys_are_rejected_across_disjoint_realized_ranges(self) -> None:
        spec = FixedVirtualListSpec(
            source=SequenceDataSource(
                ("a", "b", "c", "d"),
                key_for_item=lambda item, index: index % 3,
            ),
            controller=FixedVirtualListController(),
            render_item=lambda item, index, key: Text(text=item),
            item_extent=10,
            axis="vertical",
            initial_mask=RenderMask(),
            retained_mask=RenderMask(),
            window_config=WindowConfig(overscan_viewports=0),
        )
        with self.assertRaisesRegex(ValueError, "Duplicate list key"):
            compose_fixed_window(
                spec,
                RenderMask.from_ranges(IndexRange(0, 1), IndexRange(3, 4)),
                on_scroll_metrics=latest(lambda event: None),
            )

    def test_registry_rejects_duplicate_key_across_compose_calls(self) -> None:
        data = tuple(range(1000))
        key_for_item = lambda item, index: index % 100
        registry = KeyRegistry()
        source = SequenceDataSource(data, key_for_item)
        registry.reset(data, key_for_item, source.item_count)
        spec = FixedVirtualListSpec(
            source=source,
            controller=FixedVirtualListController(),
            render_item=lambda item, index, key: Text(text=str(item)),
            item_extent=10,
            axis="vertical",
            initial_mask=RenderMask(),
            retained_mask=RenderMask(),
            window_config=WindowConfig(overscan_viewports=0),
            key_registry=registry,
        )
        compose_fixed_window(
            spec,
            RenderMask.from_ranges(IndexRange(0, 5)),
            on_scroll_metrics=latest(lambda event: None),
        )
        # Key 0 was realized at index 0; realizing it again at index 100 is
        # a duplicate across windows and must be rejected.
        with self.assertRaisesRegex(ValueError, "Duplicate list key"):
            compose_fixed_window(
                spec,
                RenderMask.from_ranges(IndexRange(100, 105)),
                on_scroll_metrics=latest(lambda event: None),
            )

    def test_registry_resets_when_data_object_changes(self) -> None:
        first_data = tuple(range(1000))
        second_data = tuple(reversed(range(1000)))
        key_for_item = lambda item, index: item
        registry = KeyRegistry()
        source = SequenceDataSource(first_data, key_for_item)
        registry.reset(first_data, key_for_item, source.item_count)
        spec = FixedVirtualListSpec(
            source=source,
            controller=FixedVirtualListController(),
            render_item=lambda item, index, key: Text(text=str(item)),
            item_extent=10,
            axis="vertical",
            initial_mask=RenderMask(),
            retained_mask=RenderMask(),
            window_config=WindowConfig(overscan_viewports=0),
            key_registry=registry,
        )
        compose_fixed_window(
            spec,
            RenderMask.from_ranges(IndexRange(0, 5)),
            on_scroll_metrics=latest(lambda event: None),
        )
        self.assertIn(0, registry.key_to_index)

        # A different data object resets the registry even when some keys are
        # equal: reorder/append/replacement must never false-positive.
        self.assertTrue(registry.stale(second_data, key_for_item, len(second_data)))
        registry.reset(second_data, key_for_item, len(second_data))
        self.assertEqual(registry.key_to_index, {})

    def test_index_key_sources_skip_registry_recording(self) -> None:
        data = tuple(range(1000))
        registry = KeyRegistry()
        source = SequenceDataSource(data)
        registry.reset(data, None, source.item_count)
        spec = FixedVirtualListSpec(
            source=source,
            controller=FixedVirtualListController(),
            render_item=lambda item, index, key: Text(text=str(item)),
            item_extent=10,
            axis="vertical",
            initial_mask=RenderMask(),
            retained_mask=RenderMask(),
            window_config=WindowConfig(overscan_viewports=0),
            key_registry=registry,
        )
        compose_fixed_window(
            spec,
            RenderMask.from_ranges(IndexRange(0, 1000)),
            on_scroll_metrics=latest(lambda event: None),
        )
        # Index keys are unique by construction; no entries are recorded.
        self.assertEqual(registry.key_to_index, {})


class CappedPlanningViewportTests(unittest.TestCase):
    def test_forward_projection_is_capped(self) -> None:
        config = WindowConfig(overscan_viewports=1, max_render_ahead_viewports=3)
        result = _capped_planning_viewport(
            ViewportMetrics(50_000, 100),
            ViewportMetrics(0, 100),
            config,
        )
        self.assertEqual(result.offset, 300.0)

    def test_reverse_projection_is_capped(self) -> None:
        config = WindowConfig(overscan_viewports=1, max_render_ahead_viewports=3)
        result = _capped_planning_viewport(
            ViewportMetrics(0, 100),
            ViewportMetrics(9_900, 100),
            config,
        )
        self.assertEqual(result.offset, 9_600.0)

    def test_low_bound_clamps_at_zero(self) -> None:
        config = WindowConfig(overscan_viewports=1, max_render_ahead_viewports=3)
        result = _capped_planning_viewport(
            ViewportMetrics(0, 100),
            ViewportMetrics(50, 100),
            config,
        )
        self.assertEqual(result.offset, 0.0)

    def test_projection_inside_bounds_is_unchanged(self) -> None:
        config = WindowConfig(overscan_viewports=1, max_render_ahead_viewports=3)
        result = _capped_planning_viewport(
            ViewportMetrics(150, 100),
            ViewportMetrics(0, 100),
            config,
        )
        self.assertEqual(result.offset, 150.0)

    def test_zero_cap_stays_unbounded(self) -> None:
        config = WindowConfig(overscan_viewports=1)
        result = _capped_planning_viewport(
            ViewportMetrics(0, 100),
            ViewportMetrics(9_900, 100),
            config,
        )
        self.assertEqual(result.offset, 0.0)


class MaskContainsViewportsTests(unittest.TestCase):
    def test_mask_covering_viewport_is_contained(self) -> None:
        layout = FixedExtentLayout(1000, 10)
        mask = RenderMask.from_ranges(IndexRange(40, 70))

        self.assertTrue(
            _mask_contains_viewports(
                mask,
                layout,
                ViewportMetrics(500, 100),
            )
        )

    def test_mask_missing_viewport_items_rejects(self) -> None:
        layout = FixedExtentLayout(1000, 10)
        mask = RenderMask.from_ranges(IndexRange(0, 40))

        self.assertFalse(
            _mask_contains_viewports(
                mask,
                layout,
                ViewportMetrics(500, 100),
            )
        )

    def test_out_of_range_offset_is_clamped_to_end_window(self) -> None:
        """A shrink that leaves the mask inside the item count must still
        replan when the old viewport is beyond the new content end."""
        layout = FixedExtentLayout(100, 10)  # 100 items, total 1000
        # Mask is entirely within the reduced item count...
        mask = RenderMask.from_ranges(IndexRange(90, 95))
        # ...but the viewport start (1500) is beyond the content end (1000).
        # The clamped end window is items 90..100, which the mask does not
        # fully cover, so the check must return False and force a replan.
        self.assertFalse(
            _mask_contains_viewports(
                mask,
                layout,
                ViewportMetrics(1500, 100),
            )
        )

    def test_offset_exactly_at_content_end_is_clamped(self) -> None:
        layout = FixedExtentLayout(100, 10)
        mask = RenderMask.from_ranges(IndexRange(90, 95))

        self.assertFalse(
            _mask_contains_viewports(
                mask,
                layout,
                ViewportMetrics(1000, 100),
            )
        )

    def test_mask_covering_clamped_end_window_is_contained(self) -> None:
        layout = FixedExtentLayout(100, 10)
        mask = RenderMask.from_ranges(IndexRange(90, 100))

        self.assertTrue(
            _mask_contains_viewports(
                mask,
                layout,
                ViewportMetrics(1500, 100),
            )
        )

    def test_empty_extent_skips_viewport_checks(self) -> None:
        layout = FixedExtentLayout(100, 10)
        mask = RenderMask.from_ranges(IndexRange(0, 5))

        self.assertTrue(
            _mask_contains_viewports(
                mask,
                layout,
                ViewportMetrics(0, 0),
            )
        )


class FixedWindowCompositionTests(unittest.TestCase):
    def test_only_masked_items_are_composed(self) -> None:
        spec = _spec(100)
        element = compose_fixed_window(
            spec,
            RenderMask.from_ranges(IndexRange(20, 25)),
            on_scroll_metrics=latest(lambda event: None),
        )

        content = element.children[0]
        # Leading spacer, five cells, trailing spacer.
        self.assertEqual(len(content.children), 7)
        cells = [
            child
            for child in content.children
            if child.props["key"][0] == "__vyne_list_cell__"
        ]
        self.assertEqual(len(cells), 5)
        self.assertEqual(cells[0].children[0].props["text"], "item-20")
        self.assertEqual(cells[-1].children[0].props["text"], "item-24")
        self.assertEqual(content.children[0].props["height"], 200.0)
        self.assertEqual(content.children[-1].props["height"], 750.0)
        self.assertEqual(element.props["_virtual_list_initial_offset"], 0.0)
        self.assertNotIn("_virtual_list_coverage_enabled", element.props)

    def test_retained_cells_keep_disjoint_regions_without_coverage_markers(
        self,
    ) -> None:
        element = compose_fixed_window(
            _spec(100),
            RenderMask.from_ranges(IndexRange(0, 1), IndexRange(20, 25)),
            on_scroll_metrics=latest(lambda event: None),
        )

        cell_keys = {
            child.props["key"][1]
            for child in element.children[0].children
            if child.props["key"][0] == "__vyne_list_cell__"
        }
        self.assertEqual(
            cell_keys,
            {f"key-{index}" for index in (*range(0, 1), *range(20, 25))},
        )
        self.assertFalse(
            any(
                child.props.get("_virtual_list_coverage_cell", False)
                for child in element.children[0].children
            )
        )


class HorizontalFixedVirtualListTests(unittest.TestCase):
    def _spec(self, *, on_click=None) -> FixedVirtualListSpec:
        controller = FixedVirtualListController()
        return FixedVirtualListSpec(
            source=_source(1000),
            controller=controller,
            render_item=lambda item, index, key: Text(
                text=item,
                on_click=(
                    (lambda event: on_click(controller))
                    if on_click is not None
                    else None
                ),
            ),
            item_extent=10,
            axis="horizontal",
            initial_mask=RenderMask.from_ranges(IndexRange(0, 5)),
            retained_mask=RenderMask(),
            window_config=WindowConfig(overscan_viewports=1),
            scroll_props=FrozenMap((("width", 100), ("height", 50))),
        )

    def test_horizontal_composition_uses_row_and_width_spacers(self) -> None:
        spec = self._spec()
        element = compose_fixed_window(
            spec,
            RenderMask.from_ranges(IndexRange(20, 25)),
            on_scroll_metrics=latest(lambda event: None),
        )

        self.assertEqual(element.kind, "HorizontalScroll")
        content = element.children[0]
        self.assertEqual(content.kind, "Layout")
        self.assertEqual(content.props["orientation"], "horizontal")
        self.assertEqual(content.children[0].props["width"], 200.0)
        self.assertEqual(content.children[-1].props["width"], 9750.0)
        cells = [
            child
            for child in content.children
            if child.props["key"][0] == "__vyne_list_cell__"
        ]
        self.assertEqual(len(cells), 5)
        self.assertTrue(all(cell.props["width"] == 10.0 for cell in cells))

    def test_horizontal_metrics_select_window_on_x_axis(self) -> None:
        spec = self._spec()
        runtime = Runtime(
            lambda: render_fixed_virtual_list(spec),
            transport=MemoryTransport(),
        )
        runtime.mount()
        scroll = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if "scroll_metrics" in node.listeners
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 1,
                "target": scroll.id,
                "event": "scroll_metrics",
                "handler": scroll.listeners["scroll_metrics"],
                "payload": _horizontal_scroll_payload(offset=500),
            }
        )

        self.assertEqual(scroll.kind, "HorizontalScroll")
        self.assertEqual(
            {
                node.props["text"]
                for node in runtime._coordinator.accepted_index.values()
                if node.kind == "Text"
            },
            {f"item-{index}" for index in range(40, 70)},
        )

    def test_controller_queues_x_offset_after_realizing_window(self) -> None:
        spec = self._spec(
            on_click=lambda controller: controller.scroll_to_index(
                50,
                alignment="start",
                animated=False,
            )
        )
        runtime = Runtime(
            lambda: render_fixed_virtual_list(spec),
            transport=MemoryTransport(),
        )
        runtime.mount()
        scroll = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if "scroll_metrics" in node.listeners
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 1,
                "target": scroll.id,
                "event": "scroll_metrics",
                "handler": scroll.listeners["scroll_metrics"],
                "payload": _horizontal_scroll_payload(offset=0),
            }
        )
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

        self.assertEqual(
            runtime.latest_commit["ops"][-1],
            {
                "op": "scroll_to",
                "id": spec.controller._scroll_ref.current.node_id,
                "offset_x": 500.0,
                "offset_y": 0.0,
                "animated": False,
            },
        )
        self.assertEqual(
            {
                node.props["text"]
                for node in runtime._coordinator.accepted_index.values()
                if node.kind == "Text"
            },
            {f"item-{index}" for index in range(40, 70)},
        )


class FixedVirtualListRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = _spec()
        self.transport = MemoryTransport()
        self.runtime = Runtime(
            lambda: render_fixed_virtual_list(self.spec),
            transport=self.transport,
        )
        self.runtime.mount()

    def _scroll_listener(self) -> tuple[int, int]:
        for node in self.runtime._coordinator.accepted_index.values():
            handler = node.listeners.get("scroll_metrics")
            if handler is not None:
                return node.id, handler
        self.fail("No accepted scroll_metrics listener")

    def _emit_scroll(self, *, offset: float, sequence: int) -> None:
        target, handler = self._scroll_listener()
        self.runtime.dispatch_event(
            {
                "type": "event",
                "seq": sequence,
                "target": target,
                "event": "scroll_metrics",
                "handler": handler,
                "payload": _scroll_payload(offset=offset),
            }
        )

    def test_initial_native_mirror_covers_declared_viewport_and_overscan(self) -> None:
        text_nodes = [
            node
            for node in self.runtime._coordinator.accepted_index.values()
            if node.kind == "Text"
        ]

        self.assertEqual(len(text_nodes), 20)
        self.assertLess(len(self.runtime._coordinator.accepted_index), 50)

    def test_scroll_replaces_window_without_rendering_all_data(self) -> None:
        initial_send_count = self.transport.send_count

        self._emit_scroll(offset=500, sequence=1)

        text_nodes = [
            node
            for node in self.runtime._coordinator.accepted_index.values()
            if node.kind == "Text"
        ]
        self.assertEqual(self.transport.send_count, initial_send_count + 1)
        self.assertEqual(len(text_nodes), 30)
        self.assertLess(len(self.runtime._coordinator.accepted_index), 70)
        self.assertEqual(
            {node.props["text"] for node in text_nodes},
            {f"item-{index}" for index in range(40, 70)},
        )

    def test_scroll_inside_accepted_mask_does_not_emit_a_commit(self) -> None:
        self._emit_scroll(offset=500, sequence=1)
        send_count = self.transport.send_count

        self._emit_scroll(offset=500, sequence=2)

        self.assertEqual(self.transport.send_count, send_count)

    def test_reversal_projection_spans_back_to_the_current_viewport(self) -> None:
        spec = FixedVirtualListSpec(
            source=self.spec.source,
            controller=FixedVirtualListController(),
            render_item=self.spec.render_item,
            item_extent=self.spec.item_extent,
            axis=self.spec.axis,
            initial_mask=self.spec.initial_mask,
            retained_mask=self.spec.retained_mask,
            window_config=WindowConfig(overscan_viewports=0),
            scroll_props=self.spec.scroll_props,
        )
        runtime = Runtime(
            lambda: render_fixed_virtual_list(spec),
            transport=MemoryTransport(),
        )
        runtime.mount()

        def emit(payload, sequence):
            scroll = next(
                node
                for node in runtime._coordinator.accepted_index.values()
                if "scroll_metrics" in node.listeners
            )
            runtime.dispatch_event(
                {
                    "type": "event",
                    "seq": sequence,
                    "target": scroll.id,
                    "event": "scroll_metrics",
                    "handler": scroll.listeners["scroll_metrics"],
                    "payload": payload,
                }
            )

        emit(_scroll_payload(offset=500, velocity=1000, projected_offset=500), 1)
        emit(
            _scroll_payload(
                offset=500,
                velocity=-1000,
                projected_offset=450,
            ),
            2,
        )

        self.assertEqual(
            {
                node.props["text"]
                for node in runtime._coordinator.accepted_index.values()
                if node.kind == "Text"
            },
            {f"item-{index}" for index in range(45, 60)},
        )
        self.assertEqual(spec.controller._viewport_offset, 500.0)

    def test_projected_fling_window_stays_mounted_until_outrun(self) -> None:
        spec = _spec()
        runtime = Runtime(
            lambda: render_fixed_virtual_list(spec),
            transport=MemoryTransport(),
        )
        runtime.mount()

        def emit(payload, sequence):
            scroll = next(
                node
                for node in runtime._coordinator.accepted_index.values()
                if "scroll_metrics" in node.listeners
            )
            runtime.dispatch_event(
                {
                    "type": "event",
                    "seq": sequence,
                    "target": scroll.id,
                    "event": "scroll_metrics",
                    "handler": scroll.listeners["scroll_metrics"],
                    "payload": payload,
                }
            )

        emit(_scroll_payload(offset=0, projected_offset=900), 1)
        send_count = runtime.transport.send_count

        # Mid-fling progress inside the projected span must not re-render.
        emit(_scroll_payload(offset=300, projected_offset=900), 2)
        emit(_scroll_payload(offset=600, projected_offset=900), 3)

        self.assertEqual(runtime.transport.send_count, send_count)
        self.assertEqual(
            {
                node.props["text"]
                for node in runtime._coordinator.accepted_index.values()
                if node.kind == "Text"
            },
            {f"item-{index}" for index in range(0, 110)},
        )

        # Outrunning the projected window extends it contiguously.
        emit(_scroll_payload(offset=1000, projected_offset=1200), 4)

        self.assertEqual(
            {
                node.props["text"]
                for node in runtime._coordinator.accepted_index.values()
                if node.kind == "Text"
            },
            {f"item-{index}" for index in range(100, 140)},
        )

    def test_absent_projection_falls_back_to_offset_planning(self) -> None:
        spec = _spec()
        runtime = Runtime(
            lambda: render_fixed_virtual_list(spec),
            transport=MemoryTransport(),
        )
        runtime.mount()

        def emit(payload, sequence):
            scroll = next(
                node
                for node in runtime._coordinator.accepted_index.values()
                if "scroll_metrics" in node.listeners
            )
            runtime.dispatch_event(
                {
                    "type": "event",
                    "seq": sequence,
                    "target": scroll.id,
                    "event": "scroll_metrics",
                    "handler": scroll.listeners["scroll_metrics"],
                    "payload": payload,
                }
            )

        payload = _scroll_payload(offset=500)
        del payload["projected_offset_y"]
        emit(payload, 1)

        self.assertEqual(
            {
                node.props["text"]
                for node in runtime._coordinator.accepted_index.values()
                if node.kind == "Text"
            },
            {f"item-{index}" for index in range(40, 70)},
        )


class FixedVirtualListControllerTests(unittest.TestCase):
    def _runtime(self):
        controller = FixedVirtualListController()
        action = {
            "name": "none",
            "index": 0,
            "key": 0,
            "alignment": "start",
        }

        def app():
            item_extent = state(10.0)
            axis = state("vertical")

            def act(event):
                if action["name"] == "change_extent":
                    item_extent.set(20.0)
                elif action["name"] == "change_axis":
                    axis.set("horizontal")
                elif action["name"] == "scroll":
                    controller.scroll_to_offset(500, animated=False)
                elif action["name"] == "scroll_index":
                    controller.scroll_to_index(
                        action["index"],
                        alignment=action["alignment"],
                        animated=False,
                    )
                elif action["name"] == "scroll_key":
                    controller.scroll_to_key(
                        action["key"],
                        alignment=action["alignment"],
                        animated=False,
                    )

            spec = FixedVirtualListSpec(
                source=_source(1000),
                controller=controller,
                render_item=lambda item, index, key: Text(
                    text=item,
                    on_click=act,
                ),
                item_extent=item_extent.value,
                axis=axis.value,
                initial_mask=RenderMask.from_ranges(IndexRange(0, 5)),
                retained_mask=RenderMask(),
                window_config=WindowConfig(overscan_viewports=1),
                scroll_props=FrozenMap((("width", 100), ("height", 100))),
            )
            return render_fixed_virtual_list(spec)

        transport = SilentTransport()
        runtime = Runtime(app, transport=transport)
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        self._emit_metrics(runtime, sequence=1)
        runtime.acknowledge_native_apply(runtime.revision)
        return runtime, transport, controller, action

    @staticmethod
    def _emit_metrics(
        runtime: Runtime,
        *,
        sequence: int,
        offset: float = 0,
    ) -> None:
        scroll = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if "scroll_metrics" in node.listeners
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": sequence,
                "target": scroll.id,
                "event": "scroll_metrics",
                "handler": scroll.listeners["scroll_metrics"],
                "payload": _scroll_payload(offset=offset),
            }
        )

    @staticmethod
    def _click_cell(runtime: Runtime, *, sequence: int) -> None:
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

    def test_scroll_to_index_alignment_offsets_are_explicit(self) -> None:
        for index, alignment, expected_offset in (
            (50, "start", 500.0),
            (50, "center", 455.0),
            (50, "end", 410.0),
            (0, "end", 0.0),
            (999, "end", 9900.0),
        ):
            with self.subTest(index=index, alignment=alignment):
                runtime, _, _, action = self._runtime()
                action.update(
                    {
                        "name": "scroll_index",
                        "index": index,
                        "alignment": alignment,
                    }
                )
                self._click_cell(runtime, sequence=2)

                operation = runtime.latest_commit["ops"][-1]
                self.assertEqual(operation["op"], "scroll_to")
                self.assertEqual(operation["offset_y"], expected_offset)

    def test_scroll_to_index_nearest_is_noop_when_fully_visible(self) -> None:
        runtime, transport, _, action = self._runtime()
        send_count = len(transport.messages)
        action.update(
            {
                "name": "scroll_index",
                "index": 5,
                "alignment": "nearest",
            }
        )

        self._click_cell(runtime, sequence=2)

        self.assertEqual(len(transport.messages), send_count)

    @staticmethod
    def _scroll_ops(runtime: Runtime) -> list[dict]:
        commit = runtime.latest_commit
        if commit is None:
            return []
        return [
            op for op in commit.get("ops", []) if op.get("op") == "scroll_to"
        ]

    def test_scroll_to_index_nearest_moves_minimum_distance(self) -> None:
        runtime, _, _, action = self._runtime()
        self._emit_metrics(runtime, sequence=2, offset=400)
        runtime.acknowledge_native_apply(runtime.revision)
        action.update(
            {
                "name": "scroll_index",
                "index": 50,
                "alignment": "nearest",
            }
        )

        self._click_cell(runtime, sequence=3)

        operation = runtime.latest_commit["ops"][-1]
        self.assertEqual(operation["op"], "scroll_to")
        self.assertEqual(operation["offset_y"], 410.0)

    def test_in_flight_commit_does_not_leak_into_nearest_command(self) -> None:
        # A non-animated jump to 500 is staged but not yet acknowledged; a
        # nearest command issued while that commit is in flight must compute
        # from the last accepted actual viewport (0), where item 5 is
        # already fully visible, not from the un-acked destination (500).
        runtime, _, _, action = self._runtime()
        action["name"] = "scroll"
        self._click_cell(runtime, sequence=2)
        action.update(
            {
                "name": "scroll_index",
                "index": 5,
                "alignment": "nearest",
            }
        )
        self._click_cell(runtime, sequence=3)
        # Resolve the in-flight commit: the nearest command was a no-op
        # computed from the accepted viewport (0), so the in-flight jump is
        # the only scroll published.  A nearest computed from the un-acked
        # destination (500) would have deferred a spurious scroll_to 50.
        runtime.acknowledge_native_apply(runtime.revision)
        ops = self._scroll_ops(runtime)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[-1]["offset_y"], 500.0)
        self.assertIsNone(runtime._last_error)

    def test_in_flight_horizontal_commit_does_not_leak_into_nearest_command(
        self,
    ) -> None:
        # The horizontal axis mirrors the vertical in-flight behavior: the
        # accepted snapshot (0) drives the nearest decision, not the staged
        # destination (500).
        runtime, _, _, action = self._runtime()
        action["name"] = "change_axis"
        self._click_cell(runtime, sequence=2)
        runtime.acknowledge_native_apply(runtime.revision)
        action["name"] = "scroll"
        self._click_cell(runtime, sequence=3)
        action.update(
            {
                "name": "scroll_index",
                "index": 5,
                "alignment": "nearest",
            }
        )
        self._click_cell(runtime, sequence=4)
        runtime.acknowledge_native_apply(runtime.revision)
        ops = self._scroll_ops(runtime)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[-1]["offset_x"], 500.0)
        self.assertIsNone(runtime._last_error)

    def test_ack_promotes_destination_so_nearest_is_noop(self) -> None:
        # After the jump is acknowledged the promoted binding reports the
        # destination, so a nearest command for an item already fully
        # visible there emits nothing.
        runtime, _, controller, action = self._runtime()
        action["name"] = "scroll"
        self._click_cell(runtime, sequence=2)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(controller._binding.actual_viewport.offset, 500.0)
        ops = self._scroll_ops(runtime)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[-1]["offset_y"], 500.0)
        action.update(
            {
                "name": "scroll_index",
                "index": 50,
                "alignment": "nearest",
            }
        )
        self._click_cell(runtime, sequence=3)
        self.assertEqual(len(self._scroll_ops(runtime)), 1)
        self.assertIsNone(runtime._last_error)

    def test_known_rejection_retains_accepted_viewport_for_commands(self) -> None:
        # A rejected commit never promoted its binding: the accepted actual
        # viewport snapshot still reports the pre-command position, and
        # later commands compute from it.
        runtime, _, controller, action = self._runtime()
        action["name"] = "scroll"
        self._click_cell(runtime, sequence=2)
        rejected = runtime.revision
        runtime.report_native_failure(revision=rejected, unknown=False)
        self.assertEqual(controller._binding.actual_viewport.offset, 0.0)
        # Item 50 is only visible at the rejected destination; a nearest
        # command must scroll to it from the accepted viewport (0).
        action.update(
            {
                "name": "scroll_index",
                "index": 50,
                "alignment": "nearest",
            }
        )
        self._click_cell(runtime, sequence=3)
        ops = self._scroll_ops(runtime)
        self.assertEqual(ops[-1]["op"], "scroll_to")
        self.assertEqual(ops[-1]["offset_y"], 410.0)
        self.assertEqual(runtime._last_error, "")

    def test_known_rejection_of_native_scroll_retains_physical_metrics(
        self,
    ) -> None:
        # A native scroll outside the accepted coverage stages a render;
        # its physical metrics were observed at event time and survive the
        # rejection, while the accepted binding snapshot is unchanged.
        runtime, _, controller, _ = self._runtime()
        self._emit_metrics(runtime, sequence=2, offset=500)
        rejected = runtime.revision
        runtime.report_native_failure(revision=rejected, unknown=False)
        self.assertEqual(controller._viewport_offset, 500.0)
        self.assertEqual(controller._viewport_extent, 100.0)
        self.assertEqual(controller._binding.actual_viewport.offset, 0.0)

    def test_known_rejection_of_programmatic_jump_does_not_retain_destination(
        self,
    ) -> None:
        # A programmatic jump never touches the physical cache until the
        # native side acknowledges it, so a rejected jump leaves the cache
        # and the accepted snapshot at the pre-command position.
        runtime, _, controller, action = self._runtime()
        action["name"] = "scroll"
        self._click_cell(runtime, sequence=2)
        rejected = runtime.revision
        runtime.report_native_failure(revision=rejected, unknown=False)
        self.assertEqual(controller._viewport_offset, 0.0)
        self.assertEqual(controller._binding.actual_viewport.offset, 0.0)

    def test_no_commit_scroll_updates_physical_observation_for_nearest(
        self,
    ) -> None:
        # A native scroll fully inside the accepted coverage emits no render
        # and no acknowledgement, so the promoted binding snapshot stays
        # stale.  The observed physical viewport still advances, and a
        # nearest command must compute from it instead of the snapshot.
        runtime, transport, controller, action = self._runtime()
        send_count = len(transport.messages)
        self._emit_metrics(runtime, sequence=2, offset=100)
        self.assertEqual(len(transport.messages), send_count)
        self.assertEqual(controller._viewport_offset, 100.0)
        self.assertEqual(controller._binding.actual_viewport.offset, 0.0)
        # Item 5 spans [50, 60), above the observed window [100, 200): a
        # nearest command scrolls to 50 instead of treating it as already
        # visible at the stale snapshot 0.
        action.update(
            {
                "name": "scroll_index",
                "index": 5,
                "alignment": "nearest",
            }
        )
        self._click_cell(runtime, sequence=3)
        ops = self._scroll_ops(runtime)
        self.assertEqual(ops[-1]["op"], "scroll_to")
        self.assertEqual(ops[-1]["offset_y"], 50.0)
        self.assertIsNone(runtime._last_error)

    def test_unrelated_rerender_preserves_newer_no_commit_observation(
        self,
    ) -> None:
        # An unrelated rerender (a scroll-prop change here) acknowledges
        # with the same accepted actual snapshot and must not overwrite a
        # newer no-commit native observation with stale state.
        controller = FixedVirtualListController()

        def app():
            note = state("a")
            spec = FixedVirtualListSpec(
                source=_source(1000),
                controller=controller,
                render_item=lambda item, index, key: Text(
                    text=item,
                    on_click=lambda event: note.set("b"),
                ),
                item_extent=10,
                axis="vertical",
                initial_mask=RenderMask.from_ranges(IndexRange(0, 5)),
                retained_mask=RenderMask(),
                window_config=WindowConfig(overscan_viewports=1),
                scroll_props=FrozenMap(
                    (
                        ("width", 100),
                        ("height", 100),
                        ("content_description", note.value),
                    )
                ),
            )
            return render_fixed_virtual_list(spec)

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        self._emit_metrics(runtime, sequence=1, offset=0)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(controller._viewport_offset, 0.0)
        # A no-commit native scroll records the physical observation.
        self._emit_metrics(runtime, sequence=2, offset=100)
        self.assertEqual(controller._viewport_offset, 100.0)
        # The unrelated rerender acks with the same accepted actual
        # snapshot (0); the newer observation must survive it.
        cell = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and "click" in node.listeners
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
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(controller._viewport_offset, 100.0)
        self.assertEqual(controller._binding.actual_viewport.offset, 0.0)

    def test_horizontal_no_commit_scroll_updates_physical_observation(
        self,
    ) -> None:
        # The horizontal axis mirrors the vertical no-commit observation
        # path: the physical cache advances while the accepted snapshot
        # stays stale.
        runtime, _, controller, action = self._runtime()
        action["name"] = "change_axis"
        self._click_cell(runtime, sequence=2)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(controller._viewport_extent, 100.0)
        scroll = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if "scroll_metrics" in node.listeners
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 3,
                "target": scroll.id,
                "event": "scroll_metrics",
                "handler": scroll.listeners["scroll_metrics"],
                "payload": _horizontal_scroll_payload(offset=100),
            }
        )
        self.assertEqual(controller._viewport_offset, 100.0)
        self.assertEqual(controller._binding.actual_viewport.offset, 0.0)

    def test_preferred_actual_prefers_observation_then_snapshot(self) -> None:
        # Before the first native event the promoted snapshot (or declared
        # metrics) drives commands; a no-commit native observation wins
        # over the stale snapshot afterwards.
        runtime, _, controller, _ = self._runtime()
        self.assertEqual(
            _preferred_actual(controller, controller._binding),
            ViewportMetrics(0.0, 100.0),
        )
        self._emit_metrics(runtime, sequence=2, offset=100)
        self.assertEqual(
            _preferred_actual(controller, controller._binding),
            ViewportMetrics(100.0, 100.0),
        )

    def test_nearest_uses_shorter_edge_for_oversized_item(self) -> None:
        controller = FixedVirtualListController()
        spec = FixedVirtualListSpec(
            source=_source(10),
            controller=controller,
            render_item=lambda item, index, key: Text(
                text=item,
                on_click=lambda event: controller.scroll_to_index(
                    0,
                    alignment="nearest",
                    animated=False,
                ),
            ),
            item_extent=200,
            axis="vertical",
            initial_mask=RenderMask(),
            retained_mask=RenderMask(),
            window_config=WindowConfig(overscan_viewports=0),
        )
        runtime = Runtime(
            lambda: render_fixed_virtual_list(spec),
            transport=MemoryTransport(),
        )
        runtime.mount()
        # Native metrics at offset 80 commit a window and promote the
        # accepted viewport; the oversized item 0 spans [0, 200), so its
        # nearest end-edge (100) is closer than its start edge (0).
        self._emit_metrics(runtime, sequence=1, offset=80)
        runtime.acknowledge_native_apply(runtime.revision)
        self._click_cell(runtime, sequence=2)
        self.assertEqual(runtime.latest_commit["ops"][-1]["offset_y"], 100.0)

    def test_alignment_requires_metrics_and_short_content_clamps_to_zero(self) -> None:
        controller = FixedVirtualListController()
        spec = FixedVirtualListSpec(
            source=_source(5),
            controller=controller,
            render_item=lambda item, index, key: Text(
                text=item,
                on_click=lambda event: controller.scroll_to_index(
                    4,
                    alignment="end",
                    animated=False,
                ),
            ),
            item_extent=10,
            axis="vertical",
            initial_mask=RenderMask.from_ranges(IndexRange(0, 1)),
            retained_mask=RenderMask(),
            window_config=WindowConfig(overscan_viewports=0),
        )
        runtime = Runtime(
            lambda: render_fixed_virtual_list(spec),
            transport=MemoryTransport(),
        )
        runtime.mount()
        # No declared main-axis size and no native metrics yet: end/center/
        # nearest alignment cannot resolve a viewport extent.
        self._click_cell(runtime, sequence=1)
        self.assertIn("requires viewport metrics", runtime._last_error)

        self._emit_metrics(runtime, sequence=2, offset=0)
        runtime.acknowledge_native_apply(runtime.revision)
        self._click_cell(runtime, sequence=3)
        self.assertEqual(runtime.latest_commit["ops"][-1]["offset_y"], 0.0)

    def test_scroll_to_index_validates_inputs(self) -> None:
        _, _, controller, _ = self._runtime()
        with self.assertRaises(IndexError):
            controller.scroll_to_index(1000, alignment="start", animated=False)
        with self.assertRaises(ValueError):
            controller.scroll_to_index(0, alignment="middle", animated=False)
        with self.assertRaises(TypeError):
            controller.scroll_to_index(0, alignment="start", animated=1)

    def test_scroll_to_key_default_index_keys_resolves_in_o1(self) -> None:
        controller = FixedVirtualListController()
        spec = FixedVirtualListSpec(
            source=SequenceDataSource(tuple(range(1000))),
            controller=controller,
            render_item=lambda item, index, key: Text(
                text=str(item),
                on_click=lambda event: controller.scroll_to_key(
                    7, alignment="start", animated=False
                ),
            ),
            item_extent=10,
            axis="vertical",
            initial_mask=RenderMask.from_ranges(IndexRange(0, 5)),
            retained_mask=RenderMask(),
            window_config=WindowConfig(overscan_viewports=1),
            scroll_props=FrozenMap((("width", 300), ("height", 100))),
        )
        runtime = Runtime(
            lambda: render_fixed_virtual_list(spec),
            transport=MemoryTransport(),
        )
        runtime.mount()
        self._click_cell(runtime, sequence=1)
        operation = runtime.latest_commit["ops"][-1]
        self.assertEqual(operation["op"], "scroll_to")
        self.assertEqual(operation["offset_y"], 70.0)

    def test_scroll_to_key_realized_custom_key_uses_registry(self) -> None:
        controller = FixedVirtualListController()
        key_reads = []

        def key_for_item(item, index):
            key_reads.append(index)
            return f"key-{index}"

        spec = FixedVirtualListSpec(
            source=_source(1000),
            controller=controller,
            render_item=lambda item, index, key: Text(
                text=item,
                on_click=lambda event: controller.scroll_to_key(
                    "key-5", alignment="start", animated=False
                ),
            ),
            item_extent=10,
            axis="vertical",
            initial_mask=RenderMask.from_ranges(IndexRange(0, 5)),
            retained_mask=RenderMask(),
            window_config=WindowConfig(overscan_viewports=1),
            scroll_props=FrozenMap((("width", 300), ("height", 100))),
            key_for_item=key_for_item,
        )
        runtime = Runtime(
            lambda: render_fixed_virtual_list(spec),
            transport=MemoryTransport(),
        )
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        reads_before = len(key_reads)
        self._click_cell(runtime, sequence=1)
        operation = runtime.latest_commit["ops"][-1]
        self.assertEqual(operation["offset_y"], 50.0)
        # The accepted registry resolved the key; the re-render read only
        # the new realized window, never the 1000-item source.
        self.assertLess(len(key_reads), 100)
        self.assertGreaterEqual(len(key_reads), reads_before)

    def test_scroll_to_key_unknown_raises_without_scan(self) -> None:
        controller = FixedVirtualListController()
        key_reads = []

        def key_for_item(item, index):
            key_reads.append(index)
            return f"key-{index}"

        spec = FixedVirtualListSpec(
            source=_source(1000),
            controller=controller,
            render_item=lambda item, index, key: Text(
                text=item,
                on_click=lambda event: controller.scroll_to_key(
                    "key-900", alignment="start", animated=False
                ),
            ),
            item_extent=10,
            axis="vertical",
            initial_mask=RenderMask.from_ranges(IndexRange(0, 5)),
            retained_mask=RenderMask(),
            window_config=WindowConfig(overscan_viewports=1),
            scroll_props=FrozenMap((("width", 300), ("height", 100))),
            key_for_item=key_for_item,
        )
        runtime = Runtime(
            lambda: render_fixed_virtual_list(spec),
            transport=MemoryTransport(),
        )
        runtime.mount()
        runtime.acknowledge_native_apply(runtime.revision)
        self._click_cell(runtime, sequence=1)
        self.assertIn("not realized", runtime._last_error)

    def test_scroll_to_key_validates_noncanonical_key(self) -> None:
        _, _, controller, _ = self._runtime()
        with self.assertRaises(TypeError):
            controller.scroll_to_key(object(), alignment="start", animated=False)

    def test_unmounted_fixed_controller_raises(self) -> None:
        controller = FixedVirtualListController()
        with self.assertRaisesRegex(RuntimeError, "not mounted"):
            controller.scroll_to_key(5, alignment="start", animated=False)

    def test_binding_promotes_only_after_native_ack(self) -> None:
        runtime, _, controller, action = self._runtime()
        self.assertEqual(controller._binding.layout.item_extent, 10.0)

        action["name"] = "change_extent"
        self._click_cell(runtime, sequence=2)

        self.assertEqual(controller._binding.layout.item_extent, 10.0)
        runtime.acknowledge_native_apply(runtime.revision)
        self.assertEqual(controller._binding.layout.item_extent, 20.0)

        action["name"] = "scroll"
        self._click_cell(runtime, sequence=3)
        self.assertEqual(runtime.latest_commit["ops"][-1]["op"], "scroll_to")
        self.assertEqual(
            {
                node.props["text"]
                for node in runtime._coordinator.candidate_index.values()
                if node.kind == "Text"
            },
            {f"item-{index}" for index in range(20, 35)},
        )

    def test_axis_and_ref_replace_atomically_after_ack(self) -> None:
        runtime, _, controller, action = self._runtime()
        old_handle = controller._scroll_ref.current
        action["name"] = "change_axis"
        self._click_cell(runtime, sequence=2)

        self.assertEqual(controller._binding.axis, "vertical")
        self.assertIs(controller._scroll_ref.current, old_handle)
        runtime.acknowledge_native_apply(runtime.revision)

        self.assertEqual(controller._binding.axis, "horizontal")
        self.assertFalse(old_handle.valid)
        self.assertEqual(controller._scroll_ref.current.kind, "HorizontalScroll")
        # The promoted binding carries the declared horizontal viewport
        # (width 100) into the cached physical viewport.
        self.assertEqual(controller._viewport_offset, 0.0)
        self.assertEqual(controller._viewport_extent, 100.0)

        action["name"] = "scroll"
        self._click_cell(runtime, sequence=3)
        self.assertEqual(runtime.latest_commit["ops"][-1]["offset_x"], 500.0)
        self.assertEqual(
            {
                node.props["text"]
                for node in runtime._coordinator.candidate_index.values()
                if node.kind == "Text"
            },
            {f"item-{index}" for index in range(40, 70)},
        )

    def test_old_policy_metrics_replan_after_geometry_commit_ack(self) -> None:
        runtime, _, _, action = self._runtime()
        self._emit_metrics(runtime, sequence=2, offset=500)
        runtime.acknowledge_native_apply(runtime.revision)

        action["name"] = "change_extent"
        self._click_cell(runtime, sequence=3)
        geometry_revision = runtime.revision
        self._emit_metrics(runtime, sequence=4, offset=600)

        runtime.acknowledge_native_apply(geometry_revision)

        # The geometry replan already mounted a window that covers the
        # newer offset, so the in-flight metric is absorbed without a
        # separate commit.
        self.assertEqual(
            {
                node.props["text"]
                for node in runtime._coordinator.accepted_index.values()
                if node.kind == "Text"
            },
            {f"item-{index}" for index in range(20, 35)},
        )

    def test_unknown_reset_snapshot_restores_virtual_list_offset(self) -> None:
        runtime, transport, _, action = self._runtime()
        action["name"] = "scroll"
        self._click_cell(runtime, sequence=2)
        uncertain_revision = runtime.revision

        runtime.report_native_failure(
            revision=uncertain_revision,
            unknown=True,
        )

        root_props = next(
            operation["props"]
            for operation in transport.messages[-1]["ops"]
            if operation.get("op") == "set_props" and operation.get("id") == 1
        )
        self.assertEqual(root_props["_virtual_list_initial_offset"], 500.0)
        self.assertFalse(
            any(
                operation.get("op") == "scroll_to"
                for operation in transport.messages[-1]["ops"]
            )
        )

    def test_unknown_result_promotes_binding_only_after_reset_ack(self) -> None:
        runtime, _, controller, action = self._runtime()
        action["name"] = "change_extent"
        self._click_cell(runtime, sequence=2)
        uncertain_revision = runtime.revision

        runtime.report_native_failure(
            revision=uncertain_revision,
            unknown=True,
        )

        self.assertEqual(controller._binding.layout.item_extent, 10.0)
        reset_revision = runtime.revision
        self.assertGreater(reset_revision, uncertain_revision)
        runtime.acknowledge_native_apply(reset_revision)
        self.assertEqual(controller._binding.layout.item_extent, 20.0)

    def test_rejected_render_preserves_accepted_binding(self) -> None:
        runtime, _, controller, action = self._runtime()
        action["name"] = "change_extent"
        self._click_cell(runtime, sequence=2)
        rejected_revision = runtime.revision

        runtime.report_native_failure(
            revision=rejected_revision,
            unknown=False,
        )

        self.assertEqual(controller._binding.layout.item_extent, 10.0)
        action["name"] = "scroll"
        self._click_cell(runtime, sequence=3)
        self.assertEqual(runtime.latest_commit["ops"][-1]["op"], "scroll_to")
        self.assertEqual(
            {
                node.props["text"]
                for node in runtime._coordinator.candidate_index.values()
                if node.kind == "Text"
            },
            {f"item-{index}" for index in range(40, 70)},
        )

    def test_cached_list_keeps_binding_during_unrelated_render(self) -> None:
        controller = FixedVirtualListController()
        spec = FixedVirtualListSpec(
            source=_source(10),
            controller=controller,
            render_item=lambda item, index, key: Text(text=item),
            item_extent=10,
            axis="vertical",
            initial_mask=RenderMask.from_ranges(IndexRange(0, 5)),
            retained_mask=RenderMask(),
            window_config=WindowConfig(overscan_viewports=1),
        )

        def app():
            count = state(0)
            return Column(
                render_fixed_virtual_list(spec),
                Text(
                    text=f"count-{count.value}",
                    on_click=lambda event: count.set(count.value + 1),
                ),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        handle = controller._scroll_ref.current
        sibling = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and node.props["text"] == "count-0"
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 1,
                "target": sibling.id,
                "event": "click",
                "handler": sibling.listeners["click"],
                "payload": {},
            }
        )

        self.assertIsNotNone(controller._binding)
        self.assertIs(controller._scroll_ref.current, handle)
        self.assertTrue(handle.valid)

    def test_policy_only_change_promotes_without_native_commit(self) -> None:
        controller = FixedVirtualListController()

        def app():
            config = state(WindowConfig(overscan_viewports=1))
            spec = FixedVirtualListSpec(
                source=_source(10),
                controller=controller,
                render_item=lambda item, index, key: Text(
                    text=item,
                    on_click=lambda event: config.set(WindowConfig(overscan_viewports=2)),
                ),
                item_extent=10,
                axis="vertical",
                initial_mask=RenderMask.from_ranges(IndexRange(0, 5)),
                retained_mask=RenderMask(),
                window_config=config.value,
            )
            return render_fixed_virtual_list(spec)

        transport = MemoryTransport()
        runtime = Runtime(app, transport=transport)
        runtime.mount()
        send_count = transport.send_count
        self._click_cell(runtime, sequence=1)

        self.assertEqual(transport.send_count, send_count)
        self.assertEqual(
            controller._binding.window_config,
            WindowConfig(overscan_viewports=2),
        )

    def test_controller_unbinds_when_list_is_removed(self) -> None:
        controller = FixedVirtualListController()

        def app():
            visible = state(True)
            if not visible.value:
                return Text(text="gone")
            spec = FixedVirtualListSpec(
                source=_source(10),
                controller=controller,
                render_item=lambda item, index, key: Text(
                    text=item,
                    on_click=lambda event: visible.set(False),
                ),
                item_extent=10,
                axis="vertical",
                initial_mask=RenderMask.from_ranges(IndexRange(0, 5)),
                retained_mask=RenderMask(),
                window_config=WindowConfig(overscan_viewports=1),
            )
            return render_fixed_virtual_list(spec)

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        self._click_cell(runtime, sequence=1)

        self.assertIsNone(controller._binding)
        self.assertIsNone(controller._scroll_ref.current)

    def test_rejected_render_does_not_leak_candidate_key_registry(self) -> None:
        controller = FixedVirtualListController()
        spec = FixedVirtualListSpec(
            source=_source(1000),
            controller=controller,
            render_item=lambda item, index, key: Text(text=item),
            item_extent=10,
            axis="vertical",
            initial_mask=RenderMask.from_ranges(IndexRange(0, 5)),
            retained_mask=RenderMask(),
            window_config=WindowConfig(overscan_viewports=1),
            scroll_props=FrozenMap((("width", 300), ("height", 100))),
            key_for_item=lambda item, index: index,
        )
        runtime = Runtime(
            lambda: render_fixed_virtual_list(spec),
            transport=SilentTransport(),
        )
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        # The declared viewport realizes indices 0-19 on mount.
        self.assertEqual(
            set(controller._key_registry.key_to_index),
            {f"key-{index}" for index in range(20)},
        )
        scroll = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if "scroll_metrics" in node.listeners
        )
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 1,
                "target": scroll.id,
                "event": "scroll_metrics",
                "handler": scroll.listeners["scroll_metrics"],
                "payload": _scroll_payload(offset=500),
            }
        )
        uncertain = runtime.revision
        runtime.report_native_failure(revision=uncertain, unknown=False)
        # The candidate cloned the registry and mutated the clone; the
        # accepted mappings are untouched by the rejected render.
        self.assertEqual(
            set(controller._key_registry.key_to_index),
            {f"key-{index}" for index in range(20)},
        )
        self.assertNotIn("key-50", controller._key_registry.key_to_index)


if __name__ == "__main__":
    unittest.main()
