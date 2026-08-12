"""MATERIAL-01: Mount-local slider gesture state.

Tests for:
- SliderGesture lifecycle (down/move/up/cancel/reset)
- One callback per tap / per distinct drag target
- RangeSliderGesture dual-thumb coordination
- Cancel and pointer replacement
- Reused Element occurrence independence

Controlled callbacks receive the proposed value directly (no signature
inspection or zero-argument adaptation).
"""

from __future__ import annotations

import unittest
from collections.abc import Callable

from vyne_material._validation import (
    RangeSliderGesture,
    SliderGesture,
    SliderSpec,
)


class SliderGestureLifecycleTests(unittest.TestCase):
    """SliderGesture owns phase, active thumb, and per-gesture last emission."""

    def setUp(self):
        self.spec = SliderSpec(minimum=0, maximum=1, step=0.1, width=240)

    def _make_callback(self, received: list[float]) -> Callable[[float], None]:
        return received.append

    def test_initial_phase_is_idle(self):
        g = SliderGesture(self.spec, None)
        self.assertEqual(g.phase, "idle")
        self.assertEqual(g.active_thumb, "")

    def test_down_activates_and_emits(self):
        received: list[float] = []
        g = SliderGesture(self.spec, self._make_callback(received))
        g.down("single", 142)  # x=142 -> value 0.6
        self.assertEqual(g.phase, "active")
        self.assertEqual(g.active_thumb, "single")
        self.assertEqual(len(received), 1)
        self.assertAlmostEqual(received[0], 0.6)

    def test_move_deduplicates_same_value(self):
        received: list[float] = []
        g = SliderGesture(self.spec, self._make_callback(received))
        g.down("single", 142)
        self.assertEqual(len(received), 1)
        g.move(142)
        self.assertEqual(len(received), 1)  # same value -> deduplicated
        g.move(143)
        self.assertEqual(len(received), 1)  # 143 also normalizes to 0.6
        g.move(164)
        self.assertEqual(len(received), 2)  # 0.7 is new

    def test_move_only_when_active(self):
        received: list[float] = []
        g = SliderGesture(self.spec, self._make_callback(received))
        g.move(164)  # not active -> no emission
        self.assertEqual(len(received), 0)

    def test_up_resets_phase(self):
        g = SliderGesture(self.spec, None)
        g.down("single", 120)
        self.assertEqual(g.phase, "active")
        g.up()
        self.assertEqual(g.phase, "idle")
        self.assertEqual(g.active_thumb, "")

    def test_cancel_resets_like_up(self):
        g = SliderGesture(self.spec, None)
        g.down("single", 120)
        g.cancel()
        self.assertEqual(g.phase, "idle")

    def test_separate_taps_emit_each_time(self):
        """Each down/up cycle emits one callback per tap."""
        received: list[float] = []
        g = SliderGesture(self.spec, self._make_callback(received))

        g.down("single", 142)
        self.assertEqual(len(received), 1)
        g.up()

        g.down("single", 142)
        self.assertEqual(len(received), 2)
        g.up()

        g.down("single", 142)
        self.assertEqual(len(received), 3)

    def test_tap_always_emits(self):
        received: list[float] = []
        g = SliderGesture(self.spec, self._make_callback(received))
        g.tap(142)
        self.assertEqual(len(received), 1)
        g.tap(142)
        self.assertEqual(len(received), 2)
        g.tap(164)
        self.assertEqual(len(received), 3)

    def test_null_callback_does_not_raise(self):
        g = SliderGesture(self.spec, None)
        # Gesture routing must tolerate a missing callback without raising.
        g.down("single", 142)
        g.move(164)
        g.up()


class RangeSliderGestureTests(unittest.TestCase):
    """Dual-thumb gesture emits complete (start, end) tuples."""

    def setUp(self):
        self.spec = SliderSpec(minimum=0, maximum=1, step=0.1, width=240)

    def _make_callback(
        self, received: list[tuple[float, float]]
    ) -> Callable[[tuple[float, float]], None]:
        return received.append

    def test_down_start_emits_pair(self):
        received: list[tuple[float, float]] = []
        g = RangeSliderGesture(self.spec, self._make_callback(received), 0.2, 0.8)
        g.down_start(32)  # value_at(32) = 0.1
        self.assertEqual(len(received), 1)
        self.assertAlmostEqual(received[0][0], 0.1)
        self.assertAlmostEqual(received[0][1], 0.8)

    def test_down_end_emits_pair(self):
        received: list[tuple[float, float]] = []
        g = RangeSliderGesture(self.spec, self._make_callback(received), 0.2, 0.8)
        # end target at global x = 120 (midpoint) + 88 = 208 -> value 0.9
        g.down_end(208)
        self.assertEqual(len(received), 1)
        self.assertAlmostEqual(received[0][0], 0.2)
        self.assertAlmostEqual(received[0][1], 0.9)

    def test_start_cannot_cross_end(self):
        received: list[tuple[float, float]] = []
        g = RangeSliderGesture(self.spec, self._make_callback(received), 0.2, 0.8)
        g.down_start(230)  # value_at(230) = 1.0, but capped by end=0.8
        self.assertAlmostEqual(g.start, 0.8)
        self.assertAlmostEqual(received[0][0], 0.8)

    def test_end_cannot_cross_start(self):
        received: list[tuple[float, float]] = []
        g = RangeSliderGesture(self.spec, self._make_callback(received), 0.2, 0.8)
        g.down_end(10)  # value_at(10) = 0.0, but capped by start=0.2
        self.assertAlmostEqual(g.end, 0.2)
        self.assertAlmostEqual(received[0][1], 0.2)

    def test_move_end_only_when_active(self):
        received: list[tuple[float, float]] = []
        g = RangeSliderGesture(self.spec, self._make_callback(received), 0.2, 0.8)
        g.move_end(208)  # not active -> no emission
        self.assertEqual(len(received), 0)

    def test_up_and_cancel_do_not_raise_with_null_callback(self):
        g = RangeSliderGesture(self.spec, None, 0.2, 0.8)
        g.down_start(32)
        g.up_start()
        # Idempotent: repeated up/cancel is safe
        g.up_start()
        g.cancel_start()

    def test_both_thumbs_independent(self):
        received: list[tuple[float, float]] = []
        g = RangeSliderGesture(self.spec, self._make_callback(received), 0.2, 0.8)

        g.down_start(32)   # start = 0.1, emit (0.1, 0.8)
        g.down_end(208)    # end = 0.9, emit (0.1, 0.9)
        self.assertEqual(len(received), 2)
        self.assertAlmostEqual(received[1][0], 0.1)
        self.assertAlmostEqual(received[1][1], 0.9)

    def test_null_callback_does_not_raise(self):
        g = RangeSliderGesture(self.spec, None, 0.2, 0.8)
        g.down_start(32)
        g.move_start(100)
        g.down_end(200)


class SliderGestureRegressionTests(unittest.TestCase):
    """Preserve known-correct behaviors flagged in the audit."""

    def test_endpoint_values_preserved(self):
        """Left endpoint maps to minimum, right to maximum."""
        spec = SliderSpec(minimum=0, maximum=1, step=None, width=240)
        self.assertAlmostEqual(spec.value_at(10), 0.0)
        self.assertAlmostEqual(spec.value_at(230), 1.0)

    def test_no_x_shadowing(self):
        """value_at uses the coordinate correctly."""
        spec = SliderSpec(minimum=0, maximum=1, step=None, width=240)
        self.assertAlmostEqual(spec.value_at(120), 0.5, places=1)


if __name__ == "__main__":
    unittest.main()
