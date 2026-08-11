"""M1 conformance tests for the public generic-list contracts.

These tests use only public ``vyne.lists`` names: the value contracts, the
protocols, the built-in :class:`~vyne.lists.FixedLinearLayout`, the
:func:`~vyne.lists.select_placements` realization filter, and the conformance
fixtures in ``tests.support.list_conformance`` (grid, staggered, sections).
The fixed-engine parity test imports the private planner only as the
reference oracle for identical intervals.
"""

from __future__ import annotations

import random

import pytest

from vyne.lists import (
    CellMeasurement,
    FixedLinearLayout,
    LayoutRequest,
    LayoutResult,
    StickyConstraint,
    ViewportRect,
    VirtualData,
    VirtualLayout,
    VirtualPlacement,
    select_placements,
)

from tests.support.list_conformance import (
    SectionedLayout,
    StaggeredLayout,
    UniformGridLayout,
)

# Fixed-engine reference oracle for the parity tests (identical intervals).
from vyne._lists.model import FixedExtentLayout, ViewportMetrics, WindowConfig
from vyne._lists.window import select_window

_ZERO_CONFIG = WindowConfig(overscan_viewports=0)


def _request(
    item_count: int = 100,
    *,
    viewport: ViewportRect = ViewportRect(0, 0, 300, 100),
    realization: ViewportRect | None = None,
    target_index: int | None = None,
    initial_item_count: int = 5,
    max_offscreen_items: int = 0,
    measurement=None,
) -> LayoutRequest:
    return LayoutRequest(
        item_count=item_count,
        viewport=viewport,
        realization_viewport=realization or viewport,
        measurement_for_index=measurement or (lambda index: None),
        target_index=target_index,
        initial_item_count=initial_item_count,
        max_offscreen_items=max_offscreen_items,
    )


def _indices(selected) -> list[int]:
    return [placement.index for placement in selected]


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class _CountingData:
    def __init__(self, count: int) -> None:
        self.count = count

    @property
    def item_count(self) -> int:
        return self.count

    def item_at(self, index: int) -> object:
        return index

    def key_at(self, index: int) -> int:
        return index

    def index_for_key(self, key: int) -> int | None:
        return key if 0 <= key < self.count else None


class _BrokenData:
    """Missing key_at: does not satisfy VirtualData."""


class _PlaceOnlyLayout:
    """Missing offset_for_index: does not satisfy VirtualLayout."""

    def place(self, request: LayoutRequest) -> LayoutResult:
        return LayoutResult(0, 0, ())


def test_virtual_data_protocol_and_optional_index_for_key() -> None:
    data = _CountingData(10)
    assert isinstance(data, VirtualData)
    assert not isinstance([1, 2, 3], VirtualData)
    assert not isinstance(_BrokenData(), VirtualData)
    # index_for_key is optional and discovered, not required by the protocol.
    index_for_key = getattr(data, "index_for_key", None)
    assert index_for_key is not None and index_for_key(4) == 4
    assert getattr(_CountingData(0), "index_for_key", None) is not None


def test_virtual_layout_protocol_checks() -> None:
    assert isinstance(FixedLinearLayout(10), VirtualLayout)
    assert not isinstance(_PlaceOnlyLayout(), VirtualLayout)


# ---------------------------------------------------------------------------
# FixedLinearLayout
# ---------------------------------------------------------------------------


def test_fixed_linear_vertical_places_realized_range() -> None:
    layout = FixedLinearLayout(10, "vertical")
    request = _request(
        viewport=ViewportRect(0, 500, 300, 100),
        realization=ViewportRect(0, 400, 300, 300),
    )
    result = layout.place(request)

    assert (result.content_width, result.content_height) == (300.0, 1000.0)
    assert [p.index for p in result.placements] == list(range(40, 70))
    assert all(p.x == 0.0 and p.width == 300.0 for p in result.placements)
    assert all(p.height == 10.0 for p in result.placements)
    assert all(p.y == p.index * 10.0 for p in result.placements)

    selected = select_placements(request, result, axis="vertical")
    assert _indices(selected) == list(range(40, 70))


def test_fixed_linear_horizontal_places_realized_range() -> None:
    layout = FixedLinearLayout(10, "horizontal")
    request = _request(
        viewport=ViewportRect(0, 0, 100, 50),
        realization=ViewportRect(400, 0, 300, 50),
    )
    result = layout.place(request)

    assert (result.content_width, result.content_height) == (1000.0, 50.0)
    assert _indices(result.placements) == list(range(40, 70))
    assert all(p.y == 0.0 and p.height == 50.0 for p in result.placements)
    assert all(p.x == p.index * 10.0 for p in result.placements)

    selected = select_placements(request, result, axis="horizontal")
    assert _indices(selected) == list(range(40, 70))


def test_fixed_linear_offset_for_index() -> None:
    layout = FixedLinearLayout(10)
    assert layout.offset_for_index(7, measurement_for_index=lambda i: None) == (
        0.0,
        70.0,
    )
    horizontal = FixedLinearLayout(10, "horizontal")
    assert horizontal.offset_for_index(7, measurement_for_index=lambda i: None) == (
        70.0,
        0.0,
    )
    with pytest.raises(ValueError):
        layout.offset_for_index(-1, measurement_for_index=lambda i: None)


def test_fixed_linear_does_not_call_measurement_callback() -> None:
    calls: list[int] = []

    def measurement(index: int) -> CellMeasurement | None:
        calls.append(index)
        return None

    request = _request(measurement=measurement)
    result = FixedLinearLayout(10).place(request)

    assert result.placements
    assert calls == []


def test_budget_keeps_nearest_offscreen_placements_deterministically() -> None:
    layout = FixedLinearLayout(10, "vertical")
    request = _request(
        viewport=ViewportRect(0, 500, 300, 100),
        realization=ViewportRect(0, 400, 300, 300),
        max_offscreen_items=3,
    )
    result = layout.place(request)

    first = select_placements(request, result, axis="vertical")
    second = select_placements(request, result, axis="vertical")

    # Mandatory visible cells 50..59 always survive; the allowance admits
    # the nearest three offscreen cells (49, 60, 48) deterministically.
    assert _indices(first) == list(range(48, 61))
    assert first == second


def test_budget_never_drops_mandatory_placements() -> None:
    layout = FixedLinearLayout(10, "vertical")
    request = _request(
        viewport=ViewportRect(0, 500, 300, 100),
        realization=ViewportRect(0, 400, 300, 300),
        max_offscreen_items=1,
    )
    result = layout.place(request)

    selected = select_placements(request, result, axis="vertical")

    assert set(range(50, 60)) <= set(_indices(selected))
    assert len(selected) == 11


# ---------------------------------------------------------------------------
# Uniform grid
# ---------------------------------------------------------------------------


def test_uniform_grid_selection_and_budget() -> None:
    layout = UniformGridLayout(columns=2, cell_size=50, gap=0)
    request = _request(
        viewport=ViewportRect(0, 250, 100, 100),
        realization=ViewportRect(0, 200, 100, 250),
    )
    result = layout.place(request)

    assert result.content_width == 100.0
    assert result.content_height == 2500.0
    assert set(_indices(result.placements)) == set(range(6, 22))

    selected = select_placements(request, result, axis="vertical")
    # Rows 5-6 (indices 10-13) intersect the actual viewport and are
    # mandatory; rows 4 and 7-8 (indices 8-9 and 14-17) are offscreen
    # candidates inside the realization viewport and are kept with an
    # unbounded allowance.  The fixture's ±1-row generation margin (rows 3
    # and 9-10) lies outside the realization viewport and is dropped.
    assert set(_indices(selected)) == set(range(8, 18))

    budgeted_request = _request(
        viewport=ViewportRect(0, 250, 100, 100),
        realization=ViewportRect(0, 200, 100, 250),
        max_offscreen_items=4,
    )
    budgeted = select_placements(budgeted_request, result, axis="vertical")
    # Mandatory 10..13 plus the four nearest offscreen cells (8, 9, 14, 15).
    assert set(_indices(budgeted)) == set(range(8, 16))


def test_grid_target_outside_realization_is_added() -> None:
    layout = UniformGridLayout(columns=2, cell_size=50, gap=0)
    request = _request(
        viewport=ViewportRect(0, 250, 100, 100),
        realization=ViewportRect(0, 250, 100, 100),
        target_index=90,
    )
    result = layout.place(request)

    selected = select_placements(request, result, axis="vertical")

    assert 90 in _indices(selected)
    assert 10 in _indices(selected)


# ---------------------------------------------------------------------------
# Staggered / masonry
# ---------------------------------------------------------------------------


def test_staggered_measurement_access_is_bounded_and_lazy() -> None:
    calls: list[int] = []

    def measurement(index: int) -> CellMeasurement | None:
        calls.append(index)
        return CellMeasurement(100, 50)

    layout = StaggeredLayout(lanes=2, width=100, default_height=50)
    request = _request(
        item_count=100,
        viewport=ViewportRect(0, 0, 200, 100),
        realization=ViewportRect(0, 0, 200, 100),
        measurement=measurement,
    )
    result = layout.place(request)

    # The masonry scan stops once every lane is past the realization
    # viewport; a 100-item source consults the callback only for the leading
    # bounded portion, never the full source.
    assert set(_indices(result.placements)) == set(range(0, 6))
    assert calls == [0, 1, 2, 3, 4, 5]
    assert len(calls) < 20

    selected = select_placements(request, result, axis="vertical")
    # Indices 0..3 intersect the actual viewport and are mandatory.
    assert set(_indices(selected)) == set(range(0, 4))


def test_staggered_uses_measured_height_when_available() -> None:
    layout = StaggeredLayout(lanes=1, width=100, default_height=50)
    request = _request(
        item_count=4,
        viewport=ViewportRect(0, 0, 100, 120),
        realization=ViewportRect(0, 0, 100, 120),
        measurement=lambda index: CellMeasurement(100, 100),
    )
    result = layout.place(request)

    # One lane: measured height 100 per cell.  Cells 0-2 start above the
    # realization bottom plus margin; cell 3 would start at y 300 beyond it
    # and is not realized.
    assert [p.y for p in result.placements] == [0.0, 100.0, 200.0]
    assert all(p.height == 100.0 for p in result.placements)
    # content_height estimates the full 4-item source extent: the scanned
    # 300.0 plus the unmeasured tail at default_height (50.0) = 350.0.  The
    # true measured extent (400.0) is never reached without scanning.
    assert result.content_height == 350.0


def test_staggered_content_height_scales_with_item_count() -> None:
    layout = StaggeredLayout(lanes=2, width=100, default_height=50)
    shallow = ViewportRect(0, 0, 200, 100)
    result_1000 = layout.place(_request(item_count=1000, viewport=shallow))
    result_2000 = layout.place(_request(item_count=2000, viewport=shallow))

    # Two lanes at default 50: 1000 items need ceil(1000/2)*50 = 25000 and
    # 2000 items exactly double it, so the estimate scales with item_count
    # while candidates stay bounded to the shallow viewport.
    assert result_1000.content_height == 25_000.0
    assert result_2000.content_height == 50_000.0
    assert result_2000.content_height == 2 * result_1000.content_height
    assert len(result_1000.placements) == 6
    assert len(result_2000.placements) == 6

    # The candidate prefix is identical for both counts: the estimate grows
    # without any extra measurement or scan of the tail.
    assert [p.index for p in result_1000.placements] == [
        p.index for p in result_2000.placements
    ]


# ---------------------------------------------------------------------------
# Sections with sticky headers and footers
# ---------------------------------------------------------------------------


def test_sticky_header_and_footer_both_retained_within_section() -> None:
    layout = SectionedLayout(
        section_size=8, header_extent=30, row_extent=20, footer_extent=40
    )
    request = _request(
        item_count=30,
        viewport=ViewportRect(0, 300, 300, 60),
        realization=ViewportRect(0, 300, 300, 60),
    )
    result = layout.place(request)

    # Section 1 spans y 230..460.  The header (10) and footer (19) are
    # offscreen but their section boundary interval intersects the viewport,
    # so both must be retained simultaneously and bound to their section.
    selected = select_placements(request, result, axis="vertical")

    assert set(_indices(selected)) == {10, 13, 14, 15, 19}
    by_index = {p.index: p for p in selected}
    assert by_index[10].sticky is not None
    assert by_index[10].sticky.edge == "start"
    assert by_index[10].sticky.boundary_start == 230.0
    assert by_index[10].sticky.boundary_end == 460.0
    assert by_index[19].sticky is not None
    assert by_index[19].sticky.edge == "end"
    # Neighbouring sections' stickies are not active.
    assert 0 not in by_index
    assert 20 not in by_index


def test_horizontal_sticky_start_and_end_retained() -> None:
    viewport = ViewportRect(300, 0, 60, 300)
    request = _request(item_count=30, viewport=viewport, realization=viewport)
    placements = (
        VirtualPlacement(10, 230, 0, 30, 300, StickyConstraint("start", 230, 460)),
        VirtualPlacement(13, 300, 0, 20, 300),
        VirtualPlacement(14, 320, 0, 20, 300),
        VirtualPlacement(15, 340, 0, 20, 300),
        VirtualPlacement(19, 420, 0, 40, 300, StickyConstraint("end", 230, 460)),
    )
    result = LayoutResult(460, 300, placements)

    selected = select_placements(request, result, axis="horizontal")

    # The header and footer lie outside the actual x viewport but their
    # section boundary interval [230, 460) intersects it, so both are
    # mandatory; only body row 15 is actually visible.
    assert _indices(selected) == [10, 13, 14, 15, 19]
    by_index = {p.index: p for p in selected}
    assert by_index[10].sticky is not None
    assert by_index[10].sticky.edge == "start"
    assert by_index[19].sticky is not None
    assert by_index[19].sticky.edge == "end"


def test_sticky_boundary_adjacency_is_not_mandatory() -> None:
    # Half-open intervals: a boundary ending exactly at the viewport start
    # and a boundary starting exactly at the viewport end share no overlap
    # with the viewport, so neither placement is mandatory, and both are
    # outside the realization viewport and dropped.
    request = _request(
        item_count=30,
        viewport=ViewportRect(0, 300, 300, 60),
        realization=ViewportRect(0, 300, 300, 60),
    )
    placements = (
        VirtualPlacement(0, 0, 230, 300, 30, StickyConstraint("start", 200, 300)),
        VirtualPlacement(1, 0, 360, 300, 30, StickyConstraint("start", 360, 460)),
    )
    result = LayoutResult(300, 460, placements)

    assert select_placements(request, result, axis="vertical") == ()


def test_inactive_sticky_outside_realization_is_dropped() -> None:
    # The placement's boundary interval [0, 90) does not intersect the
    # viewport [100, 160) and its geometry is outside the realization
    # viewport, so a too-loose filter would wrongly retain it as sticky and
    # the correct filter drops it.
    request = _request(
        item_count=30,
        viewport=ViewportRect(0, 100, 300, 60),
        realization=ViewportRect(0, 100, 300, 60),
    )
    result = LayoutResult(
        300,
        160,
        (VirtualPlacement(0, 0, 0, 300, 30, StickyConstraint("start", 0, 90)),),
    )

    assert select_placements(request, result, axis="vertical") == ()


def test_sticky_relevant_via_realization_boundary_is_kept() -> None:
    # Natural geometry is off screen, but the sticky boundary interval
    # [0, 200) intersects the realization viewport [0, 50): the layout
    # contract requires the candidate for the realization viewport and the
    # filter retains it, so a scroll into the section finds its header
    # already mounted.
    request = _request(
        item_count=30,
        viewport=ViewportRect(0, 0, 100, 50),
        realization=ViewportRect(0, 0, 100, 50),
    )
    result = LayoutResult(
        100,
        400,
        (
            VirtualPlacement(0, 0, 0, 100, 20),
            VirtualPlacement(
                1,
                0,
                180,
                100,
                20,
                sticky=StickyConstraint("start", 0, 200),
            ),
        ),
    )

    selected = select_placements(request, result, axis="vertical")

    assert _indices(selected) == [0, 1]


def test_sticky_relevant_via_realization_boundary_horizontal() -> None:
    request = _request(
        item_count=30,
        viewport=ViewportRect(0, 0, 50, 100),
        realization=ViewportRect(0, 0, 50, 100),
    )
    result = LayoutResult(
        400,
        100,
        (
            VirtualPlacement(0, 0, 0, 20, 100),
            VirtualPlacement(
                1,
                180,
                0,
                20,
                100,
                sticky=StickyConstraint("end", 0, 200),
            ),
        ),
    )

    selected = select_placements(request, result, axis="horizontal")

    assert _indices(selected) == [0, 1]


def test_sticky_boundary_half_open_adjacent_to_realization_dropped() -> None:
    # Half-open intervals: a boundary that starts exactly at the realization
    # viewport end shares no overlap with it, so the sticky is not relevant
    # and is dropped even though its placed geometry is inside the content.
    request = _request(
        item_count=30,
        viewport=ViewportRect(0, 0, 100, 50),
        realization=ViewportRect(0, 0, 100, 50),
    )
    result = LayoutResult(
        100,
        400,
        (
            VirtualPlacement(0, 0, 0, 100, 20),
            VirtualPlacement(
                1,
                0,
                50,
                100,
                20,
                sticky=StickyConstraint("start", 50, 200),
            ),
        ),
    )

    selected = select_placements(request, result, axis="vertical")

    assert _indices(selected) == [0]


def test_sticky_boundary_exceeding_content_extent_rejected() -> None:
    request = _request(item_count=30)
    result = LayoutResult(
        300,
        200,
        (VirtualPlacement(0, 0, 0, 300, 30, StickyConstraint("start", 0, 250)),),
    )

    with pytest.raises(ValueError, match="exceeds"):
        select_placements(request, result, axis="vertical")

    horizontal = LayoutResult(
        200,
        300,
        (VirtualPlacement(0, 0, 0, 30, 300, StickyConstraint("start", 0, 250)),),
    )
    with pytest.raises(ValueError, match="exceeds"):
        select_placements(request, horizontal, axis="horizontal")


def test_sticky_natural_interval_outside_boundary_rejected() -> None:
    request = _request(item_count=30)
    # Header placed above its section start [230, 460).
    above = LayoutResult(
        300,
        460,
        (VirtualPlacement(0, 0, 200, 300, 30, StickyConstraint("start", 230, 460)),),
    )
    with pytest.raises(ValueError, match="lies outside"):
        select_placements(request, above, axis="vertical")
    # Footer placed past its section end [230, 460).
    past = LayoutResult(
        300,
        470,
        (VirtualPlacement(0, 0, 440, 300, 30, StickyConstraint("end", 230, 460)),),
    )
    with pytest.raises(ValueError, match="lies outside"):
        select_placements(request, past, axis="vertical")


# ---------------------------------------------------------------------------
# Targets and validation
# ---------------------------------------------------------------------------


def test_target_outside_viewport_is_retained() -> None:
    layout = FixedLinearLayout(10, "vertical")
    request = _request(
        viewport=ViewportRect(0, 500, 300, 100),
        realization=ViewportRect(0, 500, 300, 100),
        target_index=0,
    )
    result = layout.place(request)

    selected = select_placements(request, result, axis="vertical")

    assert _indices(selected)[0] == 0
    assert set(range(50, 60)) <= set(_indices(selected))


class _TargetIgnoringLayout:
    def place(self, request: LayoutRequest) -> LayoutResult:
        return LayoutResult(
            request.viewport.width,
            request.item_count * 10,
            tuple(
                VirtualPlacement(index, 0.0, index * 10.0, request.viewport.width, 10.0)
                for index in range(0, 5)
            ),
        )

    def offset_for_index(
        self, index: int, *, measurement_for_index
    ) -> tuple[float, float]:
        return (0.0, float(index) * 10.0)


def test_layout_must_return_requested_target() -> None:
    request = _request(target_index=40)
    result = _TargetIgnoringLayout().place(request)

    with pytest.raises(ValueError, match="target index 40"):
        select_placements(request, result, axis="vertical")


def test_empty_source_returns_no_placements() -> None:
    request = _request(item_count=0)
    result = FixedLinearLayout(10).place(request)
    assert result.placements == ()
    assert select_placements(request, result, axis="vertical") == ()

    grid = UniformGridLayout(2, 10).place(request)
    assert grid.placements == ()
    assert grid.content_height == 0.0


def test_pre_metrics_initial_window_fallback() -> None:
    layout = FixedLinearLayout(10, "vertical")
    request = _request(
        viewport=ViewportRect(0, 0, 0, 0),
        realization=ViewportRect(0, 0, 0, 0),
        initial_item_count=5,
    )
    result = layout.place(request)

    selected = select_placements(request, result, axis="vertical")

    assert _indices(selected) == [0, 1, 2, 3, 4]


def test_pre_metrics_with_realization_beyond_content() -> None:
    layout = FixedLinearLayout(10, "vertical")
    request = _request(
        item_count=3,
        viewport=ViewportRect(0, 0, 0, 0),
        realization=ViewportRect(0, 100, 300, 100),
        initial_item_count=5,
    )
    result = layout.place(request)

    # The realization viewport starts beyond the content end, so the
    # interval-to-range projection is empty; the pre-metrics fallback must
    # still realize the initial window instead of leaving the first frame
    # blank.
    assert _indices(result.placements) == [0, 1, 2]
    selected = select_placements(request, result, axis="vertical")
    assert _indices(selected) == [0, 1, 2]


def test_item_extent_domain_aligns_with_fixed_engine() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        FixedLinearLayout(0.5)
    with pytest.raises(ValueError, match="item_extent"):
        FixedLinearLayout(0)
    with pytest.raises(ValueError, match="finite"):
        FixedLinearLayout(float("nan"))
    with pytest.raises(ValueError, match="finite"):
        FixedLinearLayout(float("inf"))
    with pytest.raises(TypeError):
        FixedLinearLayout(True)


def test_select_rejects_out_of_range_indices() -> None:
    request = _request(item_count=10)
    result = LayoutResult(
        300,
        100,
        (VirtualPlacement(0, 0, 0, 10, 10), VirtualPlacement(10, 0, 0, 10, 10)),
    )

    with pytest.raises(ValueError, match="out of range"):
        select_placements(request, result, axis="vertical")


def test_validation_matrix() -> None:
    with pytest.raises(ValueError, match="Duplicate placement index"):
        LayoutResult(
            100,
            100,
            (
                VirtualPlacement(0, 0, 0, 10, 10),
                VirtualPlacement(0, 20, 20, 10, 10),
            ),
        )
    with pytest.raises(ValueError, match="exceeds content width"):
        LayoutResult(100, 100, (VirtualPlacement(0, 95, 0, 10, 10),))
    with pytest.raises(ValueError, match="exceeds content height"):
        LayoutResult(100, 100, (VirtualPlacement(0, 0, 95, 10, 10),))
    with pytest.raises(ValueError, match="boundary_end"):
        StickyConstraint("start", 100, 50)
    with pytest.raises(ValueError, match="edge"):
        StickyConstraint("middle", 0, 10)
    with pytest.raises(ValueError, match="non-negative"):
        VirtualPlacement(0, -1, 0, 10, 10)
    with pytest.raises(ValueError, match="finite"):
        ViewportRect(0, 0, float("nan"), 10)
    with pytest.raises(ValueError, match="finite"):
        CellMeasurement(-1, 10)
    with pytest.raises(ValueError, match="outside item range"):
        _request(item_count=10, target_index=10)
    with pytest.raises(ValueError, match="max_offscreen_items"):
        LayoutRequest(
            item_count=10,
            viewport=ViewportRect(0, 0, 100, 100),
            realization_viewport=ViewportRect(0, 0, 100, 100),
            measurement_for_index=lambda index: None,
            max_offscreen_items=-1,
        )
    with pytest.raises(TypeError, match="place requires"):
        FixedLinearLayout(10).place(object())
    with pytest.raises(TypeError, match="request must be a LayoutRequest"):
        select_placements(object(), LayoutResult(0, 0, ()), axis="vertical")
    with pytest.raises(TypeError, match="sticky"):
        VirtualPlacement(0, 0, 0, 10, 10, sticky="start")
    with pytest.raises(ValueError, match="item_extent"):
        FixedLinearLayout(0)
    with pytest.raises(ValueError, match="axis"):
        FixedLinearLayout(10, "diagonal")


# ---------------------------------------------------------------------------
# Fixed-engine parity
# ---------------------------------------------------------------------------


def _axis_viewport_rect(
    axis: str,
    offset: float,
    viewport_extent: float,
) -> ViewportRect:
    if axis == "vertical":
        return ViewportRect(0, offset, 300, viewport_extent)
    return ViewportRect(offset, 0, viewport_extent, 300)


def _assert_fixed_parity(
    item_count: int,
    extent: float,
    axis: str,
    offset: float,
    viewport_extent: float,
) -> None:
    """Assert public and engine realize identical indices for one interval.

    The engine clamps an out-of-range scroll offset to the end window before
    planning (``_selection_for_offset``), so the parity is defined on the
    clamped offset shared by both paths.
    """
    layout = FixedExtentLayout(item_count, extent)
    bounded_offset = min(
        offset,
        max(0.0, layout.total_extent - viewport_extent),
    )
    viewport = _axis_viewport_rect(axis, bounded_offset, viewport_extent)
    request = _request(
        item_count=item_count,
        viewport=viewport,
        realization=viewport,
    )
    public = _indices(
        select_placements(
            request,
            FixedLinearLayout(extent, axis).place(request),
            axis=axis,
        )
    )
    item_range = layout.range_for_interval(
        bounded_offset,
        bounded_offset + viewport_extent,
    )
    assert public == list(range(item_range.start, item_range.stop))
    selection = select_window(
        layout,
        ViewportMetrics(bounded_offset, viewport_extent),
        _ZERO_CONFIG,
    )
    assert public == [
        index
        for item_range in selection.mask.ranges
        for index in range(item_range.start, item_range.stop)
    ]


def test_fixed_linear_parity_edge_cases() -> None:
    _assert_fixed_parity(10, 10, "vertical", 0, 100)
    _assert_fixed_parity(10, 10, "vertical", 0, 1)
    _assert_fixed_parity(10, 10, "vertical", 50, 100)
    _assert_fixed_parity(10, 10, "vertical", 99.5, 10)
    _assert_fixed_parity(10, 10, "horizontal", 40, 40)
    # Offset beyond the content end clamps to the end window on both sides.
    _assert_fixed_parity(10, 10, "vertical", 10_000, 50)
    _assert_fixed_parity(10, 10, "vertical", 10_000, 100)
    # Offset exactly at the last possible scroll position.
    _assert_fixed_parity(10, 10, "horizontal", 50, 50)
    # Empty sources realize nothing on either side.
    _assert_fixed_parity(0, 10, "vertical", 0, 100)


def test_fixed_linear_parity_property_matches_engine() -> None:
    rng = random.Random(0xC0FFEE)
    for axis in ("vertical", "horizontal"):
        for _ in range(150):
            item_count = rng.choice([0, 1, 2, 3, 7, 10, 50, 100])
            extent = float(rng.choice([1, 2, 10, 33]))
            viewport_extent = float(rng.choice([1, 25, 100, 500]))
            offset = rng.uniform(0.0, item_count * extent * 1.5)
            _assert_fixed_parity(item_count, extent, axis, offset, viewport_extent)


# ---------------------------------------------------------------------------
# Public export surface
# ---------------------------------------------------------------------------


def test_public_lists_all_pins_documented_exports() -> None:
    import vyne.lists as lists_module

    assert lists_module.__all__ == [
        "CellMeasurement",
        "FixedLinearLayout",
        "LayoutRequest",
        "LayoutResult",
        "List",
        "ListController",
        "StickyConstraint",
        "ViewportRect",
        "VirtualData",
        "VirtualLayout",
        "VirtualList",
        "VirtualPlacement",
        "select_placements",
    ]
