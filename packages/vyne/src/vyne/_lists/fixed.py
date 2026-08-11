"""Private fixed-extent virtual-list controller and element compositor.

This module deliberately defines no public list API. It proves the framework
boundary: Python selects and composes cells, while the existing Runtime lowers
and reconciles the resulting ordinary Element tree.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
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
from vyne._lists._shared import (
    derive_candidate_key_registry,
    resolve_alignment_offset,
    resolve_key_index,
)
from vyne._lists.source import KeyRegistry, VirtualizedDataSource
from vyne._lists.window import plan_mask, select_window
from vyne.values import validate_canonical_key


@dataclass(frozen=True)
class _FixedWindowState:
    axis: Literal["vertical", "horizontal"]
    viewport: ViewportMetrics | None
    actual_viewport: ViewportMetrics | None
    item_count: int | None


@dataclass(frozen=True)
class _FixedVirtualListBinding:
    """Accepted controller binding for one mounted fixed-list target.

    Candidate data (key registry) lives here and is promoted through
    ``_accept_runtime_binding`` only after the native acknowledgement, so
    rejected or unknown commits never leak candidate key mappings into
    accepted controller state.  ``source`` is retained so controller
    commands can resolve keys without re-adapting the data.

    ``actual_viewport`` and ``planning_viewport`` are the immutable
    viewport snapshots of the render this binding commits.  Controller
    commands read them instead of the journaled ``window_state``, which can
    hold candidate viewports from an un-acknowledged commit: a command
    issued while a commit is in flight, or after a known rejection, must
    act on the last accepted actual viewport, never on a destination that
    was not accepted.
    """

    window_state: State[_FixedWindowState]
    source: VirtualizedDataSource
    layout: FixedExtentLayout
    retained_mask: RenderMask
    window_config: WindowConfig
    axis: Literal["vertical", "horizontal"]
    estimated_viewport_extent: float | None
    key_registry: KeyRegistry | None = None
    actual_viewport: ViewportMetrics | None = None
    planning_viewport: ViewportMetrics | None = None


class FixedVirtualListController:
    """Private accepted owner for one mounted fixed-list target.

    Owned by the public ``ListController`` facade; never part of the public
    API.
    """

    def __init__(self) -> None:
        self._scroll_ref = Ref()
        self._binding: _FixedVirtualListBinding | None = None
        self._viewport_offset: float | None = None
        self._viewport_extent: float | None = None
        self._key_registry: KeyRegistry | None = None

    @property
    def is_mounted(self) -> bool:
        """True when an accepted binding is currently attached."""
        return self._binding is not None

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
            # Unmount, a different occurrence, a fresh render state, or a
            # flipped axis invalidates the observed physical viewport;
            # commands must wait for fresh native metrics instead of acting
            # on a stale window.
            self._viewport_offset = None
            self._viewport_extent = None
        if binding is None:
            self._key_registry = None
        else:
            self._key_registry = binding.key_registry
            # Promote the accepted actual viewport into the observed
            # physical cache only when it changed from the previously
            # accepted binding (a programmatic non-animated ack, an anchor
            # correction, or a native replan) or on a first/new-occurrence
            # binding.  Programmatic jumps therefore only land in the cache
            # once the native side acknowledged the commit, while an
            # unrelated render that keeps the same accepted actual snapshot
            # must not overwrite a newer no-commit native observation with
            # stale state.
            if binding.actual_viewport is not None and (
                previous is None
                or previous.window_state is not binding.window_state
                or previous.axis != binding.axis
                or previous.actual_viewport != binding.actual_viewport
            ):
                self._viewport_offset = binding.actual_viewport.offset
                self._viewport_extent = binding.actual_viewport.extent
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
            raise ValueError("alignment must be 'start', 'center', 'end', or 'nearest'")
        if type(animated) is not bool:
            raise TypeError("animated must be a boolean")

        item_start = binding.layout.offset_for_index(index)
        item_end = binding.layout.offset_for_index(index + 1)
        actual = _preferred_actual(self, binding)
        viewport_extent = actual.extent if actual is not None else None
        viewport_offset = actual.offset if actual is not None else None
        if alignment != "start" and (viewport_extent is None or viewport_extent <= 0):
            raise RuntimeError(f"{alignment} alignment requires viewport metrics")
        if alignment == "nearest" and viewport_offset is None:
            raise RuntimeError("nearest alignment requires viewport metrics")
        target_offset = resolve_alignment_offset(
            alignment=alignment,
            main_start=item_start,
            main_end=item_end,
            viewport_offset=viewport_offset or 0.0,
            viewport_extent=viewport_extent or 0.0,
            max_offset=max(0.0, binding.layout.total_extent - (viewport_extent or 0.0)),
        )
        if target_offset is None:
            return

        self.scroll_to_offset(target_offset, animated=animated)

    def scroll_to_key(
        self,
        key: Any,
        *,
        alignment: Literal["start", "center", "end", "nearest"],
        animated: bool,
    ) -> None:
        """Scroll a stable source key into the viewport.

        Resolution never scans the source: the accepted per-occurrence key
        registry answers for already-realized keys, a plain ``Sequence``
        with default index keys answers in O(1), and an optional source
        ``index_for_key`` answers for the rest.  Any other key raises
        without a full-source scan.
        """
        binding = self._binding
        if binding is None or self._scroll_ref.current is None:
            raise RuntimeError("Fixed virtual list is not mounted")
        validate_canonical_key(key, path="list key")
        index = resolve_key_index(
            key=key,
            source=binding.source,
            key_registry=binding.key_registry,
        )
        if index is None:
            raise RuntimeError(
                f"key {key!r} is not realized and the source cannot resolve "
                "it; no full-source scan is performed"
            )
        self.scroll_to_index(index, alignment=alignment, animated=animated)

    def scroll_to_offset(self, offset: float, *, animated: bool) -> None:
        """Realize an explicit target window and queue one native scroll."""
        binding = self._binding
        handle = self._scroll_ref.current
        if binding is None or handle is None:
            raise RuntimeError("Fixed virtual list is not mounted")
        actual = _preferred_actual(self, binding)
        viewport_extent = actual.extent if actual is not None else None
        if viewport_extent is None or viewport_extent <= 0:
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
            required_viewport=actual,
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
            (actual.offset if actual is not None else 0.0),
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
            item_count=binding.layout.item_count,
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
    key_registry: KeyRegistry | None = None
    key_for_item: Callable[[Any, int], Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, VirtualizedDataSource):
            raise TypeError("source must implement VirtualizedDataSource")
        if not isinstance(self.controller, FixedVirtualListController):
            raise TypeError("controller must be FixedVirtualListController")
        if not callable(self.render_item):
            raise TypeError("render_item must be callable")
        if self.key_registry is not None and not isinstance(
            self.key_registry,
            KeyRegistry,
        ):
            raise TypeError("key_registry must be KeyRegistry or None")
        if self.key_for_item is not None and not callable(self.key_for_item):
            raise TypeError("key_for_item must be callable or None")
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
            "on_scroll_seek",
            "ref",
            "_virtual_list_initial_offset",
        }.intersection(self.scroll_props)
        if reserved:
            names = ", ".join(sorted(reserved))
            raise ValueError(f"The virtual-list controller owns {names}")
        object.__setattr__(
            self,
            "scroll_props",
            FrozenMap(
                (name, freeze(value)) for name, value in self.scroll_props.items()
            ),
        )


@component
def render_fixed_virtual_list(spec: FixedVirtualListSpec) -> Element:
    """Render one private list component using ordinary Vyne primitives."""
    candidate_registry = derive_candidate_key_registry(
        spec.controller._key_registry,
        spec.key_registry,
        spec.source,
        spec.key_for_item,
    )
    render_spec = replace(spec, key_registry=candidate_registry)
    layout = FixedExtentLayout(render_spec.source.item_count, render_spec.item_extent)
    constrained_initial = render_spec.initial_mask.constrained(layout.item_count)
    initial_mask = constrained_initial.union(
        render_spec.retained_mask.constrained(layout.item_count)
    )
    estimated_viewport_extent = _declared_viewport_extent(render_spec)
    window_state = state(
        _FixedWindowState(
            axis=render_spec.axis,
            viewport=None,
            actual_viewport=None,
            item_count=None,
        )
    )
    observed = window_state.value
    desired_offset = 0.0
    if observed.axis != render_spec.axis or observed.viewport is None:
        actual_viewport = None
        planning_viewport = None
        if estimated_viewport_extent is None:
            selection = WindowSelection(mask=initial_mask)
        else:
            metrics = ViewportMetrics(0, estimated_viewport_extent)
            actual_viewport = metrics
            planning_viewport = metrics
            selection = select_window(
                layout,
                metrics,
                render_spec.window_config,
                retained=initial_mask,
                required_viewport=metrics,
            )
    else:
        actual_viewport = observed.actual_viewport
        planning_viewport = observed.viewport
        desired_offset, selection = _selection_for_offset(
            layout,
            observed.viewport,
            render_spec.window_config,
            render_spec.retained_mask,
            required_viewport=observed.actual_viewport,
        )
    current_mask = selection.mask
    runtime = current_runtime()
    if runtime is None:
        raise RuntimeError("Fixed virtual list must render inside a Runtime")
    runtime._stage_imperative_binding(
        render_spec.controller,
        _FixedVirtualListBinding(
            window_state=window_state,
            source=render_spec.source,
            layout=layout,
            retained_mask=render_spec.retained_mask,
            window_config=render_spec.window_config,
            axis=render_spec.axis,
            estimated_viewport_extent=estimated_viewport_extent,
            key_registry=candidate_registry,
            actual_viewport=actual_viewport,
            planning_viewport=planning_viewport,
        ),
        anchor_ref=render_spec.controller._scroll_ref,
    )

    def observe_scroll(event: Any) -> None:
        actual_viewport = _axis_viewport(event, render_spec.axis)
        projected_viewport = _projected_axis_viewport(event, render_spec.axis)
        planning_viewport = (
            _capped_planning_viewport(
                projected_viewport,
                actual_viewport,
                render_spec.window_config,
            )
            if projected_viewport is not None
            else actual_viewport
        )
        render_spec.controller._observe_viewport(actual_viewport)
        # Recompute the layout from the live source count: an in-place
        # shrink leaves the last-render layout stale, and the accepted mask
        # may still contain cells that no longer exist.
        current_layout = FixedExtentLayout(
            render_spec.source.item_count, render_spec.item_extent
        )
        if _mask_contains_viewports(
            selection.mask,
            current_layout,
            planning_viewport,
            actual_viewport,
        ):
            return
        next_state = _FixedWindowState(
            axis=render_spec.axis,
            viewport=planning_viewport,
            actual_viewport=actual_viewport,
            item_count=render_spec.source.item_count,
        )
        if next_state != window_state.value:
            window_state.set(next_state)

    def observe_seek(event: Any) -> None:
        render_spec.controller.scroll_to_offset(
            _axis_seek_offset(event, render_spec.axis),
            animated=False,
        )

    seek_handler = (
        latest(observe_seek)
        if render_spec.scroll_props.get("interactive_scrollbar") is True
        else None
    )
    return compose_fixed_window(
        render_spec,
        current_mask,
        initial_offset=desired_offset,
        on_scroll_metrics=latest(observe_scroll),
        on_scroll_seek=seek_handler,
    )


def compose_fixed_window(
    spec: FixedVirtualListSpec,
    mask: RenderMask,
    *,
    initial_offset: float = 0.0,
    on_scroll_metrics: Callable[..., Any],
    on_scroll_seek: Callable[..., Any] | None = None,
) -> Element:
    """Compose spacers and realized cells for an already selected mask."""
    layout = FixedExtentLayout(spec.source.item_count, spec.item_extent)
    plan = plan_mask(layout, mask)
    children: list[Element] = []
    spacer_ordinal = 0
    seen_keys: set[Any] = set()
    registry = spec.key_registry
    use_registry = registry is not None and not getattr(
        spec.source, "uses_index_keys", False
    )

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
            if key in seen_keys:
                raise ValueError(f"Duplicate list key {key!r} at index {index}")
            seen_keys.add(key)
            if use_registry:
                assert registry is not None
                previous_index = registry.key_to_index.get(key)
                if previous_index is not None and previous_index != index:
                    raise ValueError(
                        f"Duplicate list key {key!r} at index {index} "
                        f"(already realized at index {previous_index})"
                    )
                registry.key_to_index[key] = index
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
    if on_scroll_seek is not None:
        props["on_scroll_seek"] = on_scroll_seek
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


def _preferred_actual(
    controller: FixedVirtualListController,
    binding: _FixedVirtualListBinding,
) -> ViewportMetrics | None:
    """Preferred current physical actual viewport for one controller command.

    Real native scroll events are recorded in the controller's observation
    cache before any no-op coverage return, so the cache stays current even
    when the scroll stays inside accepted coverage and produces no render
    or acknowledgement (the promoted binding snapshot is stale).  Commands
    prefer that observation and fall back to the promoted binding snapshot
    (or the declared pre-metrics viewport) before the first native event.
    The snapshot is never read from the journaled candidate
    ``window_state``: a command issued while a commit is in flight — or
    after a known rejection — must act on the last accepted position, not
    on an un-acknowledged destination.
    """
    if (
        controller._viewport_offset is not None
        and controller._viewport_extent is not None
    ):
        return ViewportMetrics(
            controller._viewport_offset,
            controller._viewport_extent,
        )
    actual, _planning = _binding_viewports(binding)
    return actual


def _binding_viewports(
    binding: _FixedVirtualListBinding,
) -> tuple[ViewportMetrics | None, ViewportMetrics | None]:
    """Accepted viewports carried by the promoted binding.

    The snapshots are immutable and promoted together with the binding only
    on the native acknowledgement, so controller commands never observe
    candidate viewports from an in-flight or rejected commit.  Falls back
    to the declared pre-metrics viewport when the binding carries none.
    """
    if binding.actual_viewport is not None and binding.planning_viewport is not None:
        return binding.actual_viewport, binding.planning_viewport
    extent = binding.estimated_viewport_extent
    if extent is None or extent <= 0:
        return None, None
    metrics = ViewportMetrics(0.0, extent)
    return metrics, metrics


def _selection_for_offset(
    layout: FixedExtentLayout,
    viewport: ViewportMetrics,
    config: WindowConfig,
    retained: RenderMask,
    *,
    required_viewport: ViewportMetrics | None = None,
) -> tuple[float, WindowSelection]:
    target_extent = viewport.extent if viewport.extent > 0 else layout.item_extent
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
            ),
            config,
            retained=retained,
            required_viewport=required_viewport,
        )
    else:
        target = layout.range_for_interval(
            bounded_offset,
            min(layout.total_extent, bounded_offset + layout.item_extent),
        )
        selection = WindowSelection(
            mask=RenderMask.from_ranges(target).union(
                retained.constrained(layout.item_count)
            ),
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
    )


def _axis_seek_offset(
    event: Any,
    axis: Literal["vertical", "horizontal"],
) -> float:
    getter = getattr(event, "get", None)
    if getter is None:
        raise TypeError("scroll_seek event must provide get(name)")
    suffix = "y" if axis == "vertical" else "x"
    value = getter(f"target_offset_{suffix}")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("scroll_seek target offset must be a number")
    offset = float(value)
    if not math.isfinite(offset) or offset < 0:
        raise ValueError("scroll_seek target offset must be finite and non-negative")
    return offset


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
    The cap is symmetric: a backward fling may reach at most ``cap``
    viewports behind the actual viewport, and a forward fling at most ``cap``
    viewports ahead. A cap of 0 leaves the projection unbounded.
    """
    cap = config.max_render_ahead_viewports
    if cap <= 0 or actual.extent <= 0:
        return projected
    low = max(0.0, actual.offset - actual.extent * cap)
    high = actual.offset + actual.extent * cap
    bounded = min(max(projected.offset, low), high)
    return ViewportMetrics(offset=bounded, extent=actual.extent)


def _mask_contains_viewports(
    mask: RenderMask,
    layout: FixedExtentLayout,
    *viewports: ViewportMetrics,
) -> bool:
    """True when every viewport's item span is fully covered by ``mask``.

    The planner is deterministic for identical inputs, so when both the
    planning target and the current viewport are already mounted, a render
    would change nothing and can be skipped.

    A mask that still contains cells at or beyond the current item count is
    stale: the source shrank and the mounted window no longer matches the
    layout, so a replan must run to drop the removed cells.  Each viewport
    offset is clamped to the current scroll bounds before its item span is
    checked, mirroring the planner, so an out-of-range offset tests the real
    (clamped) end window instead of vacuously passing on an empty span.
    """
    if mask.constrained(layout.item_count) != mask:
        return False
    for viewport in viewports:
        if viewport.extent <= 0:
            continue
        max_offset = max(0.0, layout.total_extent - viewport.extent)
        bounded_offset = min(viewport.offset, max_offset)
        item_range = layout.range_for_interval(
            bounded_offset,
            bounded_offset + viewport.extent,
        )
        if not all(
            mask.contains(index) for index in range(item_range.start, item_range.stop)
        ):
            return False
    return True
