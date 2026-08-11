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
    required_viewport: ViewportMetrics | None = None,
) -> WindowSelection:
    """Select bounded coverage with symmetric overscan and path coverage.

    The viewport is the planning target (actual or capped projected).  A
    symmetric ``overscan_viewports`` margin is added on both sides, and
    ``required_viewport`` (the actual viewport) extends the span so the
    scroll path between "here" and "there" stays rendered as one window.
    The projected render-ahead cap is applied by the caller before this
    function; velocity prediction and reversal retention were removed in M4
    because no public path used them.
    """
    if not isinstance(layout, ItemLayout):
        raise TypeError("layout must implement ItemLayout")
    if not isinstance(viewport, ViewportMetrics):
        raise TypeError("viewport must be ViewportMetrics")
    if not isinstance(config, WindowConfig):
        raise TypeError("config must be WindowConfig")
    if not isinstance(retained, RenderMask):
        raise TypeError("retained must be RenderMask")
    if required_viewport is not None and not isinstance(
        required_viewport,
        ViewportMetrics,
    ):
        raise TypeError("required_viewport must be ViewportMetrics or None")

    item_count = layout.item_count
    if type(item_count) is not int or item_count < 0:
        raise ValueError("layout.item_count must be a non-negative integer")

    bounded_offset = min(
        viewport.offset,
        max(0.0, layout.total_extent - viewport.extent),
    )
    margin = viewport.extent * config.overscan_viewports
    interval_start = max(0.0, bounded_offset - margin)
    interval_stop = min(
        layout.total_extent,
        bounded_offset + viewport.extent + margin,
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
    coverage = IndexRange(
        min(coverage.start, item_count),
        min(coverage.stop, item_count),
    )
    mask = RenderMask.from_ranges(coverage).union(retained.constrained(item_count))
    return WindowSelection(mask=mask)


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
