"""Public generic-list contracts and the host-independent realization filter.

This module is deliberately pure Python: no Runtime, no Elements, no native
binding, no data access.  A custom layout receives a :class:`LayoutRequest`
describing the coverage the framework computed, returns a :class:`LayoutResult`
of candidate :class:`VirtualPlacement` values, and the framework's
:func:`select_placements` filter applies the realization policy:

- placements intersecting the actual viewport are mandatory;
- sticky placements whose main-axis boundary interval intersects the actual
  viewport are retained (headers and footers bounded to their section);
- the requested ``target_index`` is retained and the layout must return it;
- other candidates are kept only inside the realization viewport, and at most
  ``max_offscreen_items`` of them, nearest first, deterministically.

M1 scope is exactly this contract layer.  The generic ``VirtualList``
component, measurement events, controllers, and native positioning are
implemented in later milestones.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
from typing import Any, Literal, Protocol, runtime_checkable


def _finite_non_negative(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


@runtime_checkable
class VirtualData(Protocol):
    """Random-access item and identity adapter for virtualized content.

    A normal ``Sequence`` is adapted automatically by the framework; a
    ``VirtualData`` implementation is only needed for lazy or paged sources.

    Implementations may additionally expose ``index_for_key(key) -> int | None``
    so a controller can resolve a stable key to its current index without
    scanning the source.  It is discovered with ``getattr`` and is not part of
    this protocol.
    """

    @property
    def item_count(self) -> int: ...

    def item_at(self, index: int) -> Any: ...

    def key_at(self, index: int) -> Any: ...


@dataclass(frozen=True)
class ViewportRect:
    """Axis-neutral viewport rectangle in logical units.

    Intervals are half-open: a rect covers ``[x, x + width) × [y, y + height)``.
    Zero-area rects intersect nothing.
    """

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _finite_non_negative(self.x, name="x"))
        object.__setattr__(self, "y", _finite_non_negative(self.y, name="y"))
        object.__setattr__(
            self, "width", _finite_non_negative(self.width, name="width")
        )
        object.__setattr__(
            self, "height", _finite_non_negative(self.height, name="height")
        )

    @property
    def empty(self) -> bool:
        """True when the rect has no area (pre-metrics or degenerate)."""
        return self.width <= 0 or self.height <= 0

    def intersects(self, other: "ViewportRect") -> bool:
        """True when the two rects overlap with positive area."""
        if not isinstance(other, ViewportRect):
            raise TypeError("intersects requires a ViewportRect")
        if self.empty or other.empty:
            return False
        return (
            self.x < other.x + other.width
            and other.x < self.x + self.width
            and self.y < other.y + other.height
            and other.y < self.y + self.height
        )


@dataclass(frozen=True)
class CellMeasurement:
    """Measured logical size of one realized cell."""

    width: float
    height: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "width", _finite_non_negative(self.width, name="width")
        )
        object.__setattr__(
            self, "height", _finite_non_negative(self.height, name="height")
        )


@dataclass(frozen=True)
class StickyConstraint:
    """Bound the sticky movement of a header or footer to a layout interval.

    ``edge`` is ``"start"`` (leading viewport edge, a header) or ``"end"``
    (trailing viewport edge, a footer).  ``boundary_start``/``boundary_end``
    delimit the section or other layout-defined interval along the main axis
    that the sticky element may not escape; native scrolling applies the
    constraint and pushes the element off at the next boundary.
    """

    edge: Literal["start", "end"]
    boundary_start: float
    boundary_end: float

    def __post_init__(self) -> None:
        if self.edge not in {"start", "end"}:
            raise ValueError("StickyConstraint edge must be 'start' or 'end'")
        object.__setattr__(
            self,
            "boundary_start",
            _finite_non_negative(self.boundary_start, name="boundary_start"),
        )
        object.__setattr__(
            self,
            "boundary_end",
            _finite_non_negative(self.boundary_end, name="boundary_end"),
        )
        if self.boundary_end <= self.boundary_start:
            raise ValueError(
                "StickyConstraint boundary_end must be greater than boundary_start"
            )


@dataclass(frozen=True)
class VirtualPlacement:
    """One positioned virtual cell returned by a layout."""

    index: int
    x: float
    y: float
    width: float
    height: float
    sticky: StickyConstraint | None = None

    def __post_init__(self) -> None:
        if type(self.index) is not int:
            raise TypeError("VirtualPlacement index must be an integer")
        if self.index < 0:
            raise ValueError("VirtualPlacement index must be non-negative")
        object.__setattr__(self, "x", _finite_non_negative(self.x, name="x"))
        object.__setattr__(self, "y", _finite_non_negative(self.y, name="y"))
        object.__setattr__(
            self, "width", _finite_non_negative(self.width, name="width")
        )
        object.__setattr__(
            self, "height", _finite_non_negative(self.height, name="height")
        )
        if self.sticky is not None and not isinstance(self.sticky, StickyConstraint):
            raise TypeError("VirtualPlacement sticky must be StickyConstraint or None")

    def intersects(self, viewport: ViewportRect) -> bool:
        """True when this placement's geometry overlaps ``viewport``."""
        if not isinstance(viewport, ViewportRect):
            raise TypeError("intersects requires a ViewportRect")
        return ViewportRect(self.x, self.y, self.width, self.height).intersects(
            viewport
        )


@dataclass(frozen=True)
class LayoutResult:
    """Complete candidate output of one layout pass.

    Geometry is validated against the declared content extent: every placement
    must be fully contained and each index may appear at most once.
    """

    content_width: float
    content_height: float
    placements: tuple[VirtualPlacement, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "content_width",
            _finite_non_negative(self.content_width, name="content_width"),
        )
        object.__setattr__(
            self,
            "content_height",
            _finite_non_negative(self.content_height, name="content_height"),
        )
        placements = tuple(self.placements)
        for placement in placements:
            if not isinstance(placement, VirtualPlacement):
                raise TypeError(
                    "LayoutResult placements must contain VirtualPlacement values"
                )
        seen: set[int] = set()
        for placement in placements:
            if placement.index in seen:
                raise ValueError(f"Duplicate placement index {placement.index}")
            seen.add(placement.index)
            if placement.x + placement.width > self.content_width:
                raise ValueError(
                    f"Placement {placement.index} exceeds content width "
                    f"{self.content_width}"
                )
            if placement.y + placement.height > self.content_height:
                raise ValueError(
                    f"Placement {placement.index} exceeds content height "
                    f"{self.content_height}"
                )
        object.__setattr__(self, "placements", placements)


@dataclass(frozen=True)
class LayoutRequest:
    """One framework-computed layout query.

    ``viewport`` is the actual viewport.  ``realization_viewport`` is the
    framework-computed coverage of actual, projected, and overscan regions;
    candidates outside it are not realized unless mandatory.
    ``measurement_for_index`` lets a layout ask for a measured size by current
    index while the framework retains measurements by stable source key.  The
    callback returns ``None`` for unmeasured cells and must be side-effect
    free.  ``max_offscreen_items == 0`` means an unbounded offscreen allowance.
    """

    item_count: int
    viewport: ViewportRect
    realization_viewport: ViewportRect
    measurement_for_index: Callable[[int], CellMeasurement | None]
    target_index: int | None = None
    initial_item_count: int = 5
    max_offscreen_items: int = 0

    def __post_init__(self) -> None:
        if type(self.item_count) is not int:
            raise TypeError("item_count must be an integer")
        if self.item_count < 0:
            raise ValueError("item_count must be non-negative")
        if not isinstance(self.viewport, ViewportRect):
            raise TypeError("viewport must be a ViewportRect")
        if not isinstance(self.realization_viewport, ViewportRect):
            raise TypeError("realization_viewport must be a ViewportRect")
        if not callable(self.measurement_for_index):
            raise TypeError("measurement_for_index must be callable")
        if self.target_index is not None:
            if type(self.target_index) is not int:
                raise TypeError("target_index must be an integer or None")
            if not 0 <= self.target_index < self.item_count:
                raise ValueError(
                    f"target_index {self.target_index} outside item range "
                    f"0..{self.item_count - 1}"
                )
        if type(self.initial_item_count) is not int:
            raise TypeError("initial_item_count must be an integer")
        if self.initial_item_count < 0:
            raise ValueError("initial_item_count must be non-negative")
        if type(self.max_offscreen_items) is not int:
            raise TypeError("max_offscreen_items must be an integer")
        if self.max_offscreen_items < 0:
            raise ValueError("max_offscreen_items must be non-negative")


@runtime_checkable
class VirtualLayout(Protocol):
    """Strategy that converts a layout request into candidate placements.

    ``place`` must be a pure function of the request: it may read measured
    sizes through ``request.measurement_for_index`` but must not mutate
    framework state or retain request-scoped data.  ``offset_for_index`` maps
    an index to its main-axis scroll target.  A layout may use deterministic
    derived or incremental caches (for example cached lane heights) to avoid
    rescanning the source, as long as the cache is derived purely from
    request data and never mutates framework or transaction state: the same
    request must produce the same placements and content extent regardless
    of cache state.

    Sticky placements must be returned as candidates whenever their
    layout-defined boundary interval intersects the realization viewport
    (half-open), not only when their natural geometry or the actual viewport
    overlaps: the realization filter retains them from those candidates, and
    the engine's no-frame coverage decision depends on their presence so a
    scroll into a section never finds its sticky header or footer unmounted.

    Implementations may optionally expose ``index_near_offset`` for snapping;
    it is discovered with ``getattr`` and is not part of this protocol.

    Implementations whose ``place`` and ``offset_for_index`` never read
    ``measurement_for_index`` (fixed-extent layouts) may declare
    ``uses_measurements = False``; the engine then skips the per-cell
    layout-metrics listeners entirely, which removes one listener operation
    per cell per commit and all per-cell measurement event traffic.  The
    attribute is discovered with ``getattr`` and defaults to True.
    """

    def place(self, request: LayoutRequest) -> LayoutResult: ...

    def offset_for_index(
        self,
        index: int,
        *,
        measurement_for_index: Callable[[int], CellMeasurement | None],
    ) -> tuple[float, float]: ...


@dataclass(frozen=True)
class FixedLinearLayout:
    """Public fixed-extent linear layout conforming to :class:`VirtualLayout`.

    All cells share one ``item_extent`` along the scroll axis.  The
    offset-to-index range is O(1); placement generation is O(realized).  The
    item count and measurements come from the request, so the layout is
    stateless and never inspects item values.
    """

    item_extent: float
    axis: Literal["vertical", "horizontal"] = "vertical"

    # Fixed extents: ``place`` and ``offset_for_index`` never read measured
    # sizes, so the engine can skip per-cell measurement listeners.
    uses_measurements = False

    def __post_init__(self) -> None:
        if isinstance(self.item_extent, bool) or not isinstance(
            self.item_extent, int | float
        ):
            raise TypeError("item_extent must be a finite number at least 1")
        extent = float(self.item_extent)
        if not math.isfinite(extent) or extent < 1:
            raise ValueError("item_extent must be finite and at least 1 logical unit")
        object.__setattr__(self, "item_extent", extent)
        if self.axis not in {"vertical", "horizontal"}:
            raise ValueError("axis must be 'vertical' or 'horizontal'")

    def place(self, request: LayoutRequest) -> LayoutResult:
        if not isinstance(request, LayoutRequest):
            raise TypeError("place requires a LayoutRequest")
        extent = self.item_extent
        item_count = request.item_count
        content_extent = item_count * extent
        if self.axis == "vertical":
            content_width = request.viewport.width
            content_height = content_extent
            main_start = request.realization_viewport.y
            main_stop = (
                request.realization_viewport.y + request.realization_viewport.height
            )
        else:
            content_width = content_extent
            content_height = request.viewport.height
            main_start = request.realization_viewport.x
            main_stop = (
                request.realization_viewport.x + request.realization_viewport.width
            )
        first, last = self._index_range(main_start, main_stop, item_count)
        if first == last and request.viewport.empty and item_count > 0:
            # Pre-metrics: no native size yet (the realization viewport may
            # itself be empty or degenerate), so realize the requested
            # initial window so the first frame is not blank.
            first = 0
            last = min(item_count, request.initial_item_count)
        indices = set(range(first, last))
        if request.target_index is not None and request.target_index not in indices:
            indices.add(request.target_index)
        placements: list[VirtualPlacement] = []
        for index in sorted(indices):
            if self.axis == "vertical":
                placements.append(
                    VirtualPlacement(index, 0.0, index * extent, content_width, extent)
                )
            else:
                placements.append(
                    VirtualPlacement(index, index * extent, 0.0, extent, content_height)
                )
        return LayoutResult(content_width, content_height, tuple(placements))

    def offset_for_index(
        self,
        index: int,
        *,
        measurement_for_index: Callable[[int], CellMeasurement | None],
    ) -> tuple[float, float]:
        if type(index) is not int:
            raise TypeError("index must be an integer")
        if index < 0:
            raise ValueError("index must be non-negative")
        if self.axis == "vertical":
            return (0.0, index * self.item_extent)
        return (index * self.item_extent, 0.0)

    def _index_range(
        self, start: float, stop: float, item_count: int
    ) -> tuple[int, int]:
        """Return the O(1) half-open index span for one main-axis interval."""
        if item_count == 0 or stop <= start:
            return (0, 0)
        total = item_count * self.item_extent
        bounded_start = min(start, total)
        bounded_stop = min(stop, total)
        if bounded_stop <= bounded_start:
            return (item_count, item_count)
        first = min(item_count, math.floor(bounded_start / self.item_extent))
        last = min(item_count, math.ceil(bounded_stop / self.item_extent))
        return (first, max(first, last))


def select_placements(
    request: LayoutRequest,
    result: LayoutResult,
    *,
    axis: Literal["vertical", "horizontal"],
) -> tuple[VirtualPlacement, ...]:
    """Apply the framework realization policy to a layout's candidates.

    Mandatory placements are always kept:

    - placements intersecting the actual viewport;
    - sticky placements whose main-axis boundary interval intersects the
      actual viewport (bounded section headers and footers);
    - the requested ``target_index`` placement (the layout must return it).

    Other candidates are kept only when they are relevant to the realization
    viewport — intersecting it by natural geometry or, for sticky
    placements, by their boundary interval — and at most
    ``max_offscreen_items`` of them — nearest to the actual viewport first,
    deterministically, with ``0`` meaning unbounded.  The offscreen
    allowance never drops mandatory placements.  When no placement is
    mandatory because no metrics exist yet, the first
    ``initial_item_count`` placements are realized as the initial window.

    Returns the selected placements sorted by index for deterministic
    composition.  This filter deliberately does not guess omitted geometry:
    it cannot know about grid gaps or cells the layout chose not to return.
    """
    if not isinstance(request, LayoutRequest):
        raise TypeError("request must be a LayoutRequest")
    if not isinstance(result, LayoutResult):
        raise TypeError("result must be a LayoutResult")
    if axis not in {"vertical", "horizontal"}:
        raise ValueError("axis must be 'vertical' or 'horizontal'")

    main_axis_extent = (
        result.content_height if axis == "vertical" else result.content_width
    )
    for placement in result.placements:
        if placement.index >= request.item_count:
            raise ValueError(
                f"Placement index {placement.index} is out of range for "
                f"item_count {request.item_count}"
            )
        _validate_sticky(placement, axis, main_axis_extent)

    if request.target_index is not None and not any(
        placement.index == request.target_index for placement in result.placements
    ):
        raise ValueError(
            "Layout must return a placement for the requested target index "
            f"{request.target_index}"
        )

    mandatory: list[VirtualPlacement] = []
    optional: list[VirtualPlacement] = []
    for placement in result.placements:
        if _is_mandatory(placement, request, axis):
            mandatory.append(placement)
        else:
            optional.append(placement)

    if not mandatory and request.target_index is None and request.viewport.empty:
        by_index = sorted(result.placements, key=lambda p: p.index)
        mandatory = list(by_index[: request.initial_item_count])
        optional = list(by_index[request.initial_item_count :])

    optional = [
        placement
        for placement in optional
        if placement_relevant(placement, request.realization_viewport, axis)
    ]

    if request.max_offscreen_items > 0:
        optional.sort(key=_distance_key(request.viewport))
        optional = optional[: request.max_offscreen_items]

    selected = mandatory + optional
    selected.sort(key=lambda p: p.index)
    return tuple(selected)


def _validate_sticky(
    placement: VirtualPlacement,
    axis: Literal["vertical", "horizontal"],
    main_axis_extent: float,
) -> None:
    """Reject sticky geometry that contradicts the layout result.

    A sticky element is bounded to a section interval along the main axis:
    the boundaries must lie within the declared content extent, and the
    placement's natural main-axis interval (its placed geometry) must be
    inside those boundaries.  Both are pure structural checks: a header
    placed outside its own section, or a section extending past the content
    extent, would produce an unrecoverable native constraint.
    """
    sticky = placement.sticky
    if sticky is None:
        return
    if sticky.boundary_end > main_axis_extent:
        raise ValueError(
            f"Sticky placement {placement.index} boundary end "
            f"{sticky.boundary_end} exceeds {axis} content extent "
            f"{main_axis_extent}"
        )
    if axis == "vertical":
        natural_start = placement.y
        natural_stop = placement.y + placement.height
    else:
        natural_start = placement.x
        natural_stop = placement.x + placement.width
    if sticky.boundary_start > natural_start or natural_stop > sticky.boundary_end:
        raise ValueError(
            f"Sticky placement {placement.index} natural interval "
            f"[{natural_start}, {natural_stop}) lies outside its boundary "
            f"interval [{sticky.boundary_start}, {sticky.boundary_end})"
        )


def _is_mandatory(
    placement: VirtualPlacement,
    request: LayoutRequest,
    axis: Literal["vertical", "horizontal"],
) -> bool:
    if request.target_index is not None and placement.index == request.target_index:
        return True
    return placement_relevant(placement, request.viewport, axis)


def placement_relevant(
    placement: VirtualPlacement,
    viewport: ViewportRect,
    axis: Literal["vertical", "horizontal"],
) -> bool:
    """True when a placement matters for the given viewport.

    Natural geometry counts as before.  A sticky placement is additionally
    relevant when its layout-defined boundary interval intersects the
    viewport (half-open): the boundary interval is what activates and
    deactivates the sticky during scrolling, so a section scrolled into the
    viewport must retain its sticky header and footer even while their
    placed geometry is still off screen.  The filter uses this predicate for
    the realization viewport, the engine's safe-coverage decision uses it
    for the same viewport, and ``_is_mandatory`` uses it for the actual
    viewport, so all three share one half-open boundary implementation.
    """
    if placement.intersects(viewport):
        return True
    sticky = placement.sticky
    if sticky is None:
        return False
    if axis == "vertical":
        interval_start = viewport.y
        interval_stop = viewport.y + viewport.height
    else:
        interval_start = viewport.x
        interval_stop = viewport.x + viewport.width
    return (
        sticky.boundary_start < interval_stop and interval_start < sticky.boundary_end
    )


def _distance_key(
    viewport: ViewportRect,
) -> Callable[[VirtualPlacement], tuple[float, int]]:
    center_x = viewport.x + viewport.width / 2
    center_y = viewport.y + viewport.height / 2

    def key(placement: VirtualPlacement) -> tuple[float, int]:
        placement_center_x = placement.x + placement.width / 2
        placement_center_y = placement.y + placement.height / 2
        squared = (placement_center_x - center_x) ** 2 + (
            placement_center_y - center_y
        ) ** 2
        return (squared, placement.index)

    return key
