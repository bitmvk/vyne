"""Caveat tests for motion commands, elements, state, and path data.

Small-but-important contracts that guard against invalid values entering
the pipeline.
"""

from __future__ import annotations

import math
import unittest

from vyne import Text, component, state
from vyne.elements import Element, normalize_child, normalize_children
from vyne.motion import (
    Cancel,
    PresentationSlot,
    SetTarget,
    Spring,
    Tween,
    motion_command_to_dict,
)
from vyne.path_data import compile_path_data
from vyne.protocol import validate_message



class PresentationSlotTests(unittest.TestCase):
    def test_slot_key_format(self):
        slot = PresentationSlot(node_id=7, property="opacity")
        self.assertEqual(slot.to_key(), "view:7:prop:opacity")

class MotionSpecValidationTests(unittest.TestCase):
    def test_spring_rejects_non_positive_physics(self):
        with self.assertRaisesRegex(ValueError, "positive and finite"):
            Spring(stiffness=0)
        with self.assertRaisesRegex(ValueError, "positive and finite"):
            Spring(damping_ratio=-0.1)

    def test_spring_thresholds_must_be_non_negative(self):
        with self.assertRaisesRegex(ValueError, "non-negative and finite"):
            Spring(rest_value_threshold=-0.01)
        Spring(rest_value_threshold=0.0, rest_velocity_threshold=0.0)  # ok

    def test_set_target_validation(self):
        slot = PresentationSlot(node_id=1, property="opacity")
        with self.assertRaises(TypeError):
            SetTarget(slot=slot, spec=Tween(duration_ms=300), target=True)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            SetTarget(slot=slot, spec=Tween(duration_ms=300), target=math.inf)
        with self.assertRaises(ValueError):
            SetTarget(slot=slot, spec=Tween(duration_ms=300), target=0.5, from_value=math.nan)
        SetTarget(slot=slot, spec=Tween(duration_ms=300), target=1, from_value=None)  # ok


class MotionCommandToDictTests(unittest.TestCase):
    def test_set_target_tween_shape(self):
        cmd = SetTarget(
            slot=PresentationSlot(node_id=3, property="scale_x"),
            spec=Tween(duration_ms=250, easing="ease_in"),
            target=2.0,
            from_value=1.0,
            animation_id=1,
        )
        wire = motion_command_to_dict(cmd)
        self.assertEqual(wire["op"], "motion_set_target")
        self.assertEqual(wire["slot_key"], "view:3:prop:scale_x")
        self.assertEqual(wire["spec_type"], "tween")
        self.assertEqual(wire["duration_ms"], 250)
        self.assertEqual(wire["from_value"], 1.0)
        validate_message({"type": "commit", "revision": 1, "ops": [wire]})

    def test_set_target_spring_shape(self):
        cmd = SetTarget(
            slot=PresentationSlot(node_id=1, property="rotation"),
            spec=Spring(stiffness=400.0, damping_ratio=0.7),
            target=90.0,
            animation_id=2,
        )
        wire = motion_command_to_dict(cmd)
        self.assertEqual(wire["spec_type"], "spring")
        self.assertNotIn("from_value", wire)
        validate_message({"type": "commit", "revision": 1, "ops": [wire]})

    def test_cancel_shape(self):
        wire = motion_command_to_dict(Cancel(
            slot=PresentationSlot(node_id=9, property="alpha"),
            animation_id=3,
        ))
        self.assertEqual(wire, {
            "op": "motion_cancel",
            "slot_key": "view:9:prop:alpha",
            "animation_id": 3,
        })

    def test_unknown_command_type_rejected(self):
        with self.assertRaisesRegex(TypeError, "Unknown MotionCommand"):
            motion_command_to_dict(object())  # type: ignore[arg-type]


class StateGuardTests(unittest.TestCase):
    def test_state_outside_runtime_raises(self):
        with self.assertRaises(RuntimeError):
            state(0)


class ComponentDecoratorTests(unittest.TestCase):
    def test_requires_callable(self):
        with self.assertRaises(TypeError):
            component(42)  # type: ignore[arg-type]

    def test_calls_function_directly_without_runtime(self):
        @component
        def Leaf(x):
            return Text(text=f"x={x}")

        element = Leaf(5)  # no runtime context: plain function call
        self.assertEqual(element.props["text"], "x=5")


class ElementNormalizationTests(unittest.TestCase):
    def test_children_must_be_elements(self):
        with self.assertRaisesRegex(TypeError, "must contain Elements"):
            Element(kind="Box", props={}, children=("nope",))  # type: ignore[arg-type]

    def test_props_must_be_mapping(self):
        with self.assertRaisesRegex(TypeError, "mapping"):
            Element(kind="Box", props=[("a", 1)], children=())  # type: ignore[arg-type]

    def test_normalize_child_converts_scalars_to_text(self):
        for scalar, expected in (("hi", "hi"), (42, "42"), (1.5, "1.5"), (True, "True")):
            with self.subTest(value=scalar):
                element = normalize_child(scalar)
                self.assertEqual(element.kind, "Text")
                self.assertEqual(element.props["text"], expected)

    def test_normalize_children_flattens_and_drops_none(self):
        children = normalize_children((
            Text(text="a"),
            None,
            [Text(text="b"), (Text(text="c"),)],
        ))
        self.assertEqual(
            [child.props["text"] for child in children], ["a", "b", "c"],
        )


class PathDataTests(unittest.TestCase):
    def test_incomplete_coordinates_rejected(self):
        with self.assertRaisesRegex(ValueError, "incomplete coordinates"):
            compile_path_data("M 0")  # M needs 2 coordinates

    def test_unsupported_syntax_rejected(self):
        with self.assertRaisesRegex(ValueError, "syntax"):
            compile_path_data("M 0 0 @ 5 5")

    def test_unknown_command_rejected(self):
        with self.assertRaisesRegex(ValueError, "syntax"):
            compile_path_data("W 1 2")

    def test_compiled_commands_have_values_tuples(self):
        commands = compile_path_data("M 0 0 L 10 10 Z")
        self.assertEqual(
            [(c["cmd"], tuple(c["values"])) for c in commands],
            [("M", (0.0, 0.0)), ("L", (10.0, 10.0)), ("Z", ())],
        )


if __name__ == "__main__":
    unittest.main()
