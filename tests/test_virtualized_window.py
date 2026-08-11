from __future__ import annotations

import math
import unittest

from vyne._lists import (
    FixedExtentLayout,
    IndexRange,
    ItemRangeSegment,
    RenderMask,
    SpacerSegment,
    ViewportMetrics,
    WindowConfig,
    plan_mask,
    select_window,
)


class RenderMaskTests(unittest.TestCase):
    def test_ranges_are_normalized_and_adjacent_ranges_merge(self) -> None:
        mask = RenderMask.from_ranges(
            IndexRange(10, 15),
            IndexRange(2, 4),
            IndexRange(4, 8),
            IndexRange(7, 12),
        )

        self.assertEqual(mask.ranges, (IndexRange(2, 15),))
        self.assertEqual(mask.item_count, 13)

    def test_union_preserves_disjoint_regions(self) -> None:
        mask = RenderMask.from_ranges(IndexRange(20, 30)).union(
            RenderMask.from_ranges(IndexRange(0, 5), IndexRange(80, 81))
        )

        self.assertEqual(
            mask.ranges,
            (IndexRange(0, 5), IndexRange(20, 30), IndexRange(80, 81)),
        )
        self.assertTrue(mask.contains(23))
        self.assertFalse(mask.contains(50))

    def test_constraint_drops_and_clips_out_of_bounds_regions(self) -> None:
        mask = RenderMask.from_ranges(
            IndexRange(3, 8),
            IndexRange(20, 30),
        )

        self.assertEqual(
            mask.constrained(5),
            RenderMask.from_ranges(IndexRange(3, 5)),
        )

    def test_invalid_unormalized_mask_rejects(self) -> None:
        with self.assertRaisesRegex(ValueError, "sorted, disjoint"):
            RenderMask((IndexRange(0, 3), IndexRange(3, 4)))


class FixedExtentLayoutTests(unittest.TestCase):
    def test_interval_uses_half_open_boundaries(self) -> None:
        layout = FixedExtentLayout(item_count=100, item_extent=50)

        self.assertEqual(layout.range_for_interval(0, 100), IndexRange(0, 2))
        self.assertEqual(layout.range_for_interval(25, 75), IndexRange(0, 2))
        self.assertEqual(layout.range_for_interval(100, 150), IndexRange(2, 3))

    def test_interval_is_clamped_to_content(self) -> None:
        layout = FixedExtentLayout(item_count=3, item_extent=10)

        self.assertEqual(layout.range_for_interval(20, 100), IndexRange(2, 3))
        self.assertEqual(layout.range_for_interval(30, 100), IndexRange(3, 3))

    def test_large_count_lookup_does_not_materialize_items(self) -> None:
        layout = FixedExtentLayout(item_count=10_000_000, item_extent=8)

        self.assertEqual(
            layout.range_for_interval(79_999_920, 80_000_000),
            IndexRange(9_999_990, 10_000_000),
        )

    def test_invalid_values_fail_loudly(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 1"):
            FixedExtentLayout(1, 0)
        with self.assertRaisesRegex(ValueError, "at least 1"):
            FixedExtentLayout(1, 0.5)
        with self.assertRaisesRegex(ValueError, "non-negative"):
            FixedExtentLayout(-1, 10)
        with self.assertRaisesRegex(ValueError, "finite"):
            FixedExtentLayout(1, math.inf)


def _plan(
    layout: FixedExtentLayout,
    viewport: ViewportMetrics,
    config: WindowConfig,
    **kwargs,
):
    """Compose select_window + plan_mask (the public planner composition)."""
    return plan_mask(layout, select_window(layout, viewport, config, **kwargs).mask)


class WindowPlannerTests(unittest.TestCase):
    def test_visible_window_and_symmetric_overscan_are_planned(self) -> None:
        plan = _plan(
            FixedExtentLayout(item_count=100, item_extent=10),
            ViewportMetrics(offset=400, extent=100),
            WindowConfig(overscan_viewports=1),
        )

        self.assertEqual(plan.mask, RenderMask.from_ranges(IndexRange(30, 60)))
        self.assertEqual(
            plan.segments,
            (
                SpacerSegment(0, 30, 300),
                ItemRangeSegment(30, 60),
                SpacerSegment(60, 100, 400),
            ),
        )
        self.assertEqual(plan.total_extent, 1000)

    def test_asymmetric_overscan_is_no_longer_a_concept(self) -> None:
        # The public API always used one symmetric overscan value; the
        # before/after split was removed in M4.
        layout = FixedExtentLayout(item_count=100, item_extent=10)
        config = WindowConfig(overscan_viewports=2)
        selection = select_window(
            layout,
            ViewportMetrics(offset=400, extent=100),
            config,
        )
        self.assertEqual(selection.mask, RenderMask.from_ranges(IndexRange(20, 70)))

    def test_required_actual_viewport_survives_blocked_coverage_handoff(self) -> None:
        selection = select_window(
            FixedExtentLayout(item_count=100, item_extent=10),
            ViewportMetrics(offset=490, extent=100),
            WindowConfig(overscan_viewports=0),
            required_viewport=ViewportMetrics(offset=500, extent=100),
        )

        self.assertEqual(selection.mask, RenderMask.from_ranges(IndexRange(49, 60)))

    def test_required_viewport_extends_the_planning_path(self) -> None:
        # The planning target lies ahead of the actual viewport; the window
        # must cover the whole path in one contiguous span.
        selection = select_window(
            FixedExtentLayout(item_count=100, item_extent=10),
            ViewportMetrics(offset=900, extent=100),
            WindowConfig(overscan_viewports=1),
            required_viewport=ViewportMetrics(offset=0, extent=100),
        )

        self.assertEqual(selection.mask, RenderMask.from_ranges(IndexRange(0, 100)))

    def test_retained_regions_create_discontiguous_mask_and_spacers(self) -> None:
        plan = _plan(
            FixedExtentLayout(item_count=100, item_extent=10),
            ViewportMetrics(offset=400, extent=100),
            WindowConfig(overscan_viewports=0),
            retained=RenderMask.from_ranges(
                IndexRange(0, 2),
                IndexRange(90, 91),
            ),
        )

        self.assertEqual(
            plan.mask.ranges,
            (IndexRange(0, 2), IndexRange(40, 50), IndexRange(90, 91)),
        )
        self.assertEqual(
            plan.segments,
            (
                ItemRangeSegment(0, 2),
                SpacerSegment(2, 40, 380),
                ItemRangeSegment(40, 50),
                SpacerSegment(50, 90, 400),
                ItemRangeSegment(90, 91),
                SpacerSegment(91, 100, 90),
            ),
        )

    def test_window_at_content_end_is_clamped(self) -> None:
        plan = _plan(
            FixedExtentLayout(item_count=100, item_extent=10),
            ViewportMetrics(offset=950, extent=100),
            WindowConfig(overscan_viewports=1),
        )

        self.assertEqual(plan.mask, RenderMask.from_ranges(IndexRange(80, 100)))

    def test_overscroll_beyond_content_uses_last_legal_viewport(self) -> None:
        plan = _plan(
            FixedExtentLayout(item_count=100, item_extent=10),
            ViewportMetrics(offset=5000, extent=100),
            WindowConfig(overscan_viewports=0),
        )

        self.assertEqual(plan.mask, RenderMask.from_ranges(IndexRange(90, 100)))

    def test_empty_layout_has_no_segments(self) -> None:
        plan = _plan(
            FixedExtentLayout(item_count=0, item_extent=10),
            ViewportMetrics(offset=0, extent=100),
            WindowConfig(overscan_viewports=1),
        )

        self.assertTrue(plan.mask.empty)
        self.assertEqual(plan.segments, ())
        self.assertEqual(plan.total_extent, 0)

    def test_no_viewport_extent_renders_only_retained_policy(self) -> None:
        plan = _plan(
            FixedExtentLayout(item_count=10, item_extent=10),
            ViewportMetrics(offset=0, extent=0),
            WindowConfig(overscan_viewports=1),
            retained=RenderMask.from_ranges(IndexRange(0, 3)),
        )

        self.assertEqual(plan.mask, RenderMask.from_ranges(IndexRange(0, 3)))

    def test_window_config_validates_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "overscan_viewports"):
            WindowConfig(overscan_viewports=-1)
        with self.assertRaisesRegex(ValueError, "max_render_ahead_viewports"):
            WindowConfig(overscan_viewports=1, max_render_ahead_viewports=float("nan"))
        with self.assertRaisesRegex(TypeError, "overscan_viewports"):
            WindowConfig(overscan_viewports=True)

    def test_viewport_metrics_has_no_velocity_field(self) -> None:
        # Velocity prediction was removed in M4; the payload velocity is no
        # longer part of the planner model.
        viewport = ViewportMetrics(offset=10, extent=100)
        self.assertFalse(hasattr(viewport, "velocity"))
        with self.assertRaisesRegex(TypeError, "unexpected keyword"):
            ViewportMetrics(offset=10, extent=100, velocity=5)


if __name__ == "__main__":
    unittest.main()
