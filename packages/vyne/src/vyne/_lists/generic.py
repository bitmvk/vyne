"""Private generic virtual-list engine.

This module implements the ``VirtualList`` engine behind the public
``vyne.lists`` surface.  It composes positioned realized cells with ordinary
Vyne primitives — a ``Scroll`` (or ``_horizontal_scroll``) hosting a ``Box``
canonical Box whose children are keyed, sized, and translated cell wrappers —
and reuses the Runtime seams established by the old fixed engine: staged
imperative bindings, native effects, one-in-flight commits, rollback, reset,
and acknowledgements.

The framework boundary is unchanged from the fixed list: Python owns data
adaptation, window policy, measurement feedback, and imperative scroll
commands; the Runtime lowers, reconciles, and commits the resulting Element
tree.  No Python runs per native frame beyond the coalesced ``scroll_metrics``
and per-cell ``layout_metrics`` events.

Scroll positions arrive through ``scroll_metrics`` with ``latest`` delivery.
A scroll whose clamped actual viewport stays inside the accepted safe
coverage and whose clamped planning viewport stays inside the accepted
realization viewport sets no state and emits no commit (the no-frame path).
The safe coverage is derived from the accepted render itself: when the
offscreen budget dropped any candidate, the accepted guarantee narrows to a
local band around the actual viewport or to the exact actual viewport — no
exact geometric coverage heuristic is used.  Controller commands act on
immutable viewport snapshots carried by the accepted binding (promoted only
on the native acknowledgement), so an in-flight or rejected commit never
leaks its candidate viewport into a later command.  Cell sizes arrive through
per-cell ``layout_metrics`` listeners and are cached by stable source key in
a bounded 4096-entry insertion-order cache (reads do not refresh recency;
recency changes only when a cell is measured again); identical measurements
are no-ops, and layouts
that expose ``index_near_offset`` receive anchor preservation: the anchored
cell's placed offset is compared before/after a measurement, and a drift
shifts the planning viewport and queues one non-animated ``ScrollToEffect``
in the same event batch.  An optional ``index_near_offset`` returning
``None`` simply disables the anchor; malformed results raise instead of
reaching ``offset_for_index``.

Sticky placements are retained and composed at their natural positions, and
the Android host applies the native start/end movement from private
metadata (see ``docs/framework/list-building-blocks.md``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
import math
from typing import Any, Literal

from vyne.component import component
from vyne._effects import ScrollToEffect
from vyne.elements import Box, Element, Scroll, _horizontal_scroll, normalize_child
from vyne.events import latest
from vyne.refs import Ref
from vyne.state import State, current_runtime, state
from vyne.values import FrozenMap, freeze, validate_canonical_key

from vyne._lists._shared import (
    derive_candidate_key_registry,
    resolve_alignment_offset,
    resolve_key_index,
)
from vyne._lists.contracts import (
    CellMeasurement,
    LayoutRequest,
    LayoutResult,
    VirtualLayout,
    VirtualPlacement,
    ViewportRect,
    placement_relevant,
    select_placements,
)
from vyne._lists.source import KeyRegistry, VirtualizedDataSource

_ANCHOR_EPSILON = 1e-6

# Bounded measurement cache: measurements follow stable keys across windows
# and reorders, and the cache is capped with deterministic insertion-order
# eviction.  Reads do not refresh recency; a re-measured key is re-inserted
# at the newest position.
_MEASUREMENT_CACHE_LIMIT = 4096

# Reserved scroll props owned by the list controller.
_RESERVED_SCROLL_PROPS = frozenset(
    {"on_scroll_metrics", "on_scroll_seek", "ref", "_virtual_list_initial_offset"}
)


@dataclass(frozen=True)
class _VirtualListWindowState:
    """Accepted-plus-pending window state retained by one mounted list.

    ``viewport`` is the capped projected (planning) viewport, including any
    anchor corrections applied by measurement events.  ``actual_viewport`` is
    the last reported native viewport.  ``target_index`` is a pending
    scroll-to-index/key target: it is retained as a mandatory placement by
    the next render and cleared once the actual viewport intersects the
    target's main-axis interval.  ``target_source`` is the identity of the
    accepted data the target was computed against; renders and scroll
    observations retain the target only while the current source identity
    matches and the index is still in range, so any sequence or custom-source
    replacement cancels the pending target even at an unchanged item count —
    an index command can never silently retarget a different item on new
    data.  ``measurements`` caches cell sizes by stable source key in a
    bounded insertion-order cache, so reorders and sequence replacement keep
    sizes without re-measuring and identical measurements are no-ops.
    """

    axis: Literal["vertical", "horizontal"]
    viewport: ViewportRect | None
    actual_viewport: ViewportRect | None
    target_index: int | None
    target_main_start: float | None
    target_main_end: float | None
    target_source: Any | None
    anchor_index: int | None
    anchor_offset: float | None
    measurements: dict[Any, CellMeasurement] = field(default_factory=dict)


@dataclass(frozen=True)
class _VirtualListBinding:
    """Accepted controller binding for one mounted generic list.

    Candidate data (key registry, realized keys) lives here and is promoted
    through ``_accept_runtime_binding`` only after the native acknowledgement,
    so rejected or unknown commits never affect accepted controller state.

    ``actual_viewport`` and ``planning_viewport`` are the immutable viewport
    snapshots of the render this binding commits.  Controller commands read
    them instead of the journaled ``window_state``, which can hold candidate
    viewports from an un-acknowledged commit: a command issued while a commit
    is in flight, or after a known rejection, must act on the last accepted
    actual viewport, never on a destination that was not accepted.
    """

    window_state: State[_VirtualListWindowState]
    source: VirtualizedDataSource
    layout: VirtualLayout
    axis: Literal["vertical", "horizontal"]
    key_registry: KeyRegistry | None
    realized_keys: frozenset[Any]
    overscan: float
    max_render_ahead_viewports: float
    max_offscreen_items: int
    initial_item_count: int
    estimated_viewport_extent: float | None
    estimated_cross_extent: float | None
    content_extent: float
    actual_viewport: ViewportRect | None
    planning_viewport: ViewportRect | None


class GenericVirtualListController:
    """Private engine controller for one mounted generic-list target.

    This is the Runtime-facing engine controller owned by the public
    ``ListController`` facade; it is never part of the public API.
    """

    def __init__(self) -> None:
        self._scroll_ref = Ref()
        self._binding: _VirtualListBinding | None = None
        self._key_registry: KeyRegistry | None = None
        self._viewport: ViewportRect | None = None

    @property
    def is_mounted(self) -> bool:
        """True when an accepted binding is currently attached."""
        return self._binding is not None

    def _accept_runtime_binding(
        self,
        binding: _VirtualListBinding | None,
    ) -> None:
        if binding is not None and not isinstance(
            binding,
            _VirtualListBinding,
        ):
            raise TypeError("Invalid virtual-list Runtime binding")
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
            self._viewport = None
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
                self._viewport = binding.actual_viewport
        self._binding = binding

    def _observe_viewport(self, viewport: ViewportRect) -> None:
        """Record one accepted physical viewport observation from native.

        Called by the render's ``observe_scroll`` for every scroll event
        before any no-op coverage return, so the cache stays current even
        when the scroll produces no render or acknowledgement.
        """
        if self._binding is not None:
            self._viewport = viewport

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
            raise RuntimeError("Virtual list is not mounted")
        if type(index) is not int:
            raise TypeError("index must be an integer")
        item_count = binding.source.item_count
        if index < 0 or index >= item_count:
            raise IndexError(f"index {index} outside item range 0..{item_count - 1}")
        if alignment not in {"start", "center", "end", "nearest"}:
            raise ValueError("alignment must be 'start', 'center', 'end', or 'nearest'")
        if type(animated) is not bool:
            raise TypeError("animated must be a boolean")

        # Commands act on the preferred physical viewport: the observed
        # native actual when one has been recorded, otherwise the accepted
        # binding snapshots — never on candidate window state, so a commit
        # that is still in flight (or was rejected) cannot leak its
        # destination into a later command.
        actual, planning = _preferred_viewports(self, binding)
        realization = _realization_viewport(
            actual, planning, binding.overscan, binding.axis
        )
        measurements = binding.window_state.value.measurements
        resolver = _resolver(measurements, binding.source)
        request = LayoutRequest(
            item_count=item_count,
            viewport=actual,
            realization_viewport=realization,
            measurement_for_index=resolver,
            target_index=index,
            initial_item_count=binding.initial_item_count,
            max_offscreen_items=binding.max_offscreen_items,
        )
        result = binding.layout.place(request)
        selected = select_placements(request, result, axis=binding.axis)
        target_placement = next(
            (p for p in selected if p.index == index),
            None,
        )
        if target_placement is None:
            raise RuntimeError(
                f"Layout did not return a placement for target index {index}"
            )
        main_start = _main_offset(target_placement, binding.axis)
        main_end = _main_end(target_placement, binding.axis)

        viewport = actual
        viewport_extent = _main_extent(viewport, binding.axis)
        if alignment != "start" and viewport_extent <= 0:
            raise RuntimeError(f"{alignment} alignment requires viewport metrics")
        content_extent = _main_extent(result, binding.axis)
        max_offset = max(0.0, content_extent - viewport_extent)
        target_offset = resolve_alignment_offset(
            alignment=alignment,
            main_start=main_start,
            main_end=main_end,
            viewport_offset=_main_offset(actual, binding.axis),
            viewport_extent=viewport_extent,
            max_offset=max_offset,
        )
        if target_offset is None:
            return

        self._commit_scroll(
            binding,
            target_offset,
            viewport,
            animated=animated,
            target_index=index,
            target_main_start=main_start,
            target_main_end=main_end,
        )

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
            raise RuntimeError("Virtual list is not mounted")
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
        if binding is None or self._scroll_ref.current is None:
            raise RuntimeError("Virtual list is not mounted")
        if isinstance(offset, bool) or not isinstance(offset, int | float):
            raise TypeError("offset must be a number")
        value = float(offset)
        if not math.isfinite(value) or value < 0:
            raise ValueError("offset must be a finite non-negative number")
        if type(animated) is not bool:
            raise TypeError("animated must be a boolean")

        # Commands act on the preferred physical actual viewport (observed
        # native, falling back to the accepted binding snapshot); the
        # planning snapshot only matters to render-time projection.
        actual, _planning = _preferred_viewports(self, binding)
        viewport = actual
        main_extent = _main_extent(viewport, binding.axis)
        if main_extent <= 0:
            raise RuntimeError(
                "scroll_to_offset requires native viewport metrics or an "
                "explicit numeric main-axis list size"
            )
        max_offset = max(0.0, binding.content_extent - main_extent)
        bounded = min(value, max_offset)
        self._commit_scroll(binding, bounded, viewport, animated=animated)

    def _commit_scroll(
        self,
        binding: _VirtualListBinding,
        offset: float,
        viewport: ViewportRect,
        *,
        animated: bool,
        target_index: int | None = None,
        target_main_start: float | None = None,
        target_main_end: float | None = None,
    ) -> None:
        """Queue one scroll effect and stage the destination window state."""
        handle = self._scroll_ref.current
        if handle is None:
            raise RuntimeError("Virtual list is not mounted")
        axis = binding.axis
        main_extent = _main_extent(viewport, axis)
        cross_extent = _cross_extent(viewport, axis)
        planning = _rect_from_main(offset, main_extent, cross_extent, axis)
        actual_state = viewport if animated else planning
        runtime = current_runtime()
        if runtime is None:
            raise RuntimeError(
                "scroll_to_offset must run in an event handler or async callback"
            )
        runtime._queue_native_effect(
            ScrollToEffect(
                handle,
                offset_x=(offset if axis == "horizontal" else 0),
                offset_y=(offset if axis == "vertical" else 0),
                animated=animated,
            )
        )
        state_value = binding.window_state.value
        next_state = replace(
            state_value,
            viewport=planning,
            actual_viewport=actual_state,
            target_index=target_index,
            target_main_start=target_main_start,
            target_main_end=target_main_end,
            target_source=(
                _source_identity(binding.source) if target_index is not None else None
            ),
            anchor_index=None,
            anchor_offset=None,
        )
        index_near = _index_near_offset(binding.layout)
        if index_near is not None:
            measurements = state_value.measurements
            resolver = _resolver(measurements, binding.source)
            anchor_index = _anchor_index_near(
                binding.layout, offset, binding.source.item_count, resolver
            )
            if anchor_index is not None:
                anchor_offset = _main_component(
                    binding.layout.offset_for_index(
                        anchor_index,
                        measurement_for_index=resolver,
                    ),
                    axis,
                )
                next_state = replace(
                    next_state,
                    anchor_index=anchor_index,
                    anchor_offset=anchor_offset,
                )
        if next_state != state_value:
            binding.window_state.set(next_state)


@dataclass(frozen=True)
class VirtualListSpec:
    """Complete explicit input to the private generic virtual-list engine."""

    source: VirtualizedDataSource
    controller: GenericVirtualListController
    render_item: Callable[[Any, int, Any], Element]
    layout: VirtualLayout
    axis: Literal["vertical", "horizontal"]
    initial_item_count: int
    overscan: float
    max_render_ahead_viewports: float
    max_offscreen_items: int
    scroll_props: FrozenMap = FrozenMap()
    key_for_item: Callable[[Any, int], Any] | None = None
    key_registry: KeyRegistry | None = None
    estimated_viewport_extent: float | None = None
    estimated_cross_extent: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, VirtualizedDataSource):
            raise TypeError("source must implement VirtualizedDataSource")
        if not isinstance(self.controller, GenericVirtualListController):
            raise TypeError("controller must be GenericVirtualListController")
        if not callable(self.render_item):
            raise TypeError("render_item must be callable")
        if not isinstance(self.layout, VirtualLayout):
            raise TypeError("layout must implement VirtualLayout")
        if self.axis not in {"vertical", "horizontal"}:
            raise ValueError("axis must be 'vertical' or 'horizontal'")
        if type(self.initial_item_count) is not int:
            raise TypeError("initial_item_count must be an integer")
        if self.initial_item_count < 0:
            raise ValueError("initial_item_count must be non-negative")
        if isinstance(self.overscan, bool) or not isinstance(
            self.overscan, int | float
        ):
            raise TypeError("overscan must be a number")
        overscan = float(self.overscan)
        if not math.isfinite(overscan) or overscan < 0:
            raise ValueError("overscan must be a finite non-negative number")
        object.__setattr__(self, "overscan", overscan)
        if isinstance(self.max_render_ahead_viewports, bool) or not isinstance(
            self.max_render_ahead_viewports,
            int | float,
        ):
            raise TypeError("max_render_ahead_viewports must be a number")
        render_ahead = float(self.max_render_ahead_viewports)
        if not math.isfinite(render_ahead) or render_ahead < 0:
            raise ValueError(
                "max_render_ahead_viewports must be a finite non-negative number"
            )
        object.__setattr__(self, "max_render_ahead_viewports", render_ahead)
        if type(self.max_offscreen_items) is not int:
            raise TypeError("max_offscreen_items must be an integer")
        if self.max_offscreen_items < 0:
            raise ValueError("max_offscreen_items must be non-negative")
        if self.key_for_item is not None and not callable(self.key_for_item):
            raise TypeError("key_for_item must be callable or None")
        if self.key_registry is not None and not isinstance(
            self.key_registry,
            KeyRegistry,
        ):
            raise TypeError("key_registry must be KeyRegistry or None")
        item_count = self.source.item_count
        if type(item_count) is not int:
            raise TypeError("source item_count must be an integer")
        if item_count < 0:
            raise ValueError("source item_count must be non-negative")
        if not isinstance(self.scroll_props, Mapping):
            raise TypeError("scroll_props must be a mapping")
        reserved = _RESERVED_SCROLL_PROPS.intersection(self.scroll_props)
        if reserved:
            names = ", ".join(sorted(reserved))
            raise ValueError(f"The virtual-list controller owns {names}")
        frozen_props = FrozenMap(
            (name, freeze(value)) for name, value in self.scroll_props.items()
        )
        object.__setattr__(self, "scroll_props", frozen_props)
        main_name = "height" if self.axis == "vertical" else "width"
        cross_name = "width" if self.axis == "vertical" else "height"
        if self.estimated_viewport_extent is None:
            object.__setattr__(
                self,
                "estimated_viewport_extent",
                _declared_extent(frozen_props, main_name),
            )
        if self.estimated_cross_extent is None:
            object.__setattr__(
                self,
                "estimated_cross_extent",
                _declared_extent(frozen_props, cross_name),
            )


@component
def render_generic_virtual_list(spec: VirtualListSpec) -> Element:
    """Render one generic list: plan, compose, and bind the controller."""
    source = spec.source
    layout = spec.layout
    axis = spec.axis
    runtime = current_runtime()
    if runtime is None:
        raise RuntimeError("VirtualList must render inside a Runtime")

    window_state = state(
        _VirtualListWindowState(
            axis=axis,
            viewport=None,
            actual_viewport=None,
            target_index=None,
            target_main_start=None,
            target_main_end=None,
            target_source=None,
            anchor_index=None,
            anchor_offset=None,
        )
    )
    observed = window_state.value
    if (
        observed.axis != axis
        or observed.viewport is None
        or observed.actual_viewport is None
    ):
        # A flipped axis invalidates the retained window exactly like a fresh
        # occurrence: the previous axis's viewport geometry cannot be reused
        # on the new axis, and the controller cache already resets on axis
        # change (``_accept_runtime_binding``).  Start from the declared
        # pre-metrics viewport instead.
        actual, planning = _initial_viewports(spec)
    else:
        actual = observed.actual_viewport
        planning = observed.viewport
    realization = _realization_viewport(actual, planning, spec.overscan, axis)
    measurements = observed.measurements

    def measurement_for_index(index: int) -> CellMeasurement | None:
        key = _source_key(source, index)
        return measurements.get(key)

    # A pending target must never wedge or mis-target the render: retain it
    # only while the current source is the same accepted data the command
    # targeted and the index is still in range.  Any sequence or custom-source
    # replacement — even at an unchanged item count — cancels the target, and
    # a stale target is cleared from the window state by the next scroll
    # observation (never during render, which must not mutate state), so a
    # shrink followed by a grow before any scroll can never resurrect it.
    request_target = observed.target_index
    if request_target is not None and (
        observed.target_source is not _source_identity(source)
        or request_target >= source.item_count
    ):
        request_target = None
    request = LayoutRequest(
        item_count=source.item_count,
        viewport=actual,
        realization_viewport=realization,
        measurement_for_index=measurement_for_index,
        target_index=request_target,
        initial_item_count=spec.initial_item_count,
        max_offscreen_items=spec.max_offscreen_items,
    )
    result = layout.place(request)
    selected = select_placements(request, result, axis=axis)
    safe_actual = _accepted_safe_actual(
        result.placements, selected, request, axis, spec.overscan
    )

    candidate_registry = derive_candidate_key_registry(
        spec.controller._key_registry,
        spec.key_registry,
        source,
        spec.key_for_item,
    )
    render_spec = replace(spec, key_registry=candidate_registry)
    keyed_placements: list[tuple[VirtualPlacement, Any]] = [
        (placement, _source_key(source, placement.index)) for placement in selected
    ]
    realized_keys = frozenset(key for _, key in keyed_placements)

    binding = _VirtualListBinding(
        window_state=window_state,
        source=source,
        layout=layout,
        axis=axis,
        key_registry=candidate_registry,
        realized_keys=realized_keys,
        overscan=spec.overscan,
        max_render_ahead_viewports=spec.max_render_ahead_viewports,
        max_offscreen_items=spec.max_offscreen_items,
        initial_item_count=spec.initial_item_count,
        estimated_viewport_extent=spec.estimated_viewport_extent,
        estimated_cross_extent=spec.estimated_cross_extent,
        content_extent=_main_extent(result, axis),
        actual_viewport=actual,
        planning_viewport=planning,
    )
    runtime._stage_imperative_binding(
        spec.controller,
        binding,
        anchor_ref=spec.controller._scroll_ref,
    )

    request_item_count = request.item_count
    content_main = _main_extent(result, axis)

    def observe_scroll(event: Any) -> None:
        actual_rect = _axis_viewport_rect(event, axis)
        projected_rect = _projected_axis_viewport_rect(event, axis)
        planning_rect = (
            _capped_planning_rect(
                projected_rect,
                actual_rect,
                spec.max_render_ahead_viewports,
                axis,
            )
            if projected_rect is not None
            else actual_rect
        )
        # Native offsets never exceed the accepted content bounds; clamp
        # defensively so anchor and planning math stay inside the content
        # even when a fling overshoots or the source shrank between frames.
        actual_rect = _clamp_rect_main(actual_rect, content_main, axis)
        planning_rect = _clamp_rect_main(planning_rect, content_main, axis)
        # Record the accepted physical viewport before any no-op coverage
        # return: commands must keep observing the latest native position
        # even when the scroll produces no render or acknowledgement.
        spec.controller._observe_viewport(actual_rect)
        current = window_state.value
        clear_target = False
        if current.target_index is not None:
            if (
                current.target_source is not _source_identity(source)
                or current.target_index >= source.item_count
            ):
                # The pending target belongs to different accepted data or
                # no longer exists; drop it so renders stop carrying a dead
                # mandatory placement and a later grow cannot resurrect it.
                clear_target = True
            elif (
                current.target_main_start is not None
                and current.target_main_end is not None
            ):
                view_start = _main_offset(actual_rect, axis)
                view_stop = view_start + _main_extent(actual_rect, axis)
                clear_target = (
                    current.target_main_start < view_stop
                    and view_start < current.target_main_end
                )
        if (
            not clear_target
            and source.item_count == request_item_count
            and _rect_contains(safe_actual, actual_rect)
            and _rect_contains(realization, planning_rect)
        ):
            return
        next_state = replace(
            current,
            viewport=planning_rect,
            actual_viewport=actual_rect,
            target_index=(None if clear_target else current.target_index),
            target_main_start=(None if clear_target else current.target_main_start),
            target_main_end=(None if clear_target else current.target_main_end),
            target_source=(None if clear_target else current.target_source),
        )
        index_near = _index_near_offset(layout)
        anchor_index: int | None = None
        anchor_offset: float | None = None
        if index_near is not None and not actual_rect.empty:
            resolver = _resolver(current.measurements, source)
            anchor_index = _anchor_index_near(
                layout,
                _main_offset(actual_rect, axis),
                source.item_count,
                resolver,
            )
            if anchor_index is not None:
                anchor_offset = _main_component(
                    layout.offset_for_index(
                        anchor_index,
                        measurement_for_index=resolver,
                    ),
                    axis,
                )
        next_state = replace(
            next_state,
            anchor_index=anchor_index,
            anchor_offset=anchor_offset,
        )
        window_state.set(next_state)

    def on_layout_metrics(event: Any, key: Any) -> None:
        measurement = _measurement_from_event(event)
        if measurement is None:
            return
        current = window_state.value
        if current.measurements.get(key) == measurement:
            return
        measurements_new = dict(current.measurements)
        if key in measurements_new:
            measurements_new.pop(key)
        measurements_new[key] = measurement
        if len(measurements_new) > _MEASUREMENT_CACHE_LIMIT:
            oldest = next(iter(measurements_new))
            measurements_new.pop(oldest)
        next_state = replace(current, measurements=measurements_new)

        index_near = _index_near_offset(layout)
        if index_near is None:
            window_state.set(next_state)
            return
        anchor_index = current.anchor_index
        anchor_offset = current.anchor_offset
        if (
            anchor_index is None
            and current.actual_viewport is not None
            and not current.actual_viewport.empty
        ):
            resolver_old = _resolver(current.measurements, source)
            anchor_offset = _main_offset(current.actual_viewport, axis)
            anchor_index = _anchor_index_near(
                layout, anchor_offset, source.item_count, resolver_old
            )
            if anchor_index is not None:
                anchor_offset = _main_component(
                    layout.offset_for_index(
                        anchor_index,
                        measurement_for_index=resolver_old,
                    ),
                    axis,
                )
        if anchor_index is None or current.viewport is None:
            window_state.set(
                replace(
                    next_state,
                    anchor_index=anchor_index,
                    anchor_offset=anchor_offset,
                )
            )
            return
        new_anchor = _main_component(
            layout.offset_for_index(
                anchor_index,
                measurement_for_index=_resolver(measurements_new, source),
            ),
            axis,
        )
        assert anchor_offset is not None
        delta = new_anchor - anchor_offset
        if abs(delta) <= _ANCHOR_EPSILON:
            window_state.set(
                replace(
                    next_state,
                    anchor_index=anchor_index,
                    anchor_offset=anchor_offset,
                )
            )
            return
        viewport = current.viewport
        main_extent = _main_extent(viewport, axis)
        max_offset = max(0.0, content_main - main_extent)
        planning_main = min(
            max(_main_offset(viewport, axis) + delta, 0.0),
            max_offset,
        )
        shifted_planning = _rect_from_main(
            planning_main,
            main_extent,
            _cross_extent(viewport, axis),
            axis,
        )
        shifted_actual = None
        if current.actual_viewport is not None:
            actual = current.actual_viewport
            actual_main = min(
                max(_main_offset(actual, axis) + delta, 0.0),
                max_offset,
            )
            shifted_actual = _rect_from_main(
                actual_main,
                _main_extent(actual, axis),
                _cross_extent(actual, axis),
                axis,
            )
        handle = spec.controller._scroll_ref.current
        if handle is not None:
            runtime._queue_native_effect(
                ScrollToEffect(
                    handle,
                    offset_x=(planning_main if axis == "horizontal" else 0.0),
                    offset_y=(planning_main if axis == "vertical" else 0.0),
                    animated=False,
                )
            )
        window_state.set(
            replace(
                next_state,
                viewport=shifted_planning,
                actual_viewport=(
                    shifted_actual
                    if shifted_actual is not None
                    else current.actual_viewport
                ),
                anchor_index=anchor_index,
                anchor_offset=new_anchor,
            )
        )

    def measurement_listener(key: Any) -> Any:
        def handler(event: Any) -> None:
            on_layout_metrics(event, key)

        return latest(handler)

    def observe_seek(event: Any) -> None:
        render_spec.controller.scroll_to_offset(
            _axis_seek_offset(event, axis),
            animated=False,
        )

    seek_handler = (
        latest(observe_seek)
        if render_spec.scroll_props.get("interactive_scrollbar") is True
        else None
    )
    return compose_generic_window(
        render_spec,
        keyed_placements,
        content_width=result.content_width,
        content_height=result.content_height,
        initial_offset=_main_offset(planning, axis),
        on_scroll_metrics=latest(observe_scroll),
        on_scroll_seek=seek_handler,
        on_layout_metrics=measurement_listener,
    )


def compose_generic_window(
    spec: VirtualListSpec,
    keyed_placements: list[tuple[VirtualPlacement, Any]],
    *,
    content_width: float,
    content_height: float,
    initial_offset: float,
    on_scroll_metrics: Callable[..., Any],
    on_scroll_seek: Callable[..., Any] | None = None,
    on_layout_metrics: Callable[[Any], Any],
) -> Element:
    """Compose positioned cell wrappers inside a canonical content Box.

    The cross-axis dimension falls back to ``match_parent`` only when it is
    still unknown (zero, because no native metrics arrived yet); the main-axis
    extent — including an intentional zero — is preserved as a number.
    """
    vertical = spec.axis == "vertical"
    children: list[Element] = []
    seen_keys: set[Any] = set()
    registry = spec.key_registry
    use_registry = registry is not None and not getattr(
        spec.source, "uses_index_keys", False
    )
    for placement, key in keyed_placements:
        if key in seen_keys:
            raise ValueError(f"Duplicate list key {key!r} at index {placement.index}")
        seen_keys.add(key)
        if use_registry:
            assert registry is not None
            previous_index = registry.key_to_index.get(key)
            if previous_index is not None and previous_index != placement.index:
                raise ValueError(
                    f"Duplicate list key {key!r} at index {placement.index} "
                    f"(already realized at index {previous_index})"
                )
            registry.key_to_index[key] = placement.index
        rendered = normalize_child(
            spec.render_item(
                spec.source.item_at(placement.index),
                placement.index,
                key,
            )
        )
        if vertical:
            cell_props: dict[str, Any] = {
                "width": (placement.width if placement.width > 0 else "match_parent"),
                "height": placement.height,
                "translation_x": placement.x,
                "translation_y": placement.y,
                "on_layout_metrics": on_layout_metrics(key),
            }
        else:
            cell_props = {
                "width": placement.width,
                "height": (
                    placement.height if placement.height > 0 else "match_parent"
                ),
                "translation_x": placement.x,
                "translation_y": placement.y,
                "on_layout_metrics": on_layout_metrics(key),
            }
        sticky = placement.sticky
        if sticky is not None:
            # Private native sticky metadata (bounds before edge).  The
            # natural translation props above still carry the placed
            # position; the native host applies the per-frame displacement.
            cell_props["_virtual_sticky_boundary_start"] = sticky.boundary_start
            cell_props["_virtual_sticky_boundary_end"] = sticky.boundary_end
            cell_props["_virtual_sticky_edge"] = sticky.edge
        children.append(
            Box(
                rendered,
                key=("__vyne_virtual_cell__", key),
                **cell_props,
            )
        )
    if vertical:
        content_props: dict[str, Any] = {
            "width": content_width if content_width > 0 else "match_parent",
            "height": content_height,
        }
    else:
        content_props = {
            "width": content_width,
            "height": (content_height if content_height > 0 else "match_parent"),
        }
    # Mark the content Box only when the accepted window includes a sticky
    # placement.  The native scroll host gates its per-frame sticky pass on
    # the marker, so ordinary (non-sticky) virtual lists pay only an O(1)
    # marker check per scroll frame instead of an O(realized) child loop.
    # The realization contract requires a layout to return a sticky candidate
    # whenever its boundary interval intersects the realization viewport, so
    # a future active sticky is composed (and re-emits the marker) in the
    # same commit that first needs it.
    if any(placement.sticky is not None for placement, _key in keyed_placements):
        content_props["_virtual_content"] = True
    # Publish semantic content size independently of platform measurement.
    # Each host enforces it with its native content-size mechanism. No platform
    # workaround appears as a fake child in the Python element tree.
    content_props["_virtual_content_width"] = content_width
    content_props["_virtual_content_height"] = content_height
    content = Box(
        *children,
        key=("__vyne_virtual_content__",),
        **content_props,
    )
    props = dict(spec.scroll_props.items())
    props["on_scroll_metrics"] = on_scroll_metrics
    if on_scroll_seek is not None:
        props["on_scroll_seek"] = on_scroll_seek
    props["_virtual_list_initial_offset"] = initial_offset
    scroll_factory = Scroll if vertical else _horizontal_scroll
    return scroll_factory(
        content,
        ref=spec.controller._scroll_ref,
        **props,
    )


# ---------------------------------------------------------------------------
# viewport helpers
# ---------------------------------------------------------------------------


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


def _rect_from_main(
    main_offset: float,
    main_extent: float,
    cross_extent: float,
    axis: Literal["vertical", "horizontal"],
) -> ViewportRect:
    if axis == "vertical":
        return ViewportRect(0.0, main_offset, cross_extent, main_extent)
    return ViewportRect(main_offset, 0.0, main_extent, cross_extent)


def _main_offset(
    rect_or_placement: ViewportRect | VirtualPlacement,
    axis: Literal["vertical", "horizontal"],
) -> float:
    return rect_or_placement.y if axis == "vertical" else rect_or_placement.x


def _main_extent(
    rect_or_result: ViewportRect | VirtualPlacement | LayoutResult,
    axis: Literal["vertical", "horizontal"],
) -> float:
    if isinstance(rect_or_result, LayoutResult):
        return (
            rect_or_result.content_height
            if axis == "vertical"
            else rect_or_result.content_width
        )
    return rect_or_result.height if axis == "vertical" else rect_or_result.width


def _main_end(
    placement: VirtualPlacement,
    axis: Literal["vertical", "horizontal"],
) -> float:
    return _main_offset(placement, axis) + _main_extent(placement, axis)


def _cross_extent(
    rect_or_placement: ViewportRect | VirtualPlacement,
    axis: Literal["vertical", "horizontal"],
) -> float:
    return rect_or_placement.width if axis == "vertical" else rect_or_placement.height


def _main_component(
    pair: tuple[float, float],
    axis: Literal["vertical", "horizontal"],
) -> float:
    return pair[1] if axis == "vertical" else pair[0]


def _source_key(
    source: VirtualizedDataSource,
    index: int,
) -> Any:
    """Read and canonically validate one source key."""
    key = source.key_at(index)
    validate_canonical_key(key, path=f"list key at index {index}")
    return key


def _source_identity(source: VirtualizedDataSource) -> Any:
    """Identity token for the accepted underlying data of one source.

    A ``SequenceDataSource`` wraps a plain sequence, so its identity is the
    wrapped data object: a state-driven replacement — even at an unchanged
    item count — cancels a pending scroll target instead of silently
    retargeting another item.  A custom ``VirtualData`` source owns its
    identity directly, matching the key registry's data-identity rule.
    """
    return getattr(source, "data", source)


def _initial_viewports(spec: VirtualListSpec) -> tuple[ViewportRect, ViewportRect]:
    """Pre-metrics viewports: the declared extents when present, else zero.

    A known cross extent is retained even when the main extent is unknown, so
    pre-metrics cells can match it instead of collapsing to zero width.
    """
    main = spec.estimated_viewport_extent
    cross = spec.estimated_cross_extent or 0.0
    if main is None or main <= 0:
        rect = (
            ViewportRect(0, 0, cross, 0)
            if spec.axis == "vertical"
            else ViewportRect(0, 0, 0, cross)
        )
        return rect, rect
    return (
        _rect_from_main(0.0, main, cross, spec.axis),
        _rect_from_main(0.0, main, cross, spec.axis),
    )


def _state_viewports(
    binding: _VirtualListBinding,
) -> tuple[ViewportRect, ViewportRect]:
    """Accepted viewports carried by the promoted binding.

    The snapshots are immutable and are promoted together with the binding
    only on the native acknowledgement, so controller commands never observe
    candidate viewports from an in-flight commit: a known rejection keeps
    the previous accepted viewports.  Falls back to declared pre-metrics
    viewports when the binding carries none.
    """
    actual = binding.actual_viewport
    planning = binding.planning_viewport
    if actual is not None and planning is not None:
        return actual, planning
    main = binding.estimated_viewport_extent
    cross = binding.estimated_cross_extent or 0.0
    if main is None or main <= 0:
        rect = (
            ViewportRect(0, 0, cross, 0)
            if binding.axis == "vertical"
            else ViewportRect(0, 0, 0, cross)
        )
        return rect, rect
    return (
        _rect_from_main(0.0, main, cross, binding.axis),
        _rect_from_main(0.0, main, cross, binding.axis),
    )


def _preferred_viewports(
    controller: GenericVirtualListController,
    binding: _VirtualListBinding,
) -> tuple[ViewportRect, ViewportRect]:
    """Preferred current viewports for one controller command.

    A real native scroll is recorded in the controller's accepted
    observation cache before any no-op coverage return, so the cache stays
    current even when the scroll stays inside accepted coverage and
    produces no render or acknowledgement (the promoted binding snapshot is
    stale).  Commands prefer the observed actual viewport and fall back to
    the promoted binding snapshots (or the declared pre-metrics viewport)
    before the first native event.  The snapshot is never read from the
    journaled candidate ``window_state``: a command issued while a commit
    is in flight — or after a known rejection — must act on the last
    accepted position, not on an un-acknowledged destination.
    """
    actual, planning = _state_viewports(binding)
    if controller._viewport is not None:
        return controller._viewport, planning
    return actual, planning


def _realization_viewport(
    actual: ViewportRect,
    planning: ViewportRect,
    overscan: float,
    axis: Literal["vertical", "horizontal"],
) -> ViewportRect:
    """Actual→projected span plus overscan on the main axis.

    The cross axis mirrors the viewport span exactly; scrolling never changes
    it, and layouts bound cross-axis candidates from the viewport geometry.
    """
    if axis == "vertical":
        main_start = min(actual.y, planning.y)
        main_stop = max(actual.y + actual.height, planning.y + planning.height)
        margin = overscan * max(actual.height, planning.height)
        cross_start = min(actual.x, planning.x)
        cross_stop = max(actual.x + actual.width, planning.x + planning.width)
    else:
        main_start = min(actual.x, planning.x)
        main_stop = max(actual.x + actual.width, planning.x + planning.width)
        margin = overscan * max(actual.width, planning.width)
        cross_start = min(actual.y, planning.y)
        cross_stop = max(actual.y + actual.height, planning.y + planning.height)
    main_start = max(0.0, main_start - margin)
    main_stop += margin
    if axis == "vertical":
        return ViewportRect(
            cross_start,
            main_start,
            cross_stop - cross_start,
            main_stop - main_start,
        )
    return ViewportRect(
        main_start,
        cross_start,
        main_stop - main_start,
        cross_stop - cross_start,
    )


def _capped_planning_rect(
    projected: ViewportRect,
    actual: ViewportRect,
    cap: float,
    axis: Literal["vertical", "horizontal"],
) -> ViewportRect:
    """Bound the projection span so one commit cannot mount unbounded cells.

    A backward fling may reach at most ``cap`` viewports behind the actual
    viewport and a forward fling at most ``cap`` ahead; ``0`` stays
    unbounded, preserving the old fixed engine's symmetric cap.
    """
    if cap <= 0 or _main_extent(actual, axis) <= 0:
        return projected
    main_actual = _main_offset(actual, axis)
    low = max(0.0, main_actual - _main_extent(actual, axis) * cap)
    high = main_actual + _main_extent(actual, axis) * cap
    bounded = min(max(_main_offset(projected, axis), low), high)
    return _rect_from_main(
        bounded,
        _main_extent(projected, axis),
        _cross_extent(projected, axis),
        axis,
    )


def _accepted_safe_actual(
    candidates: tuple[VirtualPlacement, ...],
    selected: tuple[VirtualPlacement, ...],
    request: LayoutRequest,
    axis: Literal["vertical", "horizontal"],
    overscan: float,
) -> ViewportRect:
    """Coverage the accepted render actually guarantees for the actual viewport.

    The realization rect is only safe when every candidate relevant to it
    (by natural geometry or sticky boundary interval — the same predicate
    the filter uses) was selected, because a strict offscreen budget drops
    the rest.  When candidates were dropped, the local overscan band around
    the actual viewport is safe only if every candidate relevant to it was
    selected; otherwise only the exact actual viewport is guaranteed
    mounted.  The decision is set-membership on the accepted selection,
    never a geometric coverage heuristic.
    """
    selected_indices = {placement.index for placement in selected}
    realization = request.realization_viewport
    actual = request.viewport
    eligible = [
        placement
        for placement in candidates
        if placement_relevant(placement, realization, axis)
    ]
    if eligible and all(placement.index in selected_indices for placement in eligible):
        return realization
    local = _realization_viewport(actual, actual, overscan, axis)
    local_eligible = [
        placement
        for placement in candidates
        if placement_relevant(placement, local, axis)
    ]
    if local_eligible and all(
        placement.index in selected_indices for placement in local_eligible
    ):
        return local
    return actual


def _clamp_rect_main(
    rect: ViewportRect,
    content_extent: float,
    axis: Literal["vertical", "horizontal"],
) -> ViewportRect:
    """Clamp a viewport's main-axis offset to the content scroll bounds."""
    main_extent = _main_extent(rect, axis)
    if main_extent <= 0:
        return rect
    max_offset = max(0.0, content_extent - main_extent)
    main = min(max(_main_offset(rect, axis), 0.0), max_offset)
    return _rect_from_main(main, main_extent, _cross_extent(rect, axis), axis)


def _rect_contains(outer: ViewportRect, inner: ViewportRect) -> bool:
    return (
        inner.x >= outer.x
        and inner.y >= outer.y
        and inner.x + inner.width <= outer.x + outer.width
        and inner.y + inner.height <= outer.y + outer.height
    )


def _axis_viewport_rect(
    event: Any,
    axis: Literal["vertical", "horizontal"],
) -> ViewportRect:
    getter = getattr(event, "get", None)
    if getter is None:
        raise TypeError("scroll_metrics event must provide get(name)")
    if axis == "vertical":
        return ViewportRect(
            0.0,
            float(getter("offset_y")),
            float(getter("viewport_width")),
            float(getter("viewport_height")),
        )
    return ViewportRect(
        float(getter("offset_x")),
        0.0,
        float(getter("viewport_width")),
        float(getter("viewport_height")),
    )


def _projected_axis_viewport_rect(
    event: Any,
    axis: Literal["vertical", "horizontal"],
) -> ViewportRect | None:
    """Read the native fling/drag projection, or None when it is absent."""
    getter = getattr(event, "get", None)
    if getter is None:
        raise TypeError("scroll_metrics event must provide get(name)")
    name = "projected_offset_y" if axis == "vertical" else "projected_offset_x"
    projected = getter(name)
    if isinstance(projected, bool) or not isinstance(projected, int | float):
        return None
    value = float(projected)
    if not math.isfinite(value) or value < 0:
        return None
    if axis == "vertical":
        return ViewportRect(
            0.0,
            value,
            float(getter("viewport_width")),
            float(getter("viewport_height")),
        )
    return ViewportRect(
        value,
        0.0,
        float(getter("viewport_width")),
        float(getter("viewport_height")),
    )


def _measurement_from_event(event: Any) -> CellMeasurement | None:
    """Extract one finite non-negative measurement, or None when invalid."""
    getter = getattr(event, "get", None)
    if getter is None:
        return None
    width = getter("width")
    height = getter("height")
    if isinstance(width, bool) or not isinstance(width, int | float):
        return None
    if isinstance(height, bool) or not isinstance(height, int | float):
        return None
    value_width = float(width)
    value_height = float(height)
    if (
        not math.isfinite(value_width)
        or not math.isfinite(value_height)
        or value_width < 0
        or value_height < 0
    ):
        return None
    return CellMeasurement(value_width, value_height)


def _index_near_offset(layout: VirtualLayout) -> Callable[..., Any] | None:
    """Return the optional ``index_near_offset`` method, or None."""
    method = getattr(layout, "index_near_offset", None)
    return method if callable(method) else None


def _anchor_index_near(
    layout: VirtualLayout,
    offset: float,
    item_count: int,
    measurement_for_index: Callable[[int], CellMeasurement | None],
) -> int | None:
    """Resolve the optional ``index_near_offset`` anchor with validation.

    ``None`` means the layout provides no anchor at this offset and disables
    anchor preservation.  A malformed result (non-integer or out of the item
    range) raises a clear error instead of reaching ``offset_for_index``
    with a broken index.
    """
    index_near = _index_near_offset(layout)
    if index_near is None:
        return None
    anchor = index_near(offset, measurement_for_index=measurement_for_index)
    if anchor is None:
        return None
    if type(anchor) is not int:
        raise TypeError(
            "layout index_near_offset must return an integer or None; "
            f"got {type(anchor).__name__}"
        )
    if anchor < 0 or anchor >= item_count:
        raise ValueError(
            f"layout index_near_offset returned out-of-range index "
            f"{anchor} for item_count {item_count}"
        )
    return anchor


def _resolver(
    measurements: Mapping[Any, CellMeasurement],
    source: VirtualizedDataSource,
) -> Callable[[int], CellMeasurement | None]:
    """Build an index→measurement resolver keyed by stable source key.

    Resolving an index requires only the source's O(1) ``key_at`` random
    access — never a scan of the item sequence — and every key is validated
    before dict use.
    """

    def resolve(index: int) -> CellMeasurement | None:
        key = _source_key(source, index)
        return measurements.get(key)

    return resolve


def _declared_extent(props: Mapping[str, Any], name: str) -> float | None:
    """Numeric or ``<number>dp`` declared size, or None."""
    value = props.get(name)
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
