"""Pure reference semantics for platform virtual-scroll hosts.

The list engines own data, layout, realization, keys, and controller state.
A platform host owns only frame-sensitive scroll mechanics.  Android and any
future iOS adapter must conform to the axis-neutral functions in this module;
production list hot paths do not call the scrollbar reference functions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Axis = Literal["vertical", "horizontal"]
StickyEdge = Literal["start", "end"]

INTERACTIVE_SCROLLBAR_MIN_THUMB = 40.0
INTERACTIVE_SCROLLBAR_TOUCH_TARGET = 32.0
INTERACTIVE_SCROLLBAR_VISUAL_THICKNESS = 7.0
VIRTUAL_SCROLL_SEEK_EMIT_INTERVAL_MS = 32
VIRTUAL_SCROLL_SEEK_WATCHDOG_MS = 750
VIRTUAL_SCROLL_SEEK_MAX_RETRIES = 2
VIRTUAL_SCROLL_SEEK_TARGET_TOLERANCE = 1


def _finite(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _finite_non_negative(value: object, *, name: str) -> float:
    result = _finite(value, name=name)
    if result < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


def _axis(value: object) -> Axis:
    if value not in {"vertical", "horizontal"}:
        raise ValueError("axis must be 'vertical' or 'horizontal'")
    return value  # type: ignore[return-value]


@dataclass(frozen=True)
class ScrollHostMetrics:
    """Clamped logical metrics published by a platform scroll host."""

    axis: Axis
    offset: float
    viewport_extent: float
    content_extent: float
    projected_offset: float

    def __post_init__(self) -> None:
        axis = _axis(self.axis)
        viewport = _finite_non_negative(self.viewport_extent, name="viewport_extent")
        content = _finite_non_negative(self.content_extent, name="content_extent")
        maximum = max(0.0, content - viewport)
        object.__setattr__(self, "axis", axis)
        object.__setattr__(self, "viewport_extent", viewport)
        object.__setattr__(self, "content_extent", content)
        object.__setattr__(
            self,
            "offset",
            min(_finite_non_negative(self.offset, name="offset"), maximum),
        )
        object.__setattr__(
            self,
            "projected_offset",
            min(
                max(_finite(self.projected_offset, name="projected_offset"), 0.0),
                maximum,
            ),
        )

    @property
    def max_scroll(self) -> float:
        return max(0.0, self.content_extent - self.viewport_extent)


@dataclass(frozen=True)
class ScrollSeekEmission:
    """One throttled destination request emitted to the Python list engine."""

    target: int
    final: bool


class VirtualScrollSeekReference:
    """Portable reference for provisional/latest/final seek state."""

    def __init__(self) -> None:
        self.provisional_target: int | None = None
        self.final_target: int | None = None
        self.retries = 0
        self.last_non_final_emit: int | None = None

    def begin_gesture(self) -> None:
        self.reset()

    def update(
        self, target: int, event_time: int, *, final: bool
    ) -> ScrollSeekEmission | None:
        if type(target) is not int or target < 0:
            raise ValueError("target must be a non-negative integer")
        if type(event_time) is not int or event_time < 0:
            raise ValueError("event_time must be a non-negative integer")
        self.provisional_target = target
        if final:
            self.final_target = target
            self.retries = 0
            return self._emit(target, final=True)
        if (
            self.last_non_final_emit is not None
            and event_time - self.last_non_final_emit
            < VIRTUAL_SCROLL_SEEK_EMIT_INTERVAL_MS
        ):
            return None
        self.last_non_final_emit = event_time
        return self._emit(target, final=False)

    def accept_reveal(self, target: int) -> bool:
        """Accept any prepared reveal while preserving a newer target."""
        if self.provisional_target is None and self.final_target is None:
            return False
        if self._targets_match(self.provisional_target, target):
            self.provisional_target = None
        if self._targets_match(self.final_target, target):
            self.final_target = None
            self.retries = 0
        return True

    def watchdog(self, actual_target: int) -> ScrollSeekEmission | None:
        target = self.final_target
        if target is None:
            return None
        if self._targets_match(actual_target, target):
            self.provisional_target = None
            self.final_target = None
            self.retries = 0
            return None
        if self.retries < VIRTUAL_SCROLL_SEEK_MAX_RETRIES:
            self.retries += 1
            return self._emit(target, final=True)
        self.reset()
        return None

    def display_target(self, actual_target: int) -> int:
        return (
            self.provisional_target
            if self.provisional_target is not None
            else actual_target
        )

    def reset(self) -> None:
        self.provisional_target = None
        self.final_target = None
        self.retries = 0
        self.last_non_final_emit = None

    def _emit(self, target: int, *, final: bool) -> ScrollSeekEmission:
        return ScrollSeekEmission(target, final)

    @staticmethod
    def _targets_match(first: int | None, second: int) -> bool:
        return (
            first is not None
            and abs(first - second) <= VIRTUAL_SCROLL_SEEK_TARGET_TOLERANCE
        )


@dataclass(frozen=True)
class InteractiveScrollbarGeometry:
    """One axis-neutral track/thumb result in logical units."""

    track_start: float
    track_extent: float
    thumb_start: float
    thumb_extent: float
    max_scroll: float

    @property
    def thumb_end(self) -> float:
        return self.thumb_start + self.thumb_extent

    @property
    def thumb_travel(self) -> float:
        return self.track_extent - self.thumb_extent


def sticky_main_position(
    *,
    natural: float,
    extent: float,
    viewport_start: float,
    viewport_end: float,
    boundary_start: float,
    boundary_end: float,
    edge: StickyEdge | None,
) -> float:
    """Return a sticky cell's main position using half-open activation."""
    natural_value = _finite_non_negative(natural, name="natural")
    extent_value = _finite_non_negative(extent, name="extent")
    viewport_start_value = _finite_non_negative(viewport_start, name="viewport_start")
    viewport_end_value = _finite_non_negative(viewport_end, name="viewport_end")
    boundary_start_value = _finite_non_negative(boundary_start, name="boundary_start")
    boundary_end_value = _finite_non_negative(boundary_end, name="boundary_end")
    if viewport_end_value < viewport_start_value:
        raise ValueError("viewport_end must be at least viewport_start")
    if edge not in {None, "start", "end"}:
        raise ValueError("edge must be 'start', 'end', or None")
    if edge is None:
        return natural_value
    if (
        boundary_start_value >= viewport_end_value
        or viewport_start_value >= boundary_end_value
    ):
        return natural_value
    section_extent = boundary_end_value - boundary_start_value
    if section_extent <= 0 or extent_value >= section_extent:
        return natural_value
    upper = boundary_end_value - extent_value
    if edge == "start":
        target = max(natural_value, viewport_start_value)
    else:
        target = min(natural_value, viewport_end_value - extent_value)
    return min(max(target, boundary_start_value), upper)


def interactive_scrollbar_geometry(
    *,
    axis: Axis,
    viewport_extent: float,
    content_extent: float,
    scroll_offset: float,
    track_start: float = 0.0,
    track_extent: float | None = None,
    minimum_thumb_extent: float = INTERACTIVE_SCROLLBAR_MIN_THUMB,
) -> InteractiveScrollbarGeometry | None:
    """Return visible geometry, or ``None`` when content cannot scroll.

    The indicator is on the right edge for ``vertical`` and the bottom edge
    for ``horizontal``.  Those cross-axis placements are host drawing details;
    main-axis geometry is identical and therefore portable.
    """
    _axis(axis)
    viewport = _finite_non_negative(viewport_extent, name="viewport_extent")
    content = _finite_non_negative(content_extent, name="content_extent")
    offset = _finite_non_negative(scroll_offset, name="scroll_offset")
    start = _finite_non_negative(track_start, name="track_start")
    available = (
        viewport
        if track_extent is None
        else _finite_non_negative(track_extent, name="track_extent")
    )
    minimum = _finite_non_negative(minimum_thumb_extent, name="minimum_thumb_extent")
    if available <= 0 or viewport <= 0 or content <= viewport:
        return None
    maximum = content - viewport
    thumb_extent = min(
        available,
        max(minimum, available * viewport / content),
    )
    travel = available - thumb_extent
    fraction = min(offset, maximum) / maximum
    return InteractiveScrollbarGeometry(
        track_start=start,
        track_extent=available,
        thumb_start=start + travel * fraction,
        thumb_extent=thumb_extent,
        max_scroll=maximum,
    )


def interactive_scrollbar_grab_offset(
    pointer_position: float,
    geometry: InteractiveScrollbarGeometry,
) -> float:
    """Preserve an in-thumb grab; a track tap centers the thumb."""
    pointer = _finite_non_negative(pointer_position, name="pointer_position")
    if geometry.thumb_start <= pointer <= geometry.thumb_end:
        return pointer - geometry.thumb_start
    return geometry.thumb_extent / 2.0


def interactive_scrollbar_target(
    *,
    pointer_position: float,
    grab_offset: float,
    geometry: InteractiveScrollbarGeometry,
) -> float:
    """Map a pointer position to a clamped native content offset."""
    pointer = _finite_non_negative(pointer_position, name="pointer_position")
    grabbed = _finite_non_negative(grab_offset, name="grab_offset")
    travel = geometry.thumb_travel
    if travel <= 0 or geometry.max_scroll <= 0:
        return 0.0
    thumb_start = min(
        max(pointer - grabbed, geometry.track_start),
        geometry.track_start + travel,
    )
    return (thumb_start - geometry.track_start) / travel * geometry.max_scroll


def clamp_projected_offset(
    projected_offset: float,
    *,
    viewport_extent: float,
    content_extent: float,
) -> float:
    """Clamp a host's best native landing estimate to its scroll range."""
    projected = _finite(projected_offset, name="projected_offset")
    viewport = _finite_non_negative(viewport_extent, name="viewport_extent")
    content = _finite_non_negative(content_extent, name="content_extent")
    return min(max(projected, 0.0), max(0.0, content - viewport))
