from __future__ import annotations

import unittest

from vyne import Column, Text, state
from vyne._lists import (
    FixedVirtualListController,
    FixedVirtualListSpec,
    IndexRange,
    RenderMask,
    TupleDataSource,
    WindowConfig,
    compose_fixed_window,
    render_fixed_virtual_list,
)
from vyne.events import latest
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport
from vyne.values import FrozenMap


def _source(count: int) -> TupleDataSource:
    return TupleDataSource(
        items=tuple(f"item-{index}" for index in range(count)),
        keys=tuple(f"key-{index}" for index in range(count)),
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
        window_config=WindowConfig(1, 1, 0, 0, 0),
        scroll_props=FrozenMap((
            ("width", 300),
            ("height", 100),
        )),
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
    payload.update({
        "offset_x": offset,
        "projected_offset_x": offset,
        "projected_offset_y": 0.0,
        "viewport_width": extent,
        "content_width": 10_000.0,
    })
    return payload


class TupleDataSourceTests(unittest.TestCase):
    def test_keys_are_unique_and_canonical(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate list key"):
            TupleDataSource(items=("a", "b"), keys=("same", "same"))
        with self.assertRaisesRegex(TypeError, "list key at index 0"):
            TupleDataSource(items=("a",), keys=(object(),))


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
            child for child in content.children
            if child.props["key"][0] == "__vyne_list_cell__"
        ]
        self.assertEqual(len(cells), 5)
        self.assertEqual(cells[0].children[0].props["text"], "item-20")
        self.assertEqual(cells[-1].children[0].props["text"], "item-24")
        self.assertEqual(content.children[0].props["height"], 200.0)
        self.assertEqual(content.children[-1].props["height"], 750.0)
        self.assertEqual(element.props["_virtual_list_initial_offset"], 0.0)
        self.assertNotIn("_virtual_list_coverage_enabled", element.props)

    def test_retained_cells_keep_disjoint_regions_without_coverage_markers(self) -> None:
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
        self.assertFalse(any(
            child.props.get("_virtual_list_coverage_cell", False)
            for child in element.children[0].children
        ))


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
            window_config=WindowConfig(1, 1, 0, 0, 0),
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
            child for child in content.children
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
            node for node in runtime._coordinator.accepted_index.values()
            if "scroll_metrics" in node.listeners
        )
        runtime.dispatch_event({
            "type": "event",
            "seq": 1,
            "target": scroll.id,
            "event": "scroll_metrics",
            "handler": scroll.listeners["scroll_metrics"],
            "payload": _horizontal_scroll_payload(offset=500),
        })

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
            node for node in runtime._coordinator.accepted_index.values()
            if "scroll_metrics" in node.listeners
        )
        runtime.dispatch_event({
            "type": "event",
            "seq": 1,
            "target": scroll.id,
            "event": "scroll_metrics",
            "handler": scroll.listeners["scroll_metrics"],
            "payload": _horizontal_scroll_payload(offset=0),
        })
        cell = next(
            node for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and "click" in node.listeners
        )
        runtime.dispatch_event({
            "type": "event",
            "seq": 2,
            "target": cell.id,
            "event": "click",
            "handler": cell.listeners["click"],
            "payload": {},
        })

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
        self.runtime.dispatch_event({
            "type": "event",
            "seq": sequence,
            "target": target,
            "event": "scroll_metrics",
            "handler": handler,
            "payload": _scroll_payload(offset=offset),
        })

    def test_initial_native_mirror_covers_declared_viewport_and_overscan(self) -> None:
        text_nodes = [
            node for node in self.runtime._coordinator.accepted_index.values()
            if node.kind == "Text"
        ]

        self.assertEqual(len(text_nodes), 20)
        self.assertLess(len(self.runtime._coordinator.accepted_index), 50)

    def test_scroll_replaces_window_without_rendering_all_data(self) -> None:
        initial_send_count = self.transport.send_count

        self._emit_scroll(offset=500, sequence=1)

        text_nodes = [
            node for node in self.runtime._coordinator.accepted_index.values()
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
            window_config=WindowConfig(0, 0, 0.2, 3, 2),
            scroll_props=self.spec.scroll_props,
        )
        runtime = Runtime(
            lambda: render_fixed_virtual_list(spec),
            transport=MemoryTransport(),
        )
        runtime.mount()

        def emit(payload, sequence):
            scroll = next(
                node for node in runtime._coordinator.accepted_index.values()
                if "scroll_metrics" in node.listeners
            )
            runtime.dispatch_event({
                "type": "event",
                "seq": sequence,
                "target": scroll.id,
                "event": "scroll_metrics",
                "handler": scroll.listeners["scroll_metrics"],
                "payload": payload,
            })

        emit(_scroll_payload(offset=500, velocity=1000, projected_offset=500), 1)
        emit(_scroll_payload(
            offset=500,
            velocity=-1000,
            projected_offset=450,
        ), 2)

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
                node for node in runtime._coordinator.accepted_index.values()
                if "scroll_metrics" in node.listeners
            )
            runtime.dispatch_event({
                "type": "event",
                "seq": sequence,
                "target": scroll.id,
                "event": "scroll_metrics",
                "handler": scroll.listeners["scroll_metrics"],
                "payload": payload,
            })

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
                node for node in runtime._coordinator.accepted_index.values()
                if "scroll_metrics" in node.listeners
            )
            runtime.dispatch_event({
                "type": "event",
                "seq": sequence,
                "target": scroll.id,
                "event": "scroll_metrics",
                "handler": scroll.listeners["scroll_metrics"],
                "payload": payload,
            })

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
    class SilentTransport:
        preflights_commits = False

        def __init__(self) -> None:
            self.messages: list[dict] = []

        def send(self, message: dict) -> None:
            self.messages.append(message)

    def _runtime(self):
        controller = FixedVirtualListController()
        action = {
            "name": "none",
            "index": 0,
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
                window_config=WindowConfig(1, 1, 0, 0, 0),
                scroll_props=FrozenMap((("width", 100), ("height", 100))),
            )
            return render_fixed_virtual_list(spec)

        transport = self.SilentTransport()
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
            node for node in runtime._coordinator.accepted_index.values()
            if "scroll_metrics" in node.listeners
        )
        runtime.dispatch_event({
            "type": "event",
            "seq": sequence,
            "target": scroll.id,
            "event": "scroll_metrics",
            "handler": scroll.listeners["scroll_metrics"],
            "payload": _scroll_payload(offset=offset),
        })

    @staticmethod
    def _click_cell(runtime: Runtime, *, sequence: int) -> None:
        cell = next(
            node for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and "click" in node.listeners
        )
        runtime.dispatch_event({
            "type": "event",
            "seq": sequence,
            "target": cell.id,
            "event": "click",
            "handler": cell.listeners["click"],
            "payload": {},
        })

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
                action.update({
                    "name": "scroll_index",
                    "index": index,
                    "alignment": alignment,
                })
                self._click_cell(runtime, sequence=2)

                operation = runtime.latest_commit["ops"][-1]
                self.assertEqual(operation["op"], "scroll_to")
                self.assertEqual(operation["offset_y"], expected_offset)

    def test_scroll_to_index_nearest_is_noop_when_fully_visible(self) -> None:
        runtime, transport, _, action = self._runtime()
        send_count = len(transport.messages)
        action.update({
            "name": "scroll_index",
            "index": 5,
            "alignment": "nearest",
        })

        self._click_cell(runtime, sequence=2)

        self.assertEqual(len(transport.messages), send_count)

    def test_scroll_to_index_nearest_moves_minimum_distance(self) -> None:
        runtime, _, _, action = self._runtime()
        self._emit_metrics(runtime, sequence=2, offset=400)
        runtime.acknowledge_native_apply(runtime.revision)
        action.update({
            "name": "scroll_index",
            "index": 50,
            "alignment": "nearest",
        })

        self._click_cell(runtime, sequence=3)

        operation = runtime.latest_commit["ops"][-1]
        self.assertEqual(operation["op"], "scroll_to")
        self.assertEqual(operation["offset_y"], 410.0)

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
            initial_mask=RenderMask.from_ranges(IndexRange(0, 1)),
            retained_mask=RenderMask(),
            window_config=WindowConfig(0, 0, 0, 0, 0),
            scroll_props=FrozenMap((("height", 100),)),
        )
        runtime = Runtime(
            lambda: render_fixed_virtual_list(spec),
            transport=MemoryTransport(),
        )
        runtime.mount()
        self._emit_metrics(runtime, sequence=1, offset=0)
        send_count = runtime.transport.send_count
        self._click_cell(runtime, sequence=2)
        self.assertEqual(runtime.transport.send_count, send_count)

        self._emit_metrics(runtime, sequence=3, offset=80)
        self._click_cell(runtime, sequence=4)
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
            initial_mask=RenderMask.from_ranges(IndexRange(0, 5)),
            retained_mask=RenderMask(),
            window_config=WindowConfig(0, 0, 0, 0, 0),
            scroll_props=FrozenMap((("height", 100),)),
        )
        runtime = Runtime(
            lambda: render_fixed_virtual_list(spec),
            transport=MemoryTransport(),
        )
        runtime.mount()
        self._click_cell(runtime, sequence=1)
        self.assertIn("requires viewport metrics", runtime._last_error)

        self._emit_metrics(runtime, sequence=2, offset=0)
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
        self.assertIsNone(controller._viewport_extent)

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
            if operation.get("op") == "set_props"
            and operation.get("id") == 1
        )
        self.assertEqual(root_props["_virtual_list_initial_offset"], 500.0)
        self.assertFalse(any(
            operation.get("op") == "scroll_to"
            for operation in transport.messages[-1]["ops"]
        ))

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
            window_config=WindowConfig(1, 1, 0, 0, 0),
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
            node for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and node.props["text"] == "count-0"
        )
        runtime.dispatch_event({
            "type": "event",
            "seq": 1,
            "target": sibling.id,
            "event": "click",
            "handler": sibling.listeners["click"],
            "payload": {},
        })

        self.assertIsNotNone(controller._binding)
        self.assertIs(controller._scroll_ref.current, handle)
        self.assertTrue(handle.valid)

    def test_policy_only_change_promotes_without_native_commit(self) -> None:
        controller = FixedVirtualListController()

        def app():
            config = state(WindowConfig(1, 1, 0, 0, 0))
            spec = FixedVirtualListSpec(
                source=_source(10),
                controller=controller,
                render_item=lambda item, index, key: Text(
                    text=item,
                    on_click=lambda event: config.set(WindowConfig(2, 3, 0, 0, 0)),
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
            WindowConfig(2, 3, 0, 0, 0),
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
                window_config=WindowConfig(1, 1, 0, 0, 0),
            )
            return render_fixed_virtual_list(spec)

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        self._click_cell(runtime, sequence=1)

        self.assertIsNone(controller._binding)
        self.assertIsNone(controller._scroll_ref.current)


if __name__ == "__main__":
    unittest.main()
