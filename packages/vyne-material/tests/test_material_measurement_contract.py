"""Material measurement contract and counter tests (MAT-11).

Tests for native wrap-content, min/max constraints, and one-time
path command construction.  Verifies that components use native
measurement instead of ``len(text) * constant`` estimates.
"""

from __future__ import annotations

import unittest

from vyne_material import (
    Badge,
    Menu,
    MenuItem,
    TextField,
    Tooltip,
    CircularProgressIndicator,
    LinearProgressIndicator,
)
from vyne_material._geometry import progress_path, wavy_path


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

    def test_text_field_uses_native_constraints(self):
        """TextField constrains children natively, not by label length."""
        tf = TextField(value="", label="Email address")
        container = next(c for c in tf.children if c.kind == "Box")
        self.assertEqual(container.props.get("min_height"), 56)
        self.assertEqual(container.props.get("width"), "match_parent")

    def test_tooltip_uses_native_constraints(self):
        """Tooltip uses min_width + width bounds, not len(text)*constant."""
        from vyne.elements import Box as Bx
        tip = Tooltip(Bx(), "Hello World", visible=True)
        inner = next(c for c in tip.children if c.kind == "Box")
        self.assertEqual(inner.props.get("min_width"), 40)
        self.assertGreater(inner.props.get("width"), 0)

class OneTimePathCommandTests(unittest.TestCase):
    """MAT-11: Path command dictionaries are built once and reused."""

    def test_progress_path_is_constant(self):
        """progress_path() returns the exact same object every call."""
        p1 = progress_path()
        p2 = progress_path()
        self.assertIs(p1, p2)
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

    def test_wavy_path_different_dimensions_differ(self):
        """Different dimensions produce distinct paths."""
        self.assertNotEqual(wavy_path(200, 40), wavy_path(100, 20))

    def test_wavy_path_structure(self):
        """Wavy path is a well-formed SVG path."""
        path = wavy_path(100, 20, cycles=4)
        self.assertIsInstance(path, str)
        self.assertTrue(path.startswith("M"))
        self.assertTrue("L" in path)

    def test_circular_progress_reuses_path(self):
        """CircularProgressIndicator emits two path ops sharing commands."""
        indicator = CircularProgressIndicator(0.5)
        draw = indicator.props.get("draw", [])
        paths = [d for d in draw if d.get("kind") == "path"]
        # Background track + foreground trim, both built from the shared path.
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0]["commands"], paths[1]["commands"])

    def test_linear_progress_wavy_reuses_path(self):
        """LinearWavyProgressIndicator emits two path ops with real commands."""
        indicator = LinearProgressIndicator(0.5, wavy=True, width=200)
        draw = indicator.props.get("draw", [])
        paths = [d for d in draw if d.get("kind") == "path"]
        self.assertEqual(len(paths), 2)
        for path in paths:
            commands = path["commands"]
            self.assertTrue(commands, "path op must carry commands")
            self.assertEqual(commands[0]["cmd"], "M")


if __name__ == "__main__":
    unittest.main()
