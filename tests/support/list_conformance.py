"""Public-contract list conformance fixtures for M1.

These layouts are implemented only against the public ``vyne.lists``
contracts.  They double as conformance fixtures proving an external layout can
build grids, staggered content, and flattened sections (with sticky headers and
footers) without touching the private engine or any Runtime machinery.
"""

from __future__ import annotations

import math

from vyne.lists import (
    LayoutRequest,
    LayoutResult,
    StickyConstraint,
    VirtualPlacement,
)


class UniformGridLayout:
    """A 2D uniform grid: ``columns`` fixed-width cells of equal size.

    Candidate generation is bounded to the realization viewport rows rather
    than scanning the whole item count.
    """

    def __init__(self, columns: int, cell_size: float, gap: float = 0.0) -> None:
        if type(columns) is not int or columns < 1:
            raise ValueError("columns must be a positive integer")
        self.columns = columns
        self.cell_size = cell_size
        self.gap = gap

    def place(self, request: LayoutRequest) -> LayoutResult:
        columns = self.columns
        cell = self.cell_size
        gap = self.gap
        pitch = cell + gap
        item_count = request.item_count
        content_width = columns * cell + (columns - 1) * gap
        rows = math.ceil(item_count / columns) if item_count else 0
        content_height = rows * cell + (rows - 1) * gap if rows else 0.0

        real_start = request.realization_viewport.y
        real_stop = real_start + request.realization_viewport.height
        first_row = max(0, math.floor(real_start / pitch) - 1)
        last_row = min(rows - 1, math.ceil(real_stop / pitch) + 1) if rows else -1
        first_index = first_row * columns
        last_index = min(item_count, (last_row + 1) * columns)

        placements: list[VirtualPlacement] = []
        for index in range(first_index, last_index):
            row = index // columns
            column = index % columns
            placements.append(
                VirtualPlacement(
                    index,
                    column * pitch,
                    row * pitch,
                    cell,
                    cell,
                )
            )
        if request.target_index is not None and not any(
            p.index == request.target_index for p in placements
        ):
            row = request.target_index // columns
            column = request.target_index % columns
            placements.append(
                VirtualPlacement(
                    request.target_index,
                    column * pitch,
                    row * pitch,
                    cell,
                    cell,
                )
            )
        return LayoutResult(content_width, content_height, tuple(placements))

    def offset_for_index(
        self,
        index: int,
        *,
        measurement_for_index,
    ) -> tuple[float, float]:
        if type(index) is not int or index < 0:
            raise ValueError("index must be a non-negative integer")
        row = index // self.columns
        column = index % self.columns
        return (
            column * (self.cell_size + self.gap),
            row * (self.cell_size + self.gap),
        )


class StaggeredLayout:
    """A two-lane masonry-like fixture with measured per-item heights.

    Heights come from ``request.measurement_for_index`` when available and
    fall back to ``default_height``.  Each item lands at the top of the
    shorter lane.  The scan stops once every lane is past the realization
    viewport, so ``measurement_for_index`` is only consulted for the bounded
    leading portion of the source.

    ``content_height`` is a conservative full-source estimate: the exact
    scanned lane heights plus ``default_height`` for every unmeasured item
    still to be placed, distributed at ``ceil(remaining / lanes)`` per lane.
    The estimate is O(1) after the scan and never scans the tail, so a
    shallow viewport keeps candidate and measurement access bounded while
    the declared content extent still grows with ``item_count``.
    """

    def __init__(
        self,
        lanes: int = 2,
        width: float = 100.0,
        default_height: float = 50.0,
    ) -> None:
        if type(lanes) is not int or lanes < 1:
            raise ValueError("lanes must be a positive integer")
        self.lanes = lanes
        self.width = width
        self.default_height = default_height

    def place(self, request: LayoutRequest) -> LayoutResult:
        lanes = self.lanes
        width = self.width
        content_width = lanes * width
        lane_heights = [0.0] * lanes
        placements: list[VirtualPlacement] = []
        target = request.target_index
        stop_y = request.realization_viewport.y + request.realization_viewport.height
        margin = self.default_height
        index = 0
        while index < request.item_count:
            measured = request.measurement_for_index(index)
            height = measured.height if measured is not None else self.default_height
            lane = min(range(lanes), key=lambda lane: lane_heights[lane])
            y = lane_heights[lane]
            lane_heights[lane] += height
            margin = max(margin, height)
            if index == target or y < stop_y + margin:
                placements.append(
                    VirtualPlacement(index, lane * width, y, width, height)
                )
            index += 1
            if min(lane_heights) >= stop_y + margin and (
                target is None or index > target
            ):
                break
        remaining = request.item_count - index
        estimated_tail = (
            math.ceil(remaining / lanes) * self.default_height if remaining > 0 else 0.0
        )
        return LayoutResult(
            content_width,
            max(lane_heights) + estimated_tail,
            tuple(placements),
        )

    def offset_for_index(
        self,
        index: int,
        *,
        measurement_for_index,
    ) -> tuple[float, float]:
        if type(index) is not int or index < 0:
            raise ValueError("index must be a non-negative integer")
        # Exact masonry offsets require replaying lane heights, which this
        # fixture deliberately does not do; scroll-to-index/key is an M2
        # engine concern resolved through the real layout.
        return (0.0, float(index) * self.default_height)


class VariableLinearLayout:
    """Single-lane variable-extent layout driven by per-key measurements.

    Unmeasured cells fall back to ``default_extent``.  ``offset_for_index``
    and ``index_near_offset`` replay measured extents from index zero, so
    growing an already-measured cell shifts the offset of every following
    cell.  That is exactly what the M2 engine uses to prove measurement
    reflow and anchor preservation: the layout never scans more than the
    bounded leading portion in ``place`` and never reads item values.
    """

    def __init__(
        self,
        default_extent: float = 50.0,
        axis: str = "vertical",
    ) -> None:
        if isinstance(default_extent, bool) or not isinstance(
            default_extent, int | float
        ):
            raise ValueError("default_extent must be a finite positive number")
        value = float(default_extent)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("default_extent must be a finite positive number")
        if axis not in {"vertical", "horizontal"}:
            raise ValueError("axis must be 'vertical' or 'horizontal'")
        self.default_extent = value
        self.axis = axis

    def _extent_of(self, index: int, measurement_for_index) -> float:
        measured = measurement_for_index(index)
        if measured is None:
            return self.default_extent
        return measured.height if self.axis == "vertical" else measured.width

    def place(self, request: LayoutRequest) -> LayoutResult:
        item_count = request.item_count
        vertical = self.axis == "vertical"
        if vertical:
            main_stop = (
                request.realization_viewport.y + request.realization_viewport.height
            )
            cross = request.viewport.width
        else:
            main_stop = (
                request.realization_viewport.x + request.realization_viewport.width
            )
            cross = request.viewport.height
        margin = self.default_extent
        target = request.target_index
        placements: list[VirtualPlacement] = []
        total = 0.0
        index = 0
        while index < item_count:
            extent = self._extent_of(index, request.measurement_for_index)
            margin = max(margin, extent)
            if index == target or total < main_stop + margin:
                if vertical:
                    placements.append(
                        VirtualPlacement(index, 0.0, total, cross, extent)
                    )
                else:
                    placements.append(
                        VirtualPlacement(index, total, 0.0, extent, cross)
                    )
            total += extent
            index += 1
            if total >= main_stop + margin and (target is None or index > target):
                break
        remaining = item_count - index
        content_main = total + remaining * self.default_extent
        if vertical:
            return LayoutResult(cross, content_main, tuple(placements))
        return LayoutResult(content_main, cross, tuple(placements))

    def offset_for_index(
        self,
        index: int,
        *,
        measurement_for_index,
    ) -> tuple[float, float]:
        if type(index) is not int or index < 0:
            raise ValueError("index must be a non-negative integer")
        total = 0.0
        for i in range(index):
            total += self._extent_of(i, measurement_for_index)
        if self.axis == "vertical":
            return (0.0, total)
        return (total, 0.0)

    def index_near_offset(
        self,
        offset: float,
        *,
        measurement_for_index,
    ) -> int:
        if isinstance(offset, bool) or not isinstance(offset, int | float):
            raise TypeError("offset must be a number")
        value = float(offset)
        if not math.isfinite(value) or value < 0:
            raise ValueError("offset must be a finite non-negative number")
        total = 0.0
        index = 0
        while True:
            extent = self._extent_of(index, measurement_for_index)
            if value < total + extent:
                return index
            total += extent
            index += 1


class SectionedLayout:
    """Flattened-sections fixture with sticky start headers and end footers.

    Item ``i`` belongs to section ``i // items_per_section``.  Within a
    section the slots are: one header, ``section_size`` body rows, one
    footer.  The header carries a ``StickyConstraint("start", ...)`` and the
    footer a ``StickyConstraint("end", ...)`` both bounded to the section's
    main-axis interval.  A sticky is returned as a candidate whenever its
    boundary interval intersects the realization viewport (half-open), not
    only when the actual viewport overlaps: the contract requires sticky
    candidates for the realization viewport so the engine's no-frame
    coverage can guarantee a scrolled-in section header is already mounted.
    """

    def __init__(
        self,
        *,
        section_size: int = 8,
        header_extent: float = 30.0,
        row_extent: float = 20.0,
        footer_extent: float = 40.0,
    ) -> None:
        if type(section_size) is not int or section_size < 0:
            raise ValueError("section_size must be a non-negative integer")
        self.section_size = section_size
        self.header_extent = header_extent
        self.row_extent = row_extent
        self.footer_extent = footer_extent

    def place(self, request: LayoutRequest) -> LayoutResult:
        section_size = self.section_size
        header_extent = self.header_extent
        row_extent = self.row_extent
        footer_extent = self.footer_extent
        items_per_section = section_size + 2
        section_extent = header_extent + section_size * row_extent + footer_extent
        item_count = request.item_count
        total_sections = math.ceil(item_count / items_per_section) if item_count else 0
        content_height = total_sections * section_extent
        content_width = request.viewport.width

        real_start = request.realization_viewport.y
        real_stop = real_start + request.realization_viewport.height
        first_section = max(0, math.floor(real_start / section_extent) - 1)
        last_section = min(
            total_sections - 1,
            math.ceil(real_stop / section_extent) + 1,
        )
        target = request.target_index

        placements: list[VirtualPlacement] = []
        for section in range(first_section, last_section + 1):
            section_top = section * section_extent
            section_bottom = section_top + section_extent
            for slot in range(items_per_section):
                index = section * items_per_section + slot
                if index >= item_count:
                    continue
                if slot == 0:
                    y = section_top
                    height = header_extent
                    sticky = StickyConstraint("start", section_top, section_bottom)
                elif slot <= section_size:
                    y = section_top + header_extent + (slot - 1) * row_extent
                    height = row_extent
                    sticky = None
                else:
                    y = section_top + header_extent + section_size * row_extent
                    height = footer_extent
                    sticky = StickyConstraint("end", section_top, section_bottom)
                if index == target:
                    placements.append(
                        VirtualPlacement(index, 0.0, y, content_width, height, sticky)
                    )
                    continue
                bottom = y + height
                visible = bottom > real_start and y < real_stop
                sticky_relevant = (
                    sticky is not None
                    and sticky.boundary_start < real_stop
                    and real_start < sticky.boundary_end
                )
                if visible or sticky_relevant:
                    placements.append(
                        VirtualPlacement(index, 0.0, y, content_width, height, sticky)
                    )
        return LayoutResult(content_width, content_height, tuple(placements))

    def offset_for_index(
        self,
        index: int,
        *,
        measurement_for_index,
    ) -> tuple[float, float]:
        """Main-axis start of the slot holding ``index``."""
        if type(index) is not int or index < 0:
            raise ValueError("index must be a non-negative integer")
        items_per_section = self.section_size + 2
        section = index // items_per_section
        slot = index % items_per_section
        section_extent = (
            self.header_extent
            + self.section_size * self.row_extent
            + self.footer_extent
        )
        section_top = section * section_extent
        if slot == 0:
            main_start = section_top
        elif slot <= self.section_size:
            main_start = section_top + self.header_extent + (slot - 1) * self.row_extent
        else:
            main_start = (
                section_top + self.header_extent + self.section_size * self.row_extent
            )
        return (0.0, main_start)
