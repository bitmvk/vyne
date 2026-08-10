"""MATERIAL-01: SliderSpec and RangeSlider controlled policy models.

Tests for:
- SliderSpec validation (finite bounds, positive step, usable width > 20)
- RangeSlider strict ordered pair
- Nearest-step initial normalisation
- Conditional discrete target construction
- Width boundary enforcement
"""

from __future__ import annotations

import math
import unittest

from vyne_material._validation import (
    SliderSpec,
    slider_targets,
)


class SliderSpecValidationTests(unittest.TestCase):
    """SliderSpec enforces finite bounds, positive step, and usable width."""

    def test_valid_spec_accepted(self):
        spec = SliderSpec(minimum=0, maximum=1, step=0.1, width=240)
        self.assertEqual(spec.minimum, 0.0)
        self.assertEqual(spec.maximum, 1.0)
        self.assertEqual(spec.step, 0.1)
        self.assertEqual(spec.width, 240.0)
        self.assertTrue(spec.is_discrete)
        self.assertEqual(spec.usable_width, 220.0)

    def test_continuous_spec_no_step(self):
        spec = SliderSpec(minimum=0, maximum=100, step=None, width=300)
        self.assertIsNone(spec.step)
        self.assertFalse(spec.is_discrete)

    def test_rejects_bool_minimum(self):
        with self.assertRaises(TypeError):
            SliderSpec(minimum=True, maximum=1, step=None, width=240)

    def test_rejects_bool_maximum(self):
        with self.assertRaises(TypeError):
            SliderSpec(minimum=0, maximum=False, step=None, width=240)

    def test_rejects_nonfinite_minimum(self):
        with self.assertRaises(ValueError):
            SliderSpec(minimum=float('nan'), maximum=1, step=None, width=240)
        with self.assertRaises(ValueError):
            SliderSpec(minimum=float('inf'), maximum=1, step=None, width=240)

    def test_rejects_nonfinite_maximum(self):
        with self.assertRaises(ValueError):
            SliderSpec(minimum=0, maximum=float('-inf'), step=None, width=240)

    def test_rejects_minimum_geq_maximum(self):
        with self.assertRaises(ValueError):
            SliderSpec(minimum=1, maximum=1, step=None, width=240)
        with self.assertRaises(ValueError):
            SliderSpec(minimum=5, maximum=3, step=None, width=240)

    def test_rejects_non_positive_step(self):
        with self.assertRaises(ValueError):
            SliderSpec(minimum=0, maximum=1, step=0, width=240)
        with self.assertRaises(ValueError):
            SliderSpec(minimum=0, maximum=1, step=-0.1, width=240)
        with self.assertRaises(ValueError):
            SliderSpec(minimum=0, maximum=1, step=float('inf'), width=240)

    def test_rejects_bool_step(self):
        with self.assertRaises(TypeError):
            SliderSpec(minimum=0, maximum=1, step=True, width=240)

    def test_rejects_non_positive_width(self):
        with self.assertRaises(ValueError):
            SliderSpec(minimum=0, maximum=1, step=None, width=0)
        with self.assertRaises(ValueError):
            SliderSpec(minimum=0, maximum=1, step=None, width=-5)

    def test_rejects_width_at_or_below_20(self):
        """Width <= 20 is rejected (10dp insets on each side need room)."""
        with self.assertRaises(ValueError):
            SliderSpec(minimum=0, maximum=1, step=None, width=20)
        with self.assertRaises(ValueError):
            SliderSpec(minimum=0, maximum=1, step=None, width=10)
        with self.assertRaises(ValueError):
            SliderSpec(minimum=0, maximum=1, step=None, width=1)

    def test_width_above_20_accepted(self):
        spec = SliderSpec(minimum=0, maximum=1, step=None, width=20.0001)
        self.assertIsNotNone(spec)
        spec2 = SliderSpec(minimum=0, maximum=1, step=0.1, width=21)
        self.assertIsNotNone(spec2)

    def test_rejects_bool_width(self):
        with self.assertRaises(TypeError):
            SliderSpec(minimum=0, maximum=1, step=None, width=True)


class SliderSpecNormalizationTests(unittest.TestCase):
    """Nearest-step initial normalisation and value_at coordinate mapping."""

    def test_normalize_off_step_to_nearest(self):
        spec = SliderSpec(minimum=0, maximum=1, step=0.1, width=240)
        self.assertAlmostEqual(spec.normalize(0.05), 0.1, places=6)
        self.assertAlmostEqual(spec.normalize(0.04), 0.0, places=6)
        self.assertAlmostEqual(spec.normalize(0.15), 0.1, places=6)

    def test_normalize_clamps_to_bounds(self):
        spec = SliderSpec(minimum=10, maximum=20, step=1, width=240)
        self.assertEqual(spec.normalize(-100), 10.0)
        self.assertEqual(spec.normalize(999), 20.0)

    def test_normalize_continuous_passthrough(self):
        spec = SliderSpec(minimum=0, maximum=1, step=None, width=240)
        self.assertAlmostEqual(spec.normalize(0.5), 0.5, places=6)
        self.assertAlmostEqual(spec.normalize(0.333333), 0.333333, places=4)

    def test_value_at_endpoints(self):
        spec = SliderSpec(minimum=0, maximum=1, step=None, width=240)
        self.assertAlmostEqual(spec.value_at(10), 0.0, places=6)
        self.assertAlmostEqual(spec.value_at(230), 1.0, places=6)

    def test_value_at_midpoint(self):
        spec = SliderSpec(minimum=0, maximum=1, step=None, width=240)
        self.assertAlmostEqual(spec.value_at(120), 0.5, places=1)

    def test_value_at_with_step(self):
        spec = SliderSpec(minimum=0, maximum=1, step=0.1, width=240)
        # x=142 => (142-10)/220 = 0.6 exactly
        self.assertAlmostEqual(spec.value_at(142), 0.6, places=6)
        # x=155 => (145)/220 ≈ 0.659 -> snaps to 0.7
        self.assertAlmostEqual(spec.value_at(155), 0.7, places=6)


class SliderTargetsTests(unittest.TestCase):
    """Conditional discrete target construction."""

    def test_continuous_returns_empty(self):
        spec = SliderSpec(minimum=0, maximum=1, step=None, width=240)
        targets = slider_targets(spec)
        self.assertEqual(targets, [])

    def test_discrete_returns_targets(self):
        spec = SliderSpec(minimum=0, maximum=1, step=0.25, width=240)
        targets = slider_targets(spec)
        self.assertEqual(len(targets), 5)  # 0, 0.25, 0.5, 0.75, 1.0
        self.assertAlmostEqual(targets[0], 0.0)
        self.assertAlmostEqual(targets[-1], 1.0)

    def test_discrete_includes_both_ends(self):
        spec = SliderSpec(minimum=0, maximum=10, step=2, width=240)
        targets = slider_targets(spec)
        self.assertAlmostEqual(targets[0], 0.0)
        self.assertAlmostEqual(targets[-1], 10.0)

    def test_many_divisions_capped(self):
        spec = SliderSpec(minimum=0, maximum=1000, step=1, width=240)
        targets = slider_targets(spec)
        # Should be capped to at most 101 sampled points
        self.assertLessEqual(len(targets), 102)
        self.assertAlmostEqual(targets[-1], 1000.0)


class RangeSliderPolicyTests(unittest.TestCase):
    """Strict ordered pair validation for RangeSlider."""

    def test_accepts_ordered_pair(self):
        spec = SliderSpec(minimum=0, maximum=1, step=0.1, width=240)
        start, end = SliderSpec.validate_range_slider_values((0.2, 0.8), spec)
        self.assertAlmostEqual(start, 0.2)
        self.assertAlmostEqual(end, 0.8)

    def test_rejects_reversed_pair(self):
        spec = SliderSpec(minimum=0, maximum=1, step=0.1, width=240)
        with self.assertRaises(ValueError):
            SliderSpec.validate_range_slider_values((0.8, 0.2), spec)

    def test_rejects_non_tuple(self):
        spec = SliderSpec(minimum=0, maximum=1, step=0.1, width=240)
        with self.assertRaises(TypeError):
            SliderSpec.validate_range_slider_values([0.2, 0.8], spec)
        with self.assertRaises(TypeError):
            SliderSpec.validate_range_slider_values(0.5, spec)

    def test_rejects_wrong_length(self):
        spec = SliderSpec(minimum=0, maximum=1, step=0.1, width=240)
        with self.assertRaises(TypeError):
            SliderSpec.validate_range_slider_values((0.2,), spec)
        with self.assertRaises(TypeError):
            SliderSpec.validate_range_slider_values((0.2, 0.5, 0.8), spec)

    def test_rejects_out_of_bounds(self):
        spec = SliderSpec(minimum=0, maximum=1, step=0.1, width=240)
        with self.assertRaises(ValueError):
            SliderSpec.validate_range_slider_values((-0.5, 0.8), spec)
        with self.assertRaises(ValueError):
            SliderSpec.validate_range_slider_values((0.2, 1.5), spec)

    def test_rejects_bool_values(self):
        spec = SliderSpec(minimum=0, maximum=1, step=0.1, width=240)
        with self.assertRaises(TypeError):
            SliderSpec.validate_range_slider_values((True, 0.8), spec)

    def test_rejects_nonfinite_values(self):
        spec = SliderSpec(minimum=0, maximum=1, step=0.1, width=240)
        with self.assertRaises(ValueError):
            SliderSpec.validate_range_slider_values((float('nan'), 0.8), spec)

    def test_normalizes_off_step_range_values(self):
        spec = SliderSpec(minimum=0, maximum=1, step=0.1, width=240)
        start, end = SliderSpec.validate_range_slider_values((0.05, 0.85), spec)
        self.assertAlmostEqual(start, 0.1, places=6)
        self.assertAlmostEqual(end, 0.9, places=6)


if __name__ == "__main__":
    unittest.main()
