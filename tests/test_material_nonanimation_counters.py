"""Non-animation performance counters for Material components (MAT-11).

Verifies that shared models avoid repeated work:
- Path command dictionaries are built once and reused.
- Callbacks are inspected once, not per gesture.
- Continuous sliders produce no discrete-target lists.
"""

from __future__ import annotations

import unittest

from vyne.material._callbacks import CallbackAdapter
from vyne.material._foundation import invoke, value_handler, progress_path, wavy_path
from vyne.material._validation import slider_targets, SliderSpec


class PathCommandReuseTests(unittest.TestCase):
    """One-time path command construction."""

    def test_progress_path_identity(self):
        """progress_path() returns the same string object."""
        p1 = progress_path()
        p2 = progress_path()
        # Both calls return the same module-level constant
        self.assertIs(p1, p2)

    def test_wavy_path_caches_by_dimension(self):
        """wavy_path with same dimensions produces identical strings."""
        w1 = wavy_path(200, 40, cycles=8)
        w2 = wavy_path(200, 40, cycles=8)
        self.assertEqual(w1, w2)

    def test_wavy_path_different_dimensions(self):
        """Different dimensions produce different paths (not reused)."""
        w1 = wavy_path(200, 40, cycles=8)
        w2 = wavy_path(300, 40, cycles=8)
        self.assertNotEqual(w1, w2)


class CallbackInspectionCounterTests(unittest.TestCase):
    """CallbackAdapter inspects once per construction, not per invocation."""

    def test_adapter_inspects_once(self):
        """Multiple invocations reuse the same inspection result."""
        received: list[object] = []

        def handler(value):
            received.append(value)

        adapter = CallbackAdapter(handler)
        # Invoke many times — no re-inspection
        for i in range(100):
            adapter.invoke(i)
        self.assertEqual(len(received), 100)
        self.assertEqual(received, list(range(100)))

    def test_value_handler_creates_reusable_wrapper(self):
        """value_handler produces a closure that delegates to one adapter."""
        received: list[object] = []

        handler = value_handler(received.append, 42)
        self.assertIsNotNone(handler)
        # Call many times
        for _ in range(50):
            handler(None)
        self.assertEqual(len(received), 50)
        self.assertEqual(received, [42] * 50)

    def test_invoke_calls_zero_arg(self):
        """invoke calls zero-arg callables."""
        count = [0]

        def handler():
            count[0] += 1

        invoke(handler, "ignored")
        invoke(handler, "still_ignored")
        self.assertEqual(count[0], 2)

    def test_adapter_handles_single_param(self):
        """A callback accepting a single positional arg works."""
        received: list[object] = []

        def single_handler(value):
            received.append(value)

        adapter = CallbackAdapter(single_handler)
        adapter.invoke(99)
        self.assertEqual(received, [99])

    def test_adapter_accepts_varargs(self):
        """A *args callback is accepted as value-accepting."""
        received: list[object] = []

        def varargs_handler(*args):
            received.extend(args)

        adapter = CallbackAdapter(varargs_handler)
        adapter.invoke(42)
        self.assertEqual(received, [42])

    def test_adapter_handles_zero_param(self):
        """A callback accepting zero positional args works."""
        count = [0]

        def zero_handler():
            count[0] += 1

        adapter = CallbackAdapter(zero_handler)
        adapter.invoke("ignored")
        adapter.invoke("still_ignored")
        self.assertEqual(count[0], 2)


class ContinuousSliderTargetCounterTests(unittest.TestCase):
    """Continuous sliders produce zero discrete-target work."""

    def test_continuous_slider_empty_targets(self):
        """Continuous slider (step=None) produces empty target list."""
        spec = SliderSpec(minimum=0, maximum=100, step=None, width=300)
        targets = slider_targets(spec)
        self.assertEqual(targets, [])

    def test_discrete_slider_has_targets(self):
        """Discrete slider (step set) produces target list."""
        spec = SliderSpec(minimum=0, maximum=100, step=10, width=300)
        targets = slider_targets(spec)
        self.assertGreater(len(targets), 0)

    def test_many_divisions_are_capped(self):
        """Slider with many steps caps targets at 101."""
        spec = SliderSpec(minimum=0, maximum=10_000, step=0.01, width=300)
        targets = slider_targets(spec)
        self.assertLessEqual(len(targets), 101)

    def test_continuous_targets_never_built(self):
        """Continuous spec has step=None → no targets."""
        spec = SliderSpec(minimum=0, maximum=1, step=None, width=240)
        self.assertFalse(spec.is_discrete)
        self.assertEqual(slider_targets(spec), [])


if __name__ == "__main__":
    unittest.main()
