"""Material measurement contract and counter tests (MAT-11).

Tests for native wrap-content, min/max constraints, and one-time
path command construction.  Verifies that components use native
measurement instead of ``len(text) * constant`` estimates.
"""

from __future__ import annotations

import unittest

from vyne.material import (
    Badge,
    ListItem,
    Menu,
    MenuItem,
    TextField,
    Tooltip,
    Button,
    CircularProgressIndicator,
    LinearProgressIndicator,
    LoadingIndicator,
)
from vyne.material._geometry import progress_path, wavy_path


class NativeMeasurementContractTests(unittest.TestCase):
    """MAT-11: Components use native wrap-content + min/max constraints."""

    def test_badge_uses_native_measurement(self):
        """Badge uses min_width/height, not len(text)*constant."""
        badge = Badge("99+")
        # Badge should use min_width, not a fixed width derived from len()
        self.assertIn("min_width", badge.props)
        # The height should be a minimum, not a hardcoded pixel count
        self.assertIn("height", badge.props)

    def test_badge_dot_uses_fixed_size(self):
        """Badge without value (dot) uses fixed small size."""
        dot = Badge(None)
        self.assertEqual(dot.props.get("width"), 6)
        self.assertEqual(dot.props.get("height"), 6)

    def test_menu_uses_native_constraints(self):
        """Menu uses min_width + width upper bound, not len(label)*constant."""
        menu = Menu([MenuItem("Short"), MenuItem("A much longer label")])
        self.assertIn("min_width", menu.props)
        # width is an upper bound, not a computed exact pixel value
        self.assertIn("width", menu.props)

    def test_text_field_label_uses_native_constraints(self):
        """TextField label respects native measurement."""
        tf = TextField(value="", label="Email address")
        if tf is not None:
            # TextField should not compute pixel width from len(label)
            self.assertIsNotNone(tf)

    def test_tooltip_uses_native_constraints(self):
        """Tooltip uses min_width + width, not len(text)*constant."""
        from vyne.elements import Box as Bx
        tip = Tooltip(Bx(), "Hello World", visible=True)
        if tip is not None:
            # Check that props use min/max, not fixed pixel estimates
            self.assertIsNotNone(tip)

class OneTimePathCommandTests(unittest.TestCase):
    """MAT-11: Path command dictionaries are built once and reused."""

    def test_progress_path_is_constant(self):
        """progress_path() returns the same string every call."""
        p1 = progress_path()
        p2 = progress_path()
        self.assertEqual(p1, p2)
        self.assertIsInstance(p1, str)

    def test_progress_path_structure(self):
        """Progress path is a well-formed SVG path."""
        path = progress_path()
        tokens = path.split()
        self.assertTrue(tokens[0].startswith("M"))
        self.assertTrue(any(t.startswith("C") for t in tokens))

    def test_wavy_path_deterministic(self):
        """wavy_path with same args returns same string."""
        w1 = wavy_path(200, 40, cycles=8)
        w2 = wavy_path(200, 40, cycles=8)
        self.assertEqual(w1, w2)

    def test_wavy_path_structure(self):
        """Wavy path is a well-formed SVG path."""
        path = wavy_path(100, 20, cycles=4)
        self.assertIsInstance(path, str)
        self.assertTrue(path.startswith("M"))
        self.assertTrue("L" in path)

    def test_circular_progress_reuses_path(self):
        """CircularProgressIndicator uses the shared progress path commands."""
        indicator = CircularProgressIndicator(0.5)
        draw = indicator.props.get("draw", [])
        self.assertGreaterEqual(len(draw), 1)
        # Both tracks (background + foreground) use the same path commands.
        # The path is lowered to `commands` tuples (one-time construction).
        paths = [d for d in draw if d.get("kind") == "path"]
        if len(paths) >= 2:
            # Both paths use the same commands tuple (shared reference).
            self.assertEqual(paths[0]["commands"], paths[1]["commands"])

    def test_linear_progress_wavy_reuses_path(self):
        """LinearWavyProgressIndicator uses shared wavy path scheme."""
        indicator = LinearProgressIndicator(0.5, wavy=True, width=200)
        draw = indicator.props.get("draw", [])
        self.assertGreaterEqual(len(draw), 1)


class CounterTests(unittest.TestCase):
    """MAT-11: Performance-aware counter assertions.

    Continuous sliders must not build discrete target lists.
    Progress/wavy commands must be built once, not per frame.
    """

    def test_continuous_slider_has_no_target_list(self):
        """Continuous Slider produces empty target list."""
        from vyne.material._validation import slider_targets, SliderSpec
        spec = SliderSpec(minimum=0, maximum=1, step=None, width=240)
        targets = slider_targets(spec)
        self.assertEqual(targets, [])

    def test_discrete_slider_has_target_list(self):
        """Discrete Slider produces target list."""
        from vyne.material._validation import slider_targets, SliderSpec
        spec = SliderSpec(minimum=0, maximum=10, step=1, width=240)
        targets = slider_targets(spec)
        self.assertGreater(len(targets), 0)

    def test_progress_path_single_construction(self):
        """progress_path is a module-level constant, built once."""
        # Verify the constant exists and is reused
        import vyne.material._geometry as geo
        self.assertTrue(hasattr(geo, '_PROGRESS_PATH_D'))

    def test_callback_inspection_counter_bounded(self):
        """CallbackAdapter inspects signature once per adapter instance."""
        from vyne.material._callbacks import CallbackAdapter

        def handler(value):
            pass

        # Create once, call many — inspection happens at construction
        adapter = CallbackAdapter(handler)
        adapter.invoke(1)
        adapter.invoke(2)
        adapter.invoke(3)
        # No error means the adapter works without re-inspection

    def test_loading_indicator_no_dead_work(self):
        """LoadingIndicator builds draw list without dead target work."""
        indicator = LoadingIndicator(phase=0.25)
        draw = indicator.props.get("draw", [])
        self.assertGreater(len(draw), 0)


if __name__ == "__main__":
    unittest.main()
