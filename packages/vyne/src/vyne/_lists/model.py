"""Immutable values used by the virtualized-list window planner.

All intervals use Python's half-open convention: ``[start, stop)``.  The
planner works in logical units and does not know about Android pixels, widget
classes, application data, or render callbacks.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal, Protocol, runtime_checkable


def _finite_non_negative(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


@dataclass(frozen=True, order=True)
class IndexRange:
    """One half-open item-index interval."""

    start: int
    stop: int

    def __post_init__(self) -> None:
        if type(self.start) is not int or type(self.stop) is not int:
            raise TypeError("IndexRange bounds must be integers")
        if self.start < 0:
            raise ValueError("IndexRange start must be non-negative")
        if self.stop < self.start:
            raise ValueError("IndexRange stop must be greater than or equal to start")

    @property
    def empty(self) -> bool:
        return self.start == self.stop

    @property
    def item_count(self) -> int:
        return self.stop - self.start


@dataclass(frozen=True)
class RenderMask:
    """Normalized disjoint item ranges that must have real rendered cells."""

    ranges: tuple[IndexRange, ...] = ()

    def __post_init__(self) -> None:
        previous_stop = -1
        for item_range in self.ranges:
            if not isinstance(item_range, IndexRange):
                raise TypeError("RenderMask ranges must contain IndexRange values")
            if item_range.empty:
                raise ValueError("RenderMask must not contain empty ranges")
            if item_range.start <= previous_stop:
                raise ValueError(
                    "RenderMask ranges must be sorted, disjoint, and non-adjacent"
                )
            previous_stop = item_range.stop

    @classmethod
    def from_ranges(cls, *ranges: IndexRange) -> RenderMask:
        """Build a normalized mask, merging overlapping or adjacent ranges."""
        non_empty = sorted((item for item in ranges if not item.empty), key=lambda x: x.start)
        if not non_empty:
            return cls()
        merged: list[IndexRange] = [non_empty[0]]
        for item_range in non_empty[1:]:
            previous = merged[-1]
            if item_range.start <= previous.stop:
                merged[-1] = IndexRange(previous.start, max(previous.stop, item_range.stop))
            else:
                merged.append(item_range)
        return cls(tuple(merged))

    @property
    def empty(self) -> bool:
        return not self.ranges

    @property
    def item_count(self) -> int:
        return sum(item_range.item_count for item_range in self.ranges)

    def contains(self, index: int) -> bool:
        if type(index) is not int or index < 0:
            return False
        return any(item_range.start <= index < item_range.stop for item_range in self.ranges)

    def union(self, other: RenderMask) -> RenderMask:
        if not isinstance(other, RenderMask):
            raise TypeError("RenderMask can only be combined with another RenderMask")
        return RenderMask.from_ranges(*self.ranges, *other.ranges)

    def constrained(self, item_count: int) -> RenderMask:
        if type(item_count) is not int:
            raise TypeError("item_count must be an integer")
        if item_count < 0:
            raise ValueError("item_count must be non-negative")
        return RenderMask.from_ranges(*(
            IndexRange(
                min(item_range.start, item_count),
                min(item_range.stop, item_count),
            )
            for item_range in self.ranges
            if item_range.start < item_count
        ))


@dataclass(frozen=True)
class ViewportMetrics:
    """Axis-neutral native scroll measurements in logical units."""

    offset: float
    extent: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "offset",
            _finite_non_negative(self.offset, name="viewport offset"),
        )
        object.__setattr__(
            self,
            "extent",
            _finite_non_negative(self.extent, name="viewport extent"),
        )


@dataclass(frozen=True)
class WindowConfig:
    """Explicit bounded-window policy. Public defaults are intentionally absent.

    The projection cap lives here so the private fixed engine and the public
    ``List`` share one policy value; velocity prediction and reversal
    retention were removed because the public API always set them to zero.
    """

    overscan_viewports: float
    max_render_ahead_viewports: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "overscan_viewports",
            _finite_non_negative(
                self.overscan_viewports,
                name="overscan_viewports",
            ),
        )
        object.__setattr__(
            self,
            "max_render_ahead_viewports",
            _finite_non_negative(
                self.max_render_ahead_viewports,
                name="max_render_ahead_viewports",
            ),
        )


@dataclass(frozen=True)
class WindowSelection:
    """The full Python render mask chosen for one viewport observation."""

    mask: RenderMask

    def __post_init__(self) -> None:
        if not isinstance(self.mask, RenderMask):
            raise TypeError("WindowSelection mask must be RenderMask")


@runtime_checkable
class ItemLayout(Protocol):
    """Strategy used to map logical offsets to item-index ranges."""

    @property
    def item_count(self) -> int: ...

    @property
    def total_extent(self) -> float: ...

    def range_for_interval(self, start_offset: float, stop_offset: float) -> IndexRange: ...

    def offset_for_index(self, index: int) -> float: ...


@dataclass(frozen=True)
class FixedExtentLayout:
    """O(1) layout strategy for equally sized list items or rows."""

    item_count: int
    item_extent: float

    def __post_init__(self) -> None:
        if type(self.item_count) is not int:
            raise TypeError("item_count must be an integer")
        if self.item_count < 0:
            raise ValueError("item_count must be non-negative")
        if isinstance(self.item_extent, bool) or not isinstance(
            self.item_extent, int | float
        ):
            raise TypeError("item_extent must be a finite positive number")
        extent = float(self.item_extent)
        if not math.isfinite(extent) or extent < 1:
            raise ValueError(
                "item_extent must be finite and at least 1 logical unit"
            )
        object.__setattr__(self, "item_extent", extent)

    @property
    def total_extent(self) -> float:
        return self.item_count * self.item_extent

    def range_for_interval(self, start_offset: float, stop_offset: float) -> IndexRange:
        start = _finite_non_negative(start_offset, name="start_offset")
        stop = _finite_non_negative(stop_offset, name="stop_offset")
        if stop < start:
            raise ValueError("stop_offset must be greater than or equal to start_offset")
        if self.item_count == 0 or stop == start:
            return IndexRange(0, 0)
        bounded_start = min(start, self.total_extent)
        bounded_stop = min(stop, self.total_extent)
        if bounded_stop <= bounded_start:
            return IndexRange(self.item_count, self.item_count)
        first = min(self.item_count, math.floor(bounded_start / self.item_extent))
        last = min(self.item_count, math.ceil(bounded_stop / self.item_extent))
        return IndexRange(first, max(first, last))

    def offset_for_index(self, index: int) -> float:
        if type(index) is not int:
            raise TypeError("index must be an integer")
        if index < 0 or index > self.item_count:
            raise IndexError(
                f"index {index} outside layout boundary 0..{self.item_count}"
            )
        return index * self.item_extent


@dataclass(frozen=True)
class SpacerSegment:
    """Blank logical space replacing one unrendered item range."""

    start: int
    stop: int
    extent: float
    kind: Literal["spacer"] = "spacer"


@dataclass(frozen=True)
class ItemRangeSegment:
    """One contiguous range whose cells must be composed and rendered."""

    start: int
    stop: int
    kind: Literal["items"] = "items"


@dataclass(frozen=True)
class WindowPlan:
    """Pure planner output: a render mask and complete content segmentation."""

    mask: RenderMask
    segments: tuple[SpacerSegment | ItemRangeSegment, ...]
    total_extent: float
