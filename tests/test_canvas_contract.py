"""Canvas and Path contract tests (SCHEMA-01).

Validates Canvas display-list operation schemas, Path command schemas,
and boundary behavior for view_box, dash array, opacity, and geometry.
"""

from __future__ import annotations

import unittest

from vyne.spec.schema_v2 import (
    CANVAS_OP_SPECS,
    validate_canvas_draw_ops,
    validate_path_commands,
)
from vyne.lowering import lower_element
from vyne.elements import Canvas, Path


# ---------------------------------------------------------------------------
# Canvas operation schema completeness
# ---------------------------------------------------------------------------

class CanvasOpSchemaTests(unittest.TestCase):
    """Every Canvas op has required fields and field specs."""

    def test_all_expected_ops_exist(self):
        expected = {"rect", "round_rect", "circle", "line", "path"}
        self.assertEqual(set(CANVAS_OP_SPECS.keys()), expected)

    def test_each_op_has_required(self):
        for name, spec in CANVAS_OP_SPECS.items():
            self.assertIsNotNone(spec.required, f"{name} missing required")
            self.assertIsNotNone(spec.fields, f"{name} missing fields")

    def test_required_fields_present_in_op(self):
        for name, spec in CANVAS_OP_SPECS.items():
            for field in spec.required:
                self.assertIn(field, spec.fields, f"{name} required field {field} not in fields")

    def test_shared_paint_fields_on_all_ops(self):
        shared = {"fill", "stroke", "stroke_width", "stroke_cap",
                  "stroke_join", "dash", "dash_offset", "opacity"}
        for name, spec in CANVAS_OP_SPECS.items():
            for field in shared:
                self.assertIn(field, spec.fields, f"{name} missing shared paint field {field}")


# ---------------------------------------------------------------------------
# Canvas draw validation
# ---------------------------------------------------------------------------

class CanvasDrawValidationTests(unittest.TestCase):
    """Validate Canvas draw ops against the schema."""

    def test_valid_rect_accepted(self):
        ops = [{"kind": "rect", "x": 1, "y": 2, "width": 10, "height": 20}]
        validate_canvas_draw_ops(ops)

    def test_valid_round_rect_accepted(self):
        ops = [{"kind": "round_rect", "x": 1, "y": 2, "width": 10, "height": 20, "radius": 5}]
        validate_canvas_draw_ops(ops)

    def test_valid_circle_accepted(self):
        ops = [{"kind": "circle", "cx": 5, "cy": 5, "r": 10}]
        validate_canvas_draw_ops(ops)

    def test_valid_line_accepted(self):
        ops = [{"kind": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 10}]
        validate_canvas_draw_ops(ops)

    def test_valid_path_op_accepted(self):
        ops = [{"kind": "path"}]
        validate_canvas_draw_ops(ops)

    def test_missing_required_field_rejected(self):
        ops = [{"kind": "rect", "x": 1}]  # missing y, width, height
        with self.assertRaises(ValueError):
            validate_canvas_draw_ops(ops)

    def test_unknown_kind_rejected(self):
        ops = [{"kind": "triangle"}]
        with self.assertRaises(ValueError):
            validate_canvas_draw_ops(ops)

    def test_non_dict_rejected(self):
        with self.assertRaises(TypeError):
            validate_canvas_draw_ops([42])

    def test_non_list_rejected(self):
        with self.assertRaises(TypeError):
            validate_canvas_draw_ops("not a list")

    def test_tuple_draw_accepted_by_canonical_validation(self):
        """Canonical draw storage is a frozen tuple; validation accepts it."""
        ops = ({"kind": "rect", "x": 0, "y": 0, "width": 1, "height": 1},)
        validate_canvas_draw_ops(ops)  # must not raise

    def test_draw_schema_accepts_list_and_tuple(self):
        from vyne.spec.schema_v2 import ALL_PROPS
        self.assertEqual(ALL_PROPS["draw"].value.exact_types, (list, tuple))

    def test_canvas_constructor_rejects_tuple_draw(self):
        """The public Canvas() constructor compiles a list, not a tuple."""
        with self.assertRaises(TypeError):
            Canvas(draw=(
                {"kind": "rect", "x": 0, "y": 0, "width": 1, "height": 1},
            ))

    def test_negative_width_rejected(self):
        ops = [{"kind": "rect", "x": 0, "y": 0, "width": -10, "height": 10}]
        with self.assertRaises(ValueError):
            validate_canvas_draw_ops(ops)

    def test_zero_radius_on_circle_rejected(self):
        ops = [{"kind": "circle", "cx": 0, "cy": 0, "r": 0}]
        with self.assertRaises(ValueError):
            validate_canvas_draw_ops(ops)

    def test_shared_paint_fields_validated(self):
        # Bad stroke color
        ops = [{"kind": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 1, "stroke": "red"}]
        with self.assertRaises(ValueError):
            validate_canvas_draw_ops(ops)

    def test_opacity_out_of_range_rejected(self):
        ops = [{"kind": "rect", "x": 0, "y": 0, "width": 10, "height": 10, "opacity": 1.5}]
        with self.assertRaises(ValueError):
            validate_canvas_draw_ops(ops)

    def test_dash_array_odd_length_rejected(self):
        ops = [{"kind": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 1, "dash": (4,)}]
        with self.assertRaises(ValueError):
            validate_canvas_draw_ops(ops)

    def test_unknown_field_rejected(self):
        ops = [{"kind": "rect", "x": 0, "y": 0, "width": 10, "height": 10,
                "foo": "bar"}]
        with self.assertRaises(ValueError):
            validate_canvas_draw_ops(ops)


# ---------------------------------------------------------------------------
# Path command validation
# ---------------------------------------------------------------------------

class PathCommandValidationTests(unittest.TestCase):
    """Validate Path commands against the path command schema."""

    def test_valid_move_to(self):
        cmds = [{"cmd": "M", "values": (10.0, 20.0)}]
        validate_path_commands(cmds)

    def test_valid_line_to(self):
        cmds = [{"cmd": "L", "values": (30.0, 40.0)}]
        validate_path_commands(cmds)

    def test_valid_close(self):
        cmds = [{"cmd": "Z", "values": ()}]
        validate_path_commands(cmds)

    def test_valid_cubic_curve(self):
        cmds = [{"cmd": "C", "values": (10, 20, 30, 40, 50, 60)}]
        validate_path_commands(cmds)

    def test_valid_quad_curve(self):
        cmds = [{"cmd": "Q", "values": (10, 20, 30, 40)}]
        validate_path_commands(cmds)

    def test_relative_commands_accepted(self):
        cmds = [{"cmd": "m", "values": (5.0, 5.0)}]
        validate_path_commands(cmds)

    def test_wrong_arity_rejected(self):
        cmds = [{"cmd": "M", "values": (10,)}]  # needs 2 values
        with self.assertRaises(ValueError):
            validate_path_commands(cmds)

    def test_unknown_cmd_rejected(self):
        cmds = [{"cmd": "X", "values": (1, 2)}]
        with self.assertRaises(ValueError):
            validate_path_commands(cmds)

    def test_non_finite_values_rejected(self):
        cmds = [{"cmd": "L", "values": (float("inf"), 0)}]
        with self.assertRaises(ValueError):
            validate_path_commands(cmds)

    def test_non_tuple_values_rejected(self):
        cmds = [{"cmd": "L", "values": 42}]
        with self.assertRaises(TypeError):
            validate_path_commands(cmds)

    def test_missing_cmd_field_rejected(self):
        cmds = [{"values": (1, 2)}]
        with self.assertRaises(ValueError):
            validate_path_commands(cmds)

    def test_unknown_field_rejected(self):
        cmds = [{"cmd": "M", "values": (1, 2), "extra": True}]
        with self.assertRaises(ValueError):
            validate_path_commands(cmds)

    def test_non_list_rejected(self):
        with self.assertRaises(TypeError):
            validate_path_commands("not a list")

    def test_non_dict_cmd_rejected(self):
        with self.assertRaises(TypeError):
            validate_path_commands([42])


# ---------------------------------------------------------------------------
# Canvas/Path lowering integration
# ---------------------------------------------------------------------------

class CanvasPathLoweringTests(unittest.TestCase):
    """Integration: Canvas/Path validation during lowering."""

    def test_valid_canvas_lowers(self):
        canon = lower_element(Canvas(draw=[
            {"kind": "rect", "x": 0, "y": 0, "width": 10, "height": 10}
        ]))
        self.assertEqual(canon.kind, "Canvas")

    def test_valid_path_lowers(self):
        canon = lower_element(Path(d="M0,0 L10,10"))
        self.assertEqual(canon.kind, "Path")
        self.assertIn("commands", canon.props)

    def test_invalid_canvas_op_rejects_at_lowering(self):
        with self.assertRaises(ValueError):
            lower_element(Canvas(draw=[{"kind": "triangle"}]))

    def test_missing_required_canvas_field_rejects(self):
        with self.assertRaises(ValueError):
            lower_element(Canvas(draw=[{"kind": "rect", "x": 1}]))

    def test_view_box_four_numbers(self):
        canon = lower_element(Canvas(
            view_box=[0, 0, 100, 100],
            draw=[{"kind": "rect", "x": 0, "y": 0, "width": 10, "height": 10}]
        ))
        self.assertEqual(canon.props["view_box"], (0, 0, 100, 100))

    def test_view_box_wrong_length_rejects(self):
        with self.assertRaises(ValueError):
            lower_element(Canvas(view_box=[0, 0, 100], draw=[]))

    def test_view_box_non_finite_rejects(self):
        # NaN is rejected at Element construction (JSON serialization guard),
        # before lowering even runs.
        with self.assertRaises((ValueError, TypeError)):
            Canvas(view_box=[0, 0, float("nan"), 100])

    def test_empty_canvas_draw_accepted(self):
        canon = lower_element(Canvas(draw=[]))
        self.assertEqual(canon.kind, "Canvas")


if __name__ == "__main__":
    unittest.main()
