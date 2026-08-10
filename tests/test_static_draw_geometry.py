"""Static draw geometry tests (DRAW-08).

Validates Path/Canvas geometry, contours, trim, dash, view-box,
intrinsic sizing, and degenerate axis behavior at the Python level.
"""

from __future__ import annotations

import unittest

from vyne.path_data import compile_path_data
from vyne.spec.schema_v2 import (
    validate_path_commands,
    validate_canvas_draw_ops,
)
from vyne.lowering import lower_element
from vyne.elements import Path, Canvas


# ---------------------------------------------------------------------------
# Path geometry — degenerate axes and multi-contour
# ---------------------------------------------------------------------------


class PathGeometryTests(unittest.TestCase):
    """Path command geometry and degenerate axis behavior."""

    def test_horizontal_line_degenerate_height(self):
        """Horizontal line: bounds have zero height but valid width."""
        commands = compile_path_data("M 0 0 L 100 0")
        self.assertEqual(len(commands), 2)  # M + L
        # The path compiler normalizes the second M pair to L
        self.assertEqual(commands[0]["cmd"], "M")
        self.assertEqual(commands[1]["cmd"], "L")
        # Horizontal line: all y-values are 0
        for cmd in commands:
            for v in cmd["values"][1::2]:  # every other value starting at index 1 = y
                self.assertEqual(v, 0.0)

    def test_vertical_line_degenerate_width(self):
        """Vertical line: bounds have zero width but valid height."""
        commands = compile_path_data("M 0 0 L 0 100")
        self.assertEqual(len(commands), 2)
        # Vertical line: all x-values are 0
        for cmd in commands:
            for v in cmd["values"][0::2]:  # every other value starting at index 0 = x
                self.assertEqual(v, 0.0)

    def test_point_degenerate(self):
        """Point: all coordinates identical."""
        commands = compile_path_data("M 5 5 L 5 5")
        self.assertEqual(len(commands), 2)
        for cmd in commands:
            for v in cmd["values"]:
                self.assertEqual(v, 5.0)

    def test_multi_contour_path(self):
        """Multiple M commands create multiple contours."""
        commands = compile_path_data("M 0 0 L 10 10 M 20 20 L 30 30 Z")
        cmds = [c["cmd"] for c in commands]
        self.assertEqual(cmds, ["M", "L", "M", "L", "Z"])

    def test_mixed_absolute_relative(self):
        """Absolute and relative commands can coexist."""
        commands = compile_path_data("M 10 20 l 30 40")
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0]["cmd"], "M")
        self.assertEqual(commands[1]["cmd"], "l")

    def test_cubic_bezier_geometry(self):
        """Cubic bezier produces correct number of parameters."""
        commands = compile_path_data("M 0 0 C 1 2 3 4 5 6")
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[1]["values"], [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])

    def test_quad_bezier_geometry(self):
        """Quadratic bezier produces correct number of parameters."""
        commands = compile_path_data("M 0 0 Q 1 2 3 4")
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[1]["values"], [1.0, 2.0, 3.0, 4.0])

    def test_close_path_back_to_start(self):
        """Z command closes back to start point (python validation only)."""
        commands = compile_path_data("M 10 20 L 30 40 Z")
        self.assertEqual(len(commands), 3)
        self.assertEqual(commands[2]["cmd"], "Z")
        self.assertEqual(commands[2]["values"], [])


# ---------------------------------------------------------------------------
# Canvas geometry — view_box, trim, dash
# ---------------------------------------------------------------------------


class CanvasGeometryTests(unittest.TestCase):
    """Canvas display-list geometry, view_box, trim, and dash validation."""

    def test_view_box_none_accepted(self):
        canon = lower_element(Canvas(
            view_box=None,
            draw=[{"kind": "rect", "x": 0, "y": 0, "width": 10, "height": 10}]
        ))
        self.assertIsNone(canon.props.get("view_box"))

    def test_rect_op_with_opacity_accepted(self):
        ops = [{"kind": "rect", "x": 0, "y": 0, "width": 10, "height": 10,
                "opacity": 0.5}]
        validate_canvas_draw_ops(ops)  # should not raise

    def test_line_op_with_dash_accepted(self):
        ops = [{"kind": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 10,
                "dash": (4, 4), "stroke_width": 2}]
        validate_canvas_draw_ops(ops)  # should not raise

    def test_path_op_with_trim_accepted(self):
        ops = [{"kind": "path",
                "commands": [{"cmd": "M", "values": (0, 0)},
                             {"cmd": "L", "values": (10, 10)}],
                "trim_start": 0.2, "trim_end": 0.8}]
        validate_canvas_draw_ops(ops)  # should not raise

    def test_trim_values_out_of_range_rejected(self):
        ops = [{"kind": "path",
                "commands": [{"cmd": "M", "values": (0, 0)},
                             {"cmd": "L", "values": (10, 10)}],
                "trim_start": 1.5}]
        with self.assertRaises(ValueError):
            validate_canvas_draw_ops(ops)

    def test_negative_trim_rejected(self):
        ops = [{"kind": "path",
                "commands": [{"cmd": "M", "values": (0, 0)},
                             {"cmd": "L", "values": (10, 10)}],
                "trim_end": -0.1}]
        with self.assertRaises(ValueError):
            validate_canvas_draw_ops(ops)

    def test_string_dash_parsed_to_tuple(self):
        """'4,8' string → (4.0, 8.0) tuple."""
        canon = lower_element(Path(d="M0,0 L10,10", stroke_dash_array="4,8"))
        self.assertEqual(canon.props["stroke_dash_array"], (4.0, 8.0))

    def test_tuple_dash_preserved(self):
        """Tuple passing through unchanged."""
        canon = lower_element(Path(d="M0,0 L10,10", stroke_dash_array=(4.0, 8.0)))
        self.assertEqual(canon.props["stroke_dash_array"], (4.0, 8.0))

    def test_full_dash_preserved_as_string(self):
        """'full' string kept as-is for PathView resolution."""
        canon = lower_element(Path(d="M0,0 L10,10", stroke_dash_array="full"))
        self.assertEqual(canon.props["stroke_dash_array"], "full")

    def test_empty_string_removes_dash(self):
        """Empty string removes the dash prop."""
        canon = lower_element(Path(d="M0,0 L10,10", stroke_dash_array=""))
        self.assertNotIn("stroke_dash_array", canon.props)

    def test_odd_length_rejected(self):
        """Odd number of dash values rejected."""
        with self.assertRaises(ValueError):
            lower_element(Path(d="M0,0 L10,10", stroke_dash_array="4"))

    def test_negative_dash_value_rejected(self):
        """Negative dash value rejected."""
        with self.assertRaises(ValueError):
            lower_element(Path(d="M0,0 L10,10", stroke_dash_array="4,-2"))

    def test_non_finite_dash_rejected(self):
        """NaN/Inf in dash rejected."""
        with self.assertRaises(ValueError):
            lower_element(Path(d="M0,0 L10,10", stroke_dash_array="1e309,4"))

    def test_zero_dash_rejected(self):
        """Zero dash value rejected (must be positive)."""
        with self.assertRaises(ValueError):
            lower_element(Path(d="M0,0 L10,10", stroke_dash_array="0,4"))

    def test_no_dash_default(self):
        """Path without dash array has empty default."""
        canon = lower_element(Path(d="M0,0 L10,10"))
        self.assertEqual(canon.props.get("stroke_dash_array", ()), ())

    def test_list_dash_converted_to_tuple(self):
        """List of numbers converted to tuple."""
        canon = lower_element(Path(d="M0,0 L10,10", stroke_dash_array=[4.0, 8.0]))
        self.assertEqual(canon.props["stroke_dash_array"], (4.0, 8.0))

    def test_four_value_dash_accepted(self):
        """Longer dash patterns (4 values) accepted."""
        canon = lower_element(Path(d="M0,0 L10,10", stroke_dash_array="4,2,8,2"))
        self.assertEqual(canon.props["stroke_dash_array"], (4.0, 2.0, 8.0, 2.0))

    def test_whitespace_in_dash_string_ignored(self):
        """Whitespace around dash values is trimmed."""
        canon = lower_element(Path(d="M0,0 L10,10", stroke_dash_array=" 4 , 8 "))
        self.assertEqual(canon.props["stroke_dash_array"], (4.0, 8.0))

    def test_non_numeric_dash_rejected(self):
        """Non-numeric dash parts reject with a clear message."""
        with self.assertRaisesRegex(ValueError, "comma-separated"):
            lower_element(Path(d="M0,0 L10,10", stroke_dash_array="fast,slow"))


if __name__ == "__main__":
    unittest.main()
