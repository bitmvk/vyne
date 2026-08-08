"""Private fixed-extent virtual-list controller and element compositor.

This module deliberately defines no public list API. It proves the framework
boundary: Python selects and composes cells, while the existing Runtime lowers
and reconciles the resulting ordinary Element tree.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import math
from typing import Any, Literal

from vyne.component import component
from vyne._effects import ScrollToEffect
from vyne.elements import (
    Box,
    Column,
    Element,
    Row,
    Scroll,
    _horizontal_scroll,
    normalize_child,
)
from vyne.events import latest
from vyne.refs import Ref
from vyne.state import State, current_runtime, state
from vyne.values import FrozenMap, freeze
from vyne._lists.model import (
    FixedExtentLayout,
    IndexRange,
    ItemRangeSegment,
    RenderMask,
    SpacerSegment,
    ViewportMetrics,
    WindowConfig,
    WindowSelection,
)
from vyne._lists.source import VirtualizedDataSource
from vyne._lists.window import plan_mask, select_window


@dataclass(frozen=True)
class _FixedWindowState:
    axis: Literal["vertical", "horizontal"]
    viewport: ViewportMetrics | None
    actual_viewport: ViewportMetrics | None
    accepted_coverage: IndexRange | None
    accepted_direction: Literal[-1, 0, 1]


@dataclass(frozen=True)
class _FixedVirtualListBinding:
    window_state: State[_FixedWindowState]
    layout: FixedExtentLayout
    retained_mask: RenderMask
    window_config: WindowConfig
    axis: Literal["vertical", "horizontal"]
    coverage: IndexRange
    direction: Literal[-1, 0, 1]
    estimated_viewport_extent: float | None


class FixedVirtualListController:
    """Private accepted owner for one mounted fixed-list target."""

    def __init__(self) -> None:
        self._scroll_ref = Ref()
        self._binding: _FixedVirtualListBinding | None = None
        self._viewport_offset: float | None = None
        self._viewport_extent: float | None = None

    def _accept_runtime_binding(
        self,
        binding: _FixedVirtualListBinding | None,
    ) -> None:
        if binding is not None and not isinstance(
            binding,
            _FixedVirtualListBinding,
        ):
            raise TypeError("Invalid fixed virtual-list Runtime binding")
        previous = self._binding
        if (
            binding is None
            or previous is None
            or previous.window_state is not binding.window_state
            or previous.axis != binding.axis
        ):
            self._viewport_offset = None
            self._viewport_extent = None
        self._binding = binding

    def _observe_viewport(self, viewport: ViewportMetrics) -> None:
        if self._binding is not None:
            self._viewport_offset = viewport.offset
            self._viewport_extent = viewport.extent

    def scroll_to_index(
        self,
        index: int,
        *,
        alignment: Literal["start", "center", "end", "nearest"],
        animated: bool,
    ) -> None:
        """Scroll one item into an explicitly aligned viewport position."""
        binding = self._binding
        if binding is None or self._scroll_ref.current is None:
            raise RuntimeError("Fixed virtual list is not mounted")
        if type(index) is not int:
            raise TypeError("index must be an integer")
        if index < 0 or index >= binding.layout.item_count:
            raise IndexError(
                f"index {index} outside item range 0..{binding.layout.item_count - 1}"
            )
        if alignment not in {"start", "center", "end", "nearest"}:
            raise ValueError(
                "alignment must be 'start', 'center', 'end', or 'nearest'"
            )
        if type(animated) is not bool:
            raise TypeError("animated must be a boolean")

        item_start = binding.layout.offset_for_index(index)
        item_end = binding.layout.offset_for_index(index + 1)
        if alignment == "start":
            target_offset = item_start
        else:
            viewport_extent = self._viewport_extent
            if viewport_extent is None or viewport_extent <= 0:
                raise RuntimeError(
                    f"{alignment} alignment requires viewport metrics"
                )
            if alignment == "center":
                target_offset = (item_start + item_end - viewport_extent) / 2
            elif alignment == "end":
                target_offset = item_end - viewport_extent
            else:
                viewport_offset = self._viewport_offset
                if viewport_offset is None:
                    raise RuntimeError(
                        "nearest alignment requires viewport metrics"
                    )
                viewport_end = viewport_offset + viewport_extent
                if item_start >= viewport_offset and item_end <= viewport_end:
                    return
                max_offset = max(
                    0.0,
                    binding.layout.total_extent - viewport_extent,
                )
                start_target = min(item_start, max_offset)
                end_target = min(
                    max(0.0, item_end - viewport_extent),
                    max_offset,
                )
                target_offset = (
                    start_target
                    if abs(start_target - viewport_offset)
                    <= abs(end_target - viewport_offset)
                    else end_target
                )
                if target_offset == viewport_offset:
                    return

        self.scroll_to_offset(max(0.0, target_offset), animated=animated)

    def scroll_to_offset(self, offset: float, *, animated: bool) -> None:
        """Realize an explicit target window and queue one native scroll."""
        binding = self._binding
        handle = self._scroll_ref.current
        if binding is None or handle is None:
            raise RuntimeError("Fixed virtual list is not mounted")
        viewport_extent = (
            self._viewport_extent
            or binding.estimated_viewport_extent
            or 0.0
        )
        if viewport_extent <= 0:
            raise RuntimeError(
                "scroll_to_offset requires native viewport metrics or an explicit "
                "numeric main-axis list size"
            )
        viewport = ViewportMetrics(offset=offset, extent=viewport_extent)
        bounded_offset, _ = _selection_for_offset(
            binding.layout,
            viewport,
            binding.window_config,
            binding.retained_mask,
            previous_coverage=binding.coverage,
            previous_direction=binding.direction,
        )

        runtime = current_runtime()
        if runtime is None:
            raise RuntimeError(
                "scroll_to_offset must run in an event handler or async callback"
            )
        runtime._queue_native_effect(
            ScrollToEffect(
                handle,
                offset_x=(bounded_offset if binding.axis == "horizontal" else 0),
                offset_y=(bounded_offset if binding.axis == "vertical" else 0),
                animated=animated,
            )
        )
        actual_offset = min(
            self._viewport_offset or 0.0,
            max(0.0, binding.layout.total_extent - viewport.extent),
        )
        planning_viewport = ViewportMetrics(
            bounded_offset,
            viewport.extent,
        )
        actual_viewport = (
            ViewportMetrics(
                actual_offset,
                viewport.extent,
            )
            if animated
            else planning_viewport
        )
        next_state = _FixedWindowState(
            axis=binding.axis,
            viewport=planning_viewport,
            actual_viewport=actual_viewport,
            accepted_coverage=binding.coverage,
            accepted_direction=binding.direction,
        )
        if next_state != binding.window_state.value:
            binding.window_state.set(next_state)


@dataclass(frozen=True)
class FixedVirtualListSpec:
    """Complete explicit input to the private fixed-layout engine."""

    source: VirtualizedDataSource
    controller: FixedVirtualListController
    render_item: Callable[[Any, int, Any], Element]
    item_extent: float
    axis: Literal["vertical", "horizontal"]
    initial_mask: RenderMask
    retained_mask: RenderMask
    window_config: WindowConfig
    scroll_props: FrozenMap = FrozenMap()

    def __post_init__(self) -> None:
        if not isinstance(self.source, VirtualizedDataSource):
            raise TypeError("source must implement VirtualizedDataSource")
        if not isinstance(self.controller, FixedVirtualListController):
            raise TypeError("controller must be FixedVirtualListController")
        if not callable(self.render_item):
            raise TypeError("render_item must be callable")
        # Reuse the layout value object's strict count/extent validation.
        FixedExtentLayout(self.source.item_count, self.item_extent)
        if self.axis not in {"vertical", "horizontal"}:
            raise ValueError("axis must be 'vertical' or 'horizontal'")
        if not isinstance(self.initial_mask, RenderMask):
            raise TypeError("initial_mask must be RenderMask")
        if not isinstance(self.retained_mask, RenderMask):
            raise TypeError("retained_mask must be RenderMask")
        if not isinstance(self.window_config, WindowConfig):
            raise TypeError("window_config must be WindowConfig")
        if not isinstance(self.scroll_props, Mapping):
            raise TypeError("scroll_props must be a mapping")
        reserved = {
            "on_scroll_metrics",
            "ref",
            "_virtual_list_initial_offset",
        }.intersection(self.scroll_props)
        if reserved:
            names = ", ".join(sorted(reserved))
            raise ValueError(f"The virtual-list controller owns {names}")
        object.__setattr__(
            self,
            "scroll_props",
            FrozenMap((name, freeze(value)) for name, value in self.scroll_props.items()),
        )


@component
def render_fixed_virtual_list(spec: FixedVirtualListSpec) -> Element:
    """Render one private list component using ordinary Vyne primitives."""
    layout = FixedExtentLayout(spec.source.item_count, spec.item_extent)
    constrained_initial = spec.initial_mask.constrained(layout.item_count)
    initial_coverage = (
        constrained_initial.ranges[0]
        if constrained_initial.ranges
        else IndexRange(0, 0)
    )
    initial_mask = constrained_initial.union(
        spec.retained_mask.constrained(layout.item_count)
    )
    estimated_viewport_extent = _declared_viewport_extent(spec)
    window_state = state(
        _FixedWindowState(
            axis=spec.axis,
            viewport=None,
            actual_viewport=None,
            accepted_coverage=None,
            accepted_direction=0,
        )
    )
    observed = window_state.value
    desired_offset = 0.0
    if observed.axis != spec.axis or observed.viewport is None:
        if estimated_viewport_extent is None:
            selection = WindowSelection(
                mask=initial_mask,
                coverage=initial_coverage,
                direction=0,
            )
        else:
            selection = select_window(
                layout,
                ViewportMetrics(0, estimated_viewport_extent),
                spec.window_config,
                retained=initial_mask,
                required_viewport=ViewportMetrics(0, estimated_viewport_extent),
            )
            if (
                not initial_coverage.empty
                and initial_coverage.start <= selection.coverage.stop
                and selection.coverage.start <= initial_coverage.stop
            ):
                selection = WindowSelection(
                    mask=selection.mask,
                    coverage=IndexRange(
                        min(selection.coverage.start, initial_coverage.start),
                        max(selection.coverage.stop, initial_coverage.stop),
                    ),
                    direction=selection.direction,
                )
    else:
        desired_offset, selection = _selection_for_offset(
            layout,
            observed.viewport,
            spec.window_config,
            spec.retained_mask,
            previous_coverage=observed.accepted_coverage,
            previous_direction=observed.accepted_direction,
            required_viewport=observed.actual_viewport,
        )
    current_mask = selection.mask
    runtime = current_runtime()
    if runtime is None:
        raise RuntimeError("Fixed virtual list must render inside a Runtime")
    runtime._stage_imperative_binding(
        spec.controller,
        _FixedVirtualListBinding(
            window_state=window_state,
            layout=layout,
            retained_mask=spec.retained_mask,
            window_config=spec.window_config,
            axis=spec.axis,
            coverage=selection.coverage,
            direction=selection.direction,
            estimated_viewport_extent=estimated_viewport_extent,
        ),
        anchor_ref=spec.controller._scroll_ref,
    )

    def observe_scroll(event: Any) -> None:
        actual_viewport = _axis_viewport(event, spec.axis)
        projected_viewport = _projected_axis_viewport(event, spec.axis)
        planning_viewport = (
            _capped_planning_viewport(
                projected_viewport,
                actual_viewport,
                spec.window_config,
            )
            if projected_viewport is not None
            else actual_viewport
        )
        spec.controller._observe_viewport(actual_viewport)
        if _mask_contains_viewports(
            selection.mask,
            layout,
            planning_viewport,
            actual_viewport,
        ):
            return
        next_state = _FixedWindowState(
            axis=spec.axis,
            viewport=planning_viewport,
            actual_viewport=actual_viewport,
            accepted_coverage=selection.coverage,
            accepted_direction=selection.direction,
        )
        if next_state != window_state.value:
            window_state.set(next_state)

    return compose_fixed_window(
        spec,
        current_mask,
        initial_offset=desired_offset,
        on_scroll_metrics=latest(observe_scroll),
    )


def compose_fixed_window(
    spec: FixedVirtualListSpec,
    mask: RenderMask,
    *,
    initial_offset: float = 0.0,
    on_scroll_metrics: Callable[..., Any],
) -> Element:
    """Compose spacers and realized cells for an already selected mask."""
    layout = FixedExtentLayout(spec.source.item_count, spec.item_extent)
    plan = plan_mask(layout, mask)
    children: list[Element] = []
    spacer_ordinal = 0

    for segment in plan.segments:
        if isinstance(segment, SpacerSegment):
            spacer_props = (
                {"width": "match_parent", "height": segment.extent}
                if spec.axis == "vertical"
                else {"width": segment.extent, "height": "match_parent"}
            )
            children.append(
                Box(
                    key=("__vyne_list_spacer__", spacer_ordinal),
                    **spacer_props,
                )
            )
            spacer_ordinal += 1
            continue
        if not isinstance(segment, ItemRangeSegment):
            raise TypeError(f"Unknown list segment {type(segment).__name__}")
        for index in range(segment.start, segment.stop):
            key = spec.source.key_at(index)
            rendered = normalize_child(
                spec.render_item(spec.source.item_at(index), index, key)
            )
            cell_props = (
                {"width": "match_parent", "height": spec.item_extent}
                if spec.axis == "vertical"
                else {"width": spec.item_extent, "height": "match_parent"}
            )
            children.append(
                Box(
                    rendered,
                    key=("__vyne_list_cell__", key),
                    **cell_props,
                )
            )

    props = dict(spec.scroll_props.items())
    props["on_scroll_metrics"] = on_scroll_metrics
    props["_virtual_list_initial_offset"] = initial_offset
    content_factory = Column if spec.axis == "vertical" else Row
    scroll_factory = Scroll if spec.axis == "vertical" else _horizontal_scroll
    cross_axis_prop = (
        {"width": "match_parent"}
        if spec.axis == "vertical"
        else {"height": "match_parent"}
    )
    return scroll_factory(
        content_factory(
            *children,
            key=("__vyne_list_content__",),
            **cross_axis_prop,
        ),
        ref=spec.controller._scroll_ref,
        **props,
    )


def _declared_viewport_extent(spec: FixedVirtualListSpec) -> float | None:
    name = "height" if spec.axis == "vertical" else "width"
    value = spec.scroll_props.get(name)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        extent = float(value)
    elif isinstance(value, str) and value.strip().lower().endswith("dp"):
        try:
            extent = float(value.strip().lower().removesuffix("dp"))
        except ValueError:
            return None
    else:
        return None
    return extent if math.isfinite(extent) and extent > 0 else None


def _selection_for_offset(
    layout: FixedExtentLayout,
    viewport: ViewportMetrics,
    config: WindowConfig,
    retained: RenderMask,
    *,
    previous_coverage: IndexRange | None,
    previous_direction: int,
    required_viewport: ViewportMetrics | None = None,
) -> tuple[float, WindowSelection]:
    target_extent = (
        viewport.extent if viewport.extent > 0 else layout.item_extent
    )
    bounded_offset = min(
        viewport.offset,
        max(0.0, layout.total_extent - target_extent),
    )
    if viewport.extent > 0:
        selection = select_window(
            layout,
            ViewportMetrics(
                bounded_offset,
                viewport.extent,
                viewport.velocity,
            ),
            config,
            retained=retained,
            previous_coverage=previous_coverage,
            previous_direction=previous_direction,
            required_viewport=required_viewport,
        )
    else:
        target = layout.range_for_interval(
            bounded_offset,
            min(layout.total_extent, bounded_offset + layout.item_extent),
        )
        direction = (
            1 if viewport.velocity > 0 else -1 if viewport.velocity < 0 else 0
        )
        selection = WindowSelection(
            mask=RenderMask.from_ranges(target).union(
                retained.constrained(layout.item_count)
            ),
            coverage=target,
            direction=direction,
        )
    return bounded_offset, selection


def _axis_viewport(
    event: Any,
    axis: Literal["vertical", "horizontal"],
) -> ViewportMetrics:
    getter = getattr(event, "get", None)
    if getter is None:
        raise TypeError("scroll_metrics event must provide get(name)")
    suffix = "y" if axis == "vertical" else "x"
    extent_name = "viewport_height" if axis == "vertical" else "viewport_width"
    return ViewportMetrics(
        offset=getter(f"offset_{suffix}"),
        extent=getter(extent_name),
        velocity=getter(f"velocity_{suffix}", 0.0),
    )


def _projected_axis_viewport(
    event: Any,
    axis: Literal["vertical", "horizontal"],
) -> ViewportMetrics | None:
    """Read the native fling/drag projection, or None when it is absent."""
    getter = getattr(event, "get", None)
    if getter is None:
        raise TypeError("scroll_metrics event must provide get(name)")
    suffix = "y" if axis == "vertical" else "x"
    extent_name = "viewport_height" if axis == "vertical" else "viewport_width"
    projected = getter(f"projected_offset_{suffix}")
    if isinstance(projected, bool) or not isinstance(projected, int | float):
        return None
    projected_offset = float(projected)
    if not math.isfinite(projected_offset) or projected_offset < 0:
        return None
    return ViewportMetrics(offset=projected_offset, extent=getter(extent_name))


def _capped_planning_viewport(
    projected: ViewportMetrics,
    actual: ViewportMetrics,
    config: WindowConfig,
) -> ViewportMetrics:
    """Bound the projection span so one commit cannot mount unbounded cells.

    ``max_render_ahead_viewports`` caps how far ahead of the current viewport
    the planned window may reach; the window then follows the scroll in
    bounded steps instead of rendering the full fling path in one commit.
    A cap of 0 leaves the projection unbounded.
    """
    cap = config.max_render_ahead_viewports
    if cap <= 0 or actual.extent <= 0:
        return projected
    ahead = min(
        projected.offset,
        actual.offset + actual.extent * cap,
    )
    return ViewportMetrics(offset=ahead, extent=actual.extent)


def _mask_contains_viewports(
    mask: RenderMask,
    layout: FixedExtentLayout,
    *viewports: ViewportMetrics,
) -> bool:
    """True when every viewport's item span is fully covered by ``mask``.

    The planner is deterministic for identical inputs, so when both the
    planning target and the current viewport are already mounted, a render
    would change nothing and can be skipped.
    """
    for viewport in viewports:
        if viewport.extent <= 0:
            continue
        item_range = layout.range_for_interval(
            viewport.offset,
            viewport.offset + viewport.extent,
        )
        if not all(
            mask.contains(index)
            for index in range(item_range.start, item_range.stop)
        ):
            return False
    return True
