"""M3 native sticky contract tests for the generic virtual list.

These tests pin the private Python→native metadata that drives the native
sticky headers/footers:

- the schema owns four private Box-only props (`_virtual_content` and the
  `_virtual_sticky_*` trio), excluded from generated public constructor
  stubs by underscore naming;
- the generic engine marks its content Box only when the accepted window
  includes a sticky placement (non-sticky lists carry no marker) and
  publishes sticky boundary/edge metadata only on sticky cell wrappers
  (natural `translation_x/y` unchanged, no Python scroll callback);
- non-sticky wrappers carry no sticky props, and removing stickiness emits
  `remove_prop` ops (reconciliation), so pooled/reused wrappers cannot
  retain stale metadata.
"""

from __future__ import annotations

import unittest

from vyne import Column, Text, state
from vyne.lists import VirtualList
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport
from vyne.spec.schema_v2 import (
    ALL_PROPS,
    PROPS_BY_KIND,
    PRIMITIVE_KINDS,
)

from tests.support.list_conformance import SectionedLayout

_PRIVATE_STICKY_PROPS = frozenset({
    "_virtual_content",
    "_virtual_sticky_edge",
    "_virtual_sticky_boundary_start",
    "_virtual_sticky_boundary_end",
})


def _cell_by_key(runtime: Runtime, key: object) -> dict:
    return next(
        node.props
        for node in runtime._coordinator.accepted_index.values()
        if node.kind == "Box"
        and node.key is not None
        and node.key[0] == "__vyne_virtual_cell__"
        and node.key[1] == key
    )


def _content_props(runtime: Runtime) -> dict:
    return next(
        node.props
        for node in runtime._coordinator.accepted_index.values()
        if node.kind == "Box" and node.key == ("__vyne_virtual_content__",)
    )


def _cell_keys(runtime: Runtime) -> set:
    return {
        node.key[1]
        for node in runtime._coordinator.accepted_index.values()
        if node.kind == "Box"
        and node.key is not None
        and node.key[0] == "__vyne_virtual_cell__"
    }


def _scroll_payload(offset: float, *, extent: float = 100) -> dict:
    return {
        "offset_x": 0.0,
        "offset_y": offset,
        "viewport_width": 300.0,
        "viewport_height": extent,
        "content_width": 300.0,
        "content_height": 10_000_000.0,
        "velocity_x": 0.0,
        "velocity_y": 0.0,
        "projected_offset_x": 0.0,
        "projected_offset_y": offset,
        "event_time": 10,
    }


def _emit_scroll(runtime: Runtime, *, offset: float, seq: int = 1) -> None:
    scroll = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if "scroll_metrics" in node.listeners
    )
    runtime.dispatch_event({
        "type": "event",
        "seq": seq,
        "target": scroll.id,
        "event": "scroll_metrics",
        "handler": scroll.listeners["scroll_metrics"],
        "payload": _scroll_payload(offset),
    })


def _cell(item: int, index: int) -> Text:
    return Text(
        text=str(item),
        content_description=f"item-{item}",
    )


class StickySchemaTests(unittest.TestCase):
    """The private schema props exist, are Box-only, and stay off stubs."""

    def test_private_props_are_box_only(self) -> None:
        for name in _PRIVATE_STICKY_PROPS:
            self.assertIn(name, ALL_PROPS, name)
            self.assertIn(name, PROPS_BY_KIND["Box"], name)
            for kind in PRIMITIVE_KINDS:
                if kind == "Box":
                    continue
                self.assertNotIn(
                    name,
                    PROPS_BY_KIND[kind],
                    f"{name} must be Box-only (leaked to {kind})",
                )

    def test_private_props_have_unique_wire_names_and_drop_default(self) -> None:
        seen: set[str] = set()
        for name in _PRIVATE_STICKY_PROPS:
            spec = ALL_PROPS[name]
            self.assertTrue(spec.drop_default, f"{name} must drop its default")
            self.assertIsNotNone(spec.wire_name, f"{name} needs a wire name")
            self.assertNotIn(spec.wire_name, seen, f"duplicate wire {spec.wire_name}")
            seen.add(spec.wire_name)

    def test_private_props_absent_from_public_stub(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        stub = root / "packages" / "vyne" / "src" / "vyne" / "elements.pyi"
        text = stub.read_text(encoding="utf-8")
        for name in _PRIVATE_STICKY_PROPS:
            self.assertNotIn(name, text, f"{name} leaked into elements.pyi")

    def test_private_prop_value_domains(self) -> None:
        from vyne.elements import Box
        from vyne.lowering import lower_element

        with self.assertRaises(ValueError):
            lower_element(Box(_virtual_sticky_boundary_start=-1))
        # NaN is rejected at element construction by the bridge guard.
        with self.assertRaises(TypeError):
            Box(_virtual_sticky_boundary_end=float("nan"))
        with self.assertRaises(ValueError):
            lower_element(Box(_virtual_sticky_edge="middle"))
        with self.assertRaises(TypeError):
            lower_element(Box(_virtual_content=1))
        # Valid forms lower cleanly.
        lower_element(Box(_virtual_content=True))
        lower_element(Box(_virtual_sticky_edge="end"))
        # None values are stripped at lowering.
        lowered = lower_element(Box(_virtual_sticky_edge=None))
        self.assertNotIn("_virtual_sticky_edge", lowered.props)


class StickyCommitTests(unittest.TestCase):
    """The engine publishes the metadata on the wire tree."""

    def test_nonsticky_list_content_is_not_marked(self) -> None:
        from vyne.lists import FixedLinearLayout

        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(1000)),
                    render_item=_cell,
                    layout=FixedLinearLayout(10, "vertical"),
                    key_for_item=lambda item, index: item,
                    width=300,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        # No sticky placement is selected, so the native host must not run
        # the per-frame sticky pass: the content Box carries no marker.
        self.assertNotIn("_virtual_content", _content_props(runtime))
        # Scrolling far (still no sticky) keeps the marker absent.
        _emit_scroll(runtime, offset=500, seq=1)
        self.assertNotIn("_virtual_content", _content_props(runtime))

    def test_nonsticky_initial_window_then_scroll_into_section_marks(self) -> None:
        """A window with no sticky candidate is unmarked; the first scroll
        that activates a section composes the sticky and marks the content
        in the same commit."""
        layout = SectionedLayout(
            section_size=8,
            header_extent=30,
            row_extent=20,
            footer_extent=40,
        )
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(300)),
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
        # Initial window covers section 0 (0..[230,460)), so its sticky
        # header/footer are selected and the marker is present.
        self.assertTrue(_content_props(runtime)["_virtual_content"])

    def test_sticky_list_content_marker_follows_selected_stickies(self) -> None:
        layout = SectionedLayout(
            section_size=8,
            header_extent=30,
            row_extent=20,
            footer_extent=40,
        )
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(300)),
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
        # A sticky window is marked.
        self.assertTrue(_content_props(runtime)["_virtual_content"])
        # Scroll to a section; still sticky, still marked.
        _emit_scroll(runtime, offset=500, seq=1)
        self.assertTrue(_content_props(runtime)["_virtual_content"])

    def test_vertical_sticky_metadata_on_sectioned_list(self) -> None:
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
        # Initial window covers section 0 only: its start header (0) and end
        # footer (9) are sticky and retained together.
        header = _cell_by_key(runtime, 0)
        self.assertEqual(header["_virtual_sticky_edge"], "start")
        self.assertEqual(header["_virtual_sticky_boundary_start"], 0.0)
        self.assertEqual(header["_virtual_sticky_boundary_end"], 230.0)
        # Natural translation is unchanged by the sticky metadata.
        self.assertEqual(header["translation_y"], 0.0)
        footer = _cell_by_key(runtime, 9)
        self.assertEqual(footer["_virtual_sticky_edge"], "end")
        self.assertEqual(footer["_virtual_sticky_boundary_start"], 0.0)
        self.assertEqual(footer["_virtual_sticky_boundary_end"], 230.0)
        # A plain body row carries no sticky props.
        body = _cell_by_key(runtime, 4)
        self.assertNotIn("_virtual_sticky_edge", body)
        self.assertNotIn("_virtual_sticky_boundary_start", body)
        self.assertNotIn("_virtual_sticky_boundary_end", body)
        # A window with a sticky placement marks the content Box.
        self.assertTrue(_content_props(runtime)["_virtual_content"])

    def test_content_marker_present_and_nonsticky_cells_clean(self) -> None:
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(1000)),
                    render_item=_cell,
                    layout=SectionedLayout(section_size=8),
                    key_for_item=lambda item, index: item,
                    width=300,
                    height=100,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        self.assertTrue(_content_props(runtime)["_virtual_content"])
        sticky_slots = {0, 9}
        for key in _cell_keys(runtime):
            props = _cell_by_key(runtime, key)
            if key in sticky_slots:
                self.assertIn("_virtual_sticky_edge", props)
            else:
                self.assertNotIn("_virtual_sticky_edge", props)
                self.assertNotIn("_virtual_sticky_boundary_start", props)
                self.assertNotIn("_virtual_sticky_boundary_end", props)

    def test_scrolling_preserves_sticky_metadata_naturally(self) -> None:
        layout = SectionedLayout(
            section_size=8,
            header_extent=30,
            row_extent=20,
            footer_extent=40,
        )
        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(300)),
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
        _emit_scroll(runtime, offset=500, seq=1)
        # Section 2 spans [460, 690); the viewport [500, 560) activates it, so
        # its header (20) and footer (29) are both retained with metadata.
        header = _cell_by_key(runtime, 20)
        self.assertEqual(header["_virtual_sticky_edge"], "start")
        self.assertEqual(header["translation_y"], 460.0)
        footer = _cell_by_key(runtime, 29)
        self.assertEqual(footer["_virtual_sticky_edge"], "end")
        self.assertEqual(footer["translation_y"], 650.0)


    def test_horizontal_sticky_metadata_on_cell_wrappers(self) -> None:
        from vyne._lists.contracts import (
            LayoutRequest,
            LayoutResult,
            StickyConstraint,
            VirtualPlacement,
        )

        class HorizontalSectionLayout:
            """Two-row sections along x; each section has a start header and
            an end footer on the cross axis."""

            section_extent = 40.0
            per_section = 4  # header + 2 body rows + footer

            def place(self, request: LayoutRequest) -> LayoutResult:
                item_count = request.item_count
                sections = (
                    (item_count + self.per_section - 1) // self.per_section
                    if item_count
                    else 0
                )
                placements = []
                for section in range(sections):
                    top = section * self.section_extent
                    bottom = top + self.section_extent
                    for slot in range(self.per_section):
                        index = section * self.per_section + slot
                        if index >= item_count:
                            continue
                        if slot == 0:
                            x, width = top, 10.0
                            sticky = StickyConstraint(
                                "start", top, bottom
                            )
                        elif slot <= 2:
                            x = top + 10.0 + (slot - 1) * 10.0
                            width, sticky = 10.0, None
                        else:
                            x = top + 30.0
                            width = 10.0
                            sticky = StickyConstraint("end", top, bottom)
                        placements.append(
                            VirtualPlacement(
                                index,
                                x,
                                0.0,
                                width,
                                request.viewport.height,
                                sticky,
                            )
                        )
                return LayoutResult(
                    sections * self.section_extent,
                    request.viewport.height,
                    tuple(placements),
                )

            def offset_for_index(
                self,
                index: int,
                *,
                measurement_for_index,
            ) -> tuple[float, float]:
                return (float(index) * 10.0, 0.0)

        runtime = Runtime(
            lambda: Column(
                VirtualList(
                    tuple(range(30)),
                    render_item=_cell,
                    layout=HorizontalSectionLayout(),
                    key_for_item=lambda item, index: item,
                    axis="horizontal",
                    width=300,
                    height=60,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        header = _cell_by_key(runtime, 0)
        self.assertEqual(header["_virtual_sticky_edge"], "start")
        self.assertEqual(header["_virtual_sticky_boundary_start"], 0.0)
        self.assertEqual(header["_virtual_sticky_boundary_end"], 40.0)
        # Natural x translation is unchanged by sticky metadata.
        self.assertEqual(header["translation_x"], 0.0)
        footer = _cell_by_key(runtime, 3)
        self.assertEqual(footer["_virtual_sticky_edge"], "end")
        self.assertEqual(footer["_virtual_sticky_boundary_start"], 0.0)
        self.assertEqual(footer["_virtual_sticky_boundary_end"], 40.0)
        body = _cell_by_key(runtime, 1)
        self.assertNotIn("_virtual_sticky_edge", body)
        self.assertTrue(_content_props(runtime)["_virtual_content"])


class StickyReconciliationTests(unittest.TestCase):
    """Removing stickiness reconciles the same wrapper without stale props."""

    def test_sticky_props_are_removed_when_cell_loses_stickiness(self) -> None:
        from vyne._lists.contracts import (
            LayoutRequest,
            LayoutResult,
            StickyConstraint,
            VirtualPlacement,
        )

        class ToggleStickyLayout:
            """Fixed-extent linear layout; index 0 is a start-sticky header
            only while item_count > 5."""

            extent = 10.0

            def place(self, request: LayoutRequest) -> LayoutResult:
                item_count = request.item_count
                content = item_count * self.extent
                boundary = min(200.0, content)
                sticky = (
                    StickyConstraint("start", 0.0, boundary)
                    if item_count > 5 and boundary > self.extent
                    else None
                )
                placements = tuple(
                    VirtualPlacement(
                        index,
                        0.0,
                        index * self.extent,
                        request.viewport.width,
                        self.extent,
                        sticky if (sticky is not None and index == 0) else None,
                    )
                    for index in range(item_count)
                )
                return LayoutResult(
                    request.viewport.width,
                    content,
                    placements,
                )

            def offset_for_index(
                self,
                index: int,
                *,
                measurement_for_index,
            ) -> tuple[float, float]:
                return (0.0, index * self.extent)

        base = tuple(range(10))
        shrunken = tuple(range(3))

        def app():
            data_cell = state(base)

            def shrink(event):
                data_cell.set(shrunken)

            return Column(
                Text(
                    text="shrink",
                    key="btn",
                    on_click=shrink,
                ),
                VirtualList(
                    data_cell.value,
                    render_item=_cell,
                    layout=ToggleStickyLayout(),
                    key_for_item=lambda item, index: item,
                    width=300,
                    height=100,
                ),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        # Mounted with 10 items: index 0 is a sticky header.
        self.assertEqual(_cell_by_key(runtime, 0)["_virtual_sticky_edge"], "start")
        button = next(
            node
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and node.key == "btn"
        )
        runtime.dispatch_event({
            "type": "event",
            "seq": 1,
            "target": button.id,
            "event": "click",
            "handler": button.listeners["click"],
            "payload": {},
        })
        # Shrunk to 3 items: index 0 is no longer sticky.  The wrapper keyed 0
        # persists, so the reconciliation emits remove_prop ops instead of
        # leaving stale metadata on a reused/pooled view.
        self.assertNotIn("_virtual_sticky_edge", _cell_by_key(runtime, 0))
        self.assertNotIn("_virtual_sticky_boundary_start", _cell_by_key(runtime, 0))
        self.assertNotIn("_virtual_sticky_boundary_end", _cell_by_key(runtime, 0))
        # No sticky placement is selected anymore, so the content Box is no
        # longer marked and the native sticky pass is disabled.
        self.assertNotIn("_virtual_content", _content_props(runtime))
        remove_ops = [
            op
            for op in runtime.latest_commit.get("ops", [])
            if op.get("op") == "remove_prop"
        ]
        removed = {op.get("name") for op in remove_ops}
        self.assertIn("_virtual_sticky_edge", removed)
        self.assertIn("_virtual_sticky_boundary_start", removed)
        self.assertIn("_virtual_content", removed)


if __name__ == "__main__":
    unittest.main()
