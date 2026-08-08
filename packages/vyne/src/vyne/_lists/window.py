"""Pure virtualized-list window planning."""

from __future__ import annotations

from vyne._lists.model import (
    IndexRange,
    ItemLayout,
    ItemRangeSegment,
    RenderMask,
    SpacerSegment,
    ViewportMetrics,
    WindowConfig,
    WindowPlan,
    WindowSelection,
)


def select_window(
    layout: ItemLayout,
    viewport: ViewportMetrics,
    config: WindowConfig,
    *,
    retained: RenderMask = RenderMask(),
    previous_coverage: IndexRange | None = None,
    previous_direction: int = 0,
    required_viewport: ViewportMetrics | None = None,
) -> WindowSelection:
    """Select bounded contiguous coverage with prediction and reversal retention.

    ``required_viewport`` marks the currently visible region. When it lies
    outside the planned interval, the coverage span is extended contiguously
    from the required region through the planned interval, so the scroll path
    between "here" and "there" stays rendered as one window.
    """
    if not isinstance(layout, ItemLayout):
        raise TypeError("layout must implement ItemLayout")
    if not isinstance(viewport, ViewportMetrics):
        raise TypeError("viewport must be ViewportMetrics")
    if not isinstance(config, WindowConfig):
        raise TypeError("config must be WindowConfig")
    if not isinstance(retained, RenderMask):
        raise TypeError("retained must be RenderMask")
    if previous_coverage is not None and not isinstance(
        previous_coverage,
        IndexRange,
    ):
        raise TypeError("previous_coverage must be IndexRange or None")
    if required_viewport is not None and not isinstance(
        required_viewport,
        ViewportMetrics,
    ):
        raise TypeError("required_viewport must be ViewportMetrics or None")
    if type(previous_direction) is not int or previous_direction not in {-1, 0, 1}:
        raise ValueError("previous_direction must be -1, 0, or 1")

    item_count = layout.item_count
    if type(item_count) is not int or item_count < 0:
        raise ValueError("layout.item_count must be a non-negative integer")

    direction = 1 if viewport.velocity > 0 else -1 if viewport.velocity < 0 else 0
    prediction = min(
        abs(viewport.velocity) * config.prediction_horizon_seconds,
        viewport.extent * config.max_prediction_viewports,
    )
    before = viewport.extent * config.overscan_before_viewports
    after = viewport.extent * config.overscan_after_viewports
    if direction < 0:
        before += prediction
    elif direction > 0:
        after += prediction

    bounded_offset = min(
        viewport.offset,
        max(0.0, layout.total_extent - viewport.extent),
    )
    interval_start = max(0.0, bounded_offset - before)
    interval_stop = min(
        layout.total_extent,
        bounded_offset + viewport.extent + after,
    )

    if required_viewport is not None and required_viewport.extent > 0:
        required_offset = min(
            required_viewport.offset,
            max(0.0, layout.total_extent - required_viewport.extent),
        )
        interval_start = min(interval_start, required_offset)
        interval_stop = max(
            interval_stop,
            min(
                layout.total_extent,
                required_offset + required_viewport.extent,
            ),
        )
    coverage = layout.range_for_interval(interval_start, interval_stop)

    reversing = (
        direction != 0
        and previous_direction != 0
        and direction != previous_direction
    )
    if reversing and previous_coverage is not None and not previous_coverage.empty:
        retention = viewport.extent * config.reversal_retention_viewports
        retention_range = layout.range_for_interval(
            max(0.0, bounded_offset - retention),
            min(
                layout.total_extent,
                bounded_offset + viewport.extent + retention,
            ),
        )
        retained_start = max(previous_coverage.start, retention_range.start)
        retained_stop = min(previous_coverage.stop, retention_range.stop)
        if retained_start < retained_stop:
            retained_coverage = IndexRange(retained_start, retained_stop)
            if (
                retained_coverage.start <= coverage.stop
                and coverage.start <= retained_coverage.stop
            ):
                coverage = IndexRange(
                    min(coverage.start, retained_coverage.start),
                    max(coverage.stop, retained_coverage.stop),
                )

    coverage = IndexRange(
        min(coverage.start, item_count),
        min(coverage.stop, item_count),
    )
    mask = RenderMask.from_ranges(coverage).union(retained.constrained(item_count))
    return WindowSelection(mask=mask, coverage=coverage, direction=direction)


def plan_window(
    layout: ItemLayout,
    viewport: ViewportMetrics,
    config: WindowConfig,
    *,
    retained: RenderMask = RenderMask(),
    previous_coverage: IndexRange | None = None,
    previous_direction: int = 0,
    required_viewport: ViewportMetrics | None = None,
) -> WindowPlan:
    """Plan the cells and blank spacers for one viewport observation.

    The function is side-effect free. ``retained`` represents explicit policy
    supplied by the caller, such as an initial region, a focused item, or a
    pinned section header. The planner does not decide which regions deserve
    retention.
    """
    selection = select_window(
        layout,
        viewport,
        config,
        retained=retained,
        previous_coverage=previous_coverage,
        previous_direction=previous_direction,
        required_viewport=required_viewport,
    )
    return plan_mask(layout, selection.mask)


def plan_mask(layout: ItemLayout, mask: RenderMask) -> WindowPlan:
    """Segment a caller-selected render mask without choosing window policy."""
    if not isinstance(layout, ItemLayout):
        raise TypeError("layout must implement ItemLayout")
    if not isinstance(mask, RenderMask):
        raise TypeError("mask must be RenderMask")
    constrained = mask.constrained(layout.item_count)
    return WindowPlan(
        mask=constrained,
        segments=_segments_for_mask(layout, constrained),
        total_extent=layout.total_extent,
    )


def _segments_for_mask(
    layout: ItemLayout,
    mask: RenderMask,
) -> tuple[SpacerSegment | ItemRangeSegment, ...]:
    """Cover the complete data range with alternating spacers and cells."""
    if layout.item_count == 0:
        return ()

    segments: list[SpacerSegment | ItemRangeSegment] = []
    cursor = 0
    for item_range in mask.ranges:
        if cursor < item_range.start:
            segments.append(_spacer(layout, IndexRange(cursor, item_range.start)))
        segments.append(ItemRangeSegment(item_range.start, item_range.stop))
        cursor = item_range.stop
    if cursor < layout.item_count:
        segments.append(_spacer(layout, IndexRange(cursor, layout.item_count)))
    return tuple(segments)


def _spacer(layout: ItemLayout, item_range: IndexRange) -> SpacerSegment:
    return SpacerSegment(
        start=item_range.start,
        stop=item_range.stop,
        extent=(
            layout.offset_for_index(item_range.stop)
            - layout.offset_for_index(item_range.start)
        ),
    )
