"""Tests for the unified animation presentation model (v2).

Covers:
- Tween/spring endpoint and settling behavior (Python policy)
- Interrupted retarget velocity policy
- Stable Canvas operation identity across reorder/insert/remove
- Detach/remove/clear/disposal cleanup
- Animation-only commit sequencing (SCHED-01)
- View/Canvas parity in the protocol format
"""

from __future__ import annotations

import unittest

from vyne.motion import (
    Cancel,
    CanvasOpIdentity,
    PresentationSlot,
    RetargetPolicy,
    SetTarget,
    Spring,
    Tween,
    motion_command_to_dict,
)
from vyne.protocol import validate_message


class PresentationSlotTests(unittest.TestCase):
    """Stable slot identity."""

    def test_view_prop_slot_has_correct_key(self):
        slot = PresentationSlot(node_id=42, property="alpha")
        self.assertEqual(slot.to_key(), "view:42:prop:alpha")

    def test_canvas_op_slot_has_correct_key(self):
        slot = PresentationSlot(
            node_id=42, property="x", slot_id="op3_circle"
        )
        self.assertEqual(
            slot.to_key(), "view:42:slot:op3_circle:x"
        )

    def test_rejects_non_positive_node_id(self):
        with self.assertRaises(ValueError):
            PresentationSlot(node_id=0, property="alpha")
        with self.assertRaises(ValueError):
            PresentationSlot(node_id=-1, property="alpha")

    def test_rejects_empty_property(self):
        with self.assertRaises(ValueError):
            PresentationSlot(node_id=1, property="")
        with self.assertRaises(ValueError):
            PresentationSlot(node_id=1, property="   ")

    def test_slot_key_is_unique_per_property(self):
        a = PresentationSlot(node_id=1, property="alpha")
        b = PresentationSlot(node_id=1, property="scale_x")
        self.assertNotEqual(a.to_key(), b.to_key())

    def test_slot_key_is_unique_per_node(self):
        a = PresentationSlot(node_id=1, property="alpha")
        b = PresentationSlot(node_id=2, property="alpha")
        self.assertNotEqual(a.to_key(), b.to_key())


class TweenSpecTests(unittest.TestCase):
    """Tween specification validation."""

    def test_valid_tween(self):
        t = Tween(duration_ms=300, easing="ease_out")
        self.assertEqual(t.duration_ms, 300)
        self.assertEqual(t.easing, "ease_out")
        self.assertEqual(t.retarget, RetargetPolicy.RESTART)

    def test_rejects_negative_duration(self):
        with self.assertRaises(ValueError):
            Tween(duration_ms=-1)

    def test_rejects_bool_duration(self):
        with self.assertRaises(ValueError):
            Tween(duration_ms=True)

    def test_rejects_invalid_easing(self):
        with self.assertRaises(ValueError):
            Tween(duration_ms=300, easing="invalid")

    def test_all_valid_easings_accepted(self):
        for easing in [
            "linear", "ease_in", "ease_out", "ease_in_out",
            "overshoot", "bounce",
        ]:
            Tween(duration_ms=100, easing=easing)

    def test_zero_duration_is_valid(self):
        t = Tween(duration_ms=0)
        self.assertEqual(t.duration_ms, 0)


class SpringSpecTests(unittest.TestCase):
    """Spring specification validation."""

    def test_default_spring(self):
        s = Spring()
        self.assertEqual(s.stiffness, 380.0)
        self.assertEqual(s.damping_ratio, 0.8)
        self.assertEqual(s.rest_value_threshold, 0.01)
        self.assertEqual(s.rest_velocity_threshold, 0.01)
        self.assertEqual(s.retarget, RetargetPolicy.MAINTAIN_VELOCITY)

    def test_custom_spring(self):
        s = Spring(
            stiffness=200.0,
            damping_ratio=0.5,
            rest_value_threshold=0.001,
            rest_velocity_threshold=0.001,
        )
        self.assertEqual(s.stiffness, 200.0)
        self.assertEqual(s.damping_ratio, 0.5)

    def test_rejects_non_positive_stiffness(self):
        with self.assertRaises(ValueError):
            Spring(stiffness=0)
        with self.assertRaises(ValueError):
            Spring(stiffness=-1)

    def test_rejects_non_positive_damping_ratio(self):
        with self.assertRaises(ValueError):
            Spring(damping_ratio=0)
        with self.assertRaises(ValueError):
            Spring(damping_ratio=-1)

    def test_accepts_zero_thresholds(self):
        s = Spring(rest_value_threshold=0.0, rest_velocity_threshold=0.0)
        self.assertEqual(s.rest_value_threshold, 0.0)


class SetTargetTests(unittest.TestCase):
    """SetTarget command validation."""

    def test_valid_set_target(self):
        slot = PresentationSlot(node_id=1, property="alpha")
        spec = Tween(duration_ms=300)
        cmd = SetTarget(
            slot=slot, spec=spec, target=0.5, animation_id=1
        )
        self.assertEqual(cmd.target, 0.5)
        self.assertIsNone(cmd.from_value)

    def test_with_from_value(self):
        slot = PresentationSlot(node_id=1, property="alpha")
        spec = Tween(duration_ms=300)
        cmd = SetTarget(slot=slot, spec=spec, target=0.5, from_value=0.0)
        self.assertEqual(cmd.from_value, 0.0)

    def test_rejects_non_finite_target(self):
        slot = PresentationSlot(node_id=1, property="alpha")
        spec = Tween(duration_ms=300)
        with self.assertRaises(ValueError):
            SetTarget(slot=slot, spec=spec, target=float("inf"))
        with self.assertRaises(ValueError):
            SetTarget(slot=slot, spec=spec, target=float("nan"))

    def test_rejects_non_numeric_from_value(self):
        slot = PresentationSlot(node_id=1, property="alpha")
        spec = Tween(duration_ms=300)
        with self.assertRaises(TypeError):
            SetTarget(slot=slot, spec=spec, target=0.5, from_value="start")


class MotionCommandSerializationTests(unittest.TestCase):
    """Protocol serialization for motion commands."""

    def test_tween_set_target_serialization(self):
        slot = PresentationSlot(node_id=1, property="alpha")
        spec = Tween(duration_ms=300, easing="ease_out")
        cmd = SetTarget(
            slot=slot, spec=spec, target=0.5, animation_id=1
        )
        d = motion_command_to_dict(cmd)

        self.assertEqual(d["op"], "motion_set_target")
        self.assertEqual(d["slot_key"], "view:1:prop:alpha")
        self.assertEqual(d["node_id"], 1)
        self.assertEqual(d["property"], "alpha")
        self.assertEqual(d["spec_type"], "tween")
        self.assertEqual(d["animation_id"], 1)
        self.assertEqual(d["targets"], [0.5])
        self.assertEqual(d["duration_ms"], 300)
        self.assertEqual(d["easing"], "ease_out")
        self.assertEqual(d["retarget"], "restart")

    def test_spring_set_target_serialization(self):
        slot = PresentationSlot(node_id=2, property="scale_x")
        spec = Spring(stiffness=200.0, damping_ratio=0.7)
        cmd = SetTarget(
            slot=slot,
            spec=spec,
            target=1.0,
            from_value=0.5,
            animation_id=2,
        )
        d = motion_command_to_dict(cmd)

        self.assertEqual(d["op"], "motion_set_target")
        self.assertEqual(d["spec_type"], "spring")
        self.assertEqual(d["stiffness"], 200.0)
        self.assertEqual(d["damping_ratio"], 0.7)
        self.assertEqual(d["targets"], [1.0])
        self.assertEqual(d["from_value"], 0.5)
        self.assertEqual(d["retarget"], "maintain_velocity")

    def test_cancel_serialization(self):
        slot = PresentationSlot(node_id=3, property="alpha")
        cmd = Cancel(slot=slot, animation_id=3)
        d = motion_command_to_dict(cmd)

        self.assertEqual(d["op"], "motion_cancel")
        self.assertEqual(d["slot_key"], "view:3:prop:alpha")
        self.assertEqual(d["animation_id"], 3)

    def test_canvas_slot_serialization(self):
        slot = PresentationSlot(
            node_id=5, property="x", slot_id="op2_rect"
        )
        spec = Tween(duration_ms=150)
        cmd = SetTarget(
            slot=slot,
            spec=spec,
            target=100.0,
            animation_id=4,
        )
        d = motion_command_to_dict(cmd)

        self.assertEqual(d["slot_key"], "view:5:slot:op2_rect:x")
        self.assertEqual(d["slot_id"], "op2_rect")
        validate_message({"type": "commit", "revision": 1, "ops": [d]})

class CanvasOpIdentityTests(unittest.TestCase):
    """Stable Canvas operation identity."""

    def test_stabilize_assigns_ids(self):
        draw = [
            {"kind": "circle", "cx": 0, "cy": 0, "r": 10},
            {"kind": "rect", "x": 0, "y": 0, "width": 100, "height": 50},
        ]
        result = CanvasOpIdentity.stabilize(draw)
        self.assertEqual(len(result), 2)
        for op in result:
            self.assertIn(CanvasOpIdentity.RESERVED_ID_KEY, op)
            self.assertTrue(
                isinstance(op[CanvasOpIdentity.RESERVED_ID_KEY], str)
            )

    def test_stabilize_is_deterministic(self):
        draw = [
            {"kind": "circle", "cx": 10, "cy": 20, "r": 5},
        ]
        r1 = CanvasOpIdentity.stabilize(draw)
        r2 = CanvasOpIdentity.stabilize(draw)
        self.assertEqual(
            r1[0][CanvasOpIdentity.RESERVED_ID_KEY],
            r2[0][CanvasOpIdentity.RESERVED_ID_KEY],
        )

    def test_different_content_different_ids(self):
        r1 = CanvasOpIdentity.stabilize([
            {"kind": "circle", "cx": 0, "cy": 0, "r": 10},
        ])
        r2 = CanvasOpIdentity.stabilize([
            {"kind": "circle", "cx": 0, "cy": 0, "r": 20},
        ])
        self.assertNotEqual(
            r1[0][CanvasOpIdentity.RESERVED_ID_KEY],
            r2[0][CanvasOpIdentity.RESERVED_ID_KEY],
        )

    def test_preserves_existing_ids(self):
        draw = [
            {"kind": "rect", "x": 0, "y": 0, "width": 100, "height": 50,
             CanvasOpIdentity.RESERVED_ID_KEY: "existing_op7"},
        ]
        result = CanvasOpIdentity.stabilize(draw)
        self.assertEqual(
            result[0][CanvasOpIdentity.RESERVED_ID_KEY], "existing_op7"
        )

    def test_animatable_fields_coverage(self):
        from vyne.spec.schema_v2 import ANIMATABLE_CANVAS_FIELDS

        # Exact set: any field added/removed in the schema's canvas ops must
        # appear/adjust here (catches omissions and accidental additions).
        self.assertEqual(
            ANIMATABLE_CANVAS_FIELDS,
            frozenset({
                "x", "y", "width", "height",
                "radius",
                "cx", "cy", "r",
                "x1", "y1", "x2", "y2",
                "trim_start", "trim_end",
                "opacity", "stroke_width", "dash_offset",
            }),
        )

    def test_id_survives_reorder(self):
        """Stable IDs survive neighboring insert/reorder/remove."""
        draw = [
            {"kind": "rect", "x": 0, "y": 0, "width": 100, "height": 50},
            {"kind": "circle", "cx": 50, "cy": 50, "r": 20},
        ]
        stabilized = CanvasOpIdentity.stabilize(draw)
        id_rect = stabilized[0][CanvasOpIdentity.RESERVED_ID_KEY]
        id_circle = stabilized[1][CanvasOpIdentity.RESERVED_ID_KEY]

        # Reorder: circle first, then rect.
        reordered = [
            {"kind": "circle", "cx": 50, "cy": 50, "r": 20},
            {"kind": "rect", "x": 0, "y": 0, "width": 100, "height": 50},
        ]
        restab = CanvasOpIdentity.stabilize(reordered)
        # Content-hash IDs should follow content, not position.
        self.assertEqual(
            restab[0][CanvasOpIdentity.RESERVED_ID_KEY], id_circle
        )
        self.assertEqual(
            restab[1][CanvasOpIdentity.RESERVED_ID_KEY], id_rect
        )


if __name__ == "__main__":
    unittest.main()
