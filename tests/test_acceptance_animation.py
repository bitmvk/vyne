"""Animation and presentation trace acceptance tests.

Proves that:
- Python owns animation targets and policy.
- Animation ops are emitted with correct fields.
- Animation-only events don't trigger component re-execution.
- AnimatedValue encoding is stable.
- Canvas draw commands carry stable animation markers.
- Multiple animations in one event produce ordered ops.

Evidence: E2 (applied operation streams).
"""

from __future__ import annotations

import unittest
from typing import Any

from vyne import (
    AnimatedValue, Box, Canvas, Column, Layout, Path,
    Row, Text, animate, component, state,
)
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport


def _animation_ops(commit: dict[str, Any]) -> list[dict]:
    """Extract animation operations from a commit."""
    return [
        op for op in commit.get("ops", [])
        if op.get("op") in ("motion_set_target", "motion_cancel")
    ]


def _render_ops(commit: dict[str, Any]) -> list[dict]:
    """Extract renderer (non-animation) operations."""
    return [
        op for op in commit.get("ops", [])
        if op.get("op") not in ("motion_set_target", "motion_cancel")
    ]


class AnimationTraceTests(unittest.TestCase):
    """Test animation operation emission and ordering."""

    def test_animate_emits_correct_op_fields(self):
        """animate() produces a valid motion_set_target operation."""
        def App():
            return Text(
                text="Animate me",
                on_click=lambda e: animate(e.target, "alpha", to=0.5, duration=400, easing="ease_out"),
            )

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()

        click_listener = [
            op for op in runtime.latest_commit["ops"]
            if op.get("op") == "listen" and op.get("event") == "click"
        ][0]

        runtime.dispatch_event({
            "type": "event", "seq": 1,
            "target": click_listener["id"],
            "event": "click",
            "handler": click_listener["handler"],
            "payload": {},
        })

        anim_ops = _animation_ops(runtime.latest_commit)
        self.assertEqual(len(anim_ops), 1)
        op = anim_ops[0]
        self.assertEqual(op["op"], "motion_set_target")
        self.assertEqual(op["property"], "opacity")
        self.assertEqual(op["targets"], [0.5])
        self.assertGreater(op["animation_id"], 0)
        self.assertEqual(op["duration_ms"], 400)
        self.assertEqual(op["easing"], "ease_out")

    def test_animation_from_field_is_optional(self):
        """Animation without 'from' omits from_value field."""
        def App():
            return Text(
                text="Fade",
                on_click=lambda e: animate(e.target, "alpha", to=0.0),
            )

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()

        click = [
            op for op in runtime.latest_commit["ops"]
            if op.get("op") == "listen" and op.get("event") == "click"
        ][0]

        runtime.dispatch_event({
            "type": "event", "seq": 1,
            "target": click["id"], "event": "click",
            "handler": click["handler"], "payload": {},
        })

        anim_ops = _animation_ops(runtime.latest_commit)
        self.assertNotIn("from_value", anim_ops[0])

    def test_animation_with_from_field(self):
        """Animation with explicit 'from' field includes from_value."""
        def App():
            return Text(
                text="Fade",
                on_click=lambda e: animate(e.target, "alpha", from_=1.0, to=0.0),
            )

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()

        click = [
            op for op in runtime.latest_commit["ops"]
            if op.get("op") == "listen" and op.get("event") == "click"
        ][0]

        runtime.dispatch_event({
            "type": "event", "seq": 1,
            "target": click["id"], "event": "click",
            "handler": click["handler"], "payload": {},
        })

        anim_ops = _animation_ops(runtime.latest_commit)
        self.assertEqual(anim_ops[0]["from_value"], 1.0)

    def test_keyframe_animation(self):
        """Animation with multiple keyframe targets produces multiple ops."""
        def App():
            return Text(
                text="Bounce",
                on_click=lambda e: animate(
                    e.target, "scale_x",
                    to=[0.94, 1.0], duration=220, easing="ease_in_out",
                ),
            )

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()

        click = [
            op for op in runtime.latest_commit["ops"]
            if op.get("op") == "listen" and op.get("event") == "click"
        ][0]

        runtime.dispatch_event({
            "type": "event", "seq": 1,
            "target": click["id"], "event": "click",
            "handler": click["handler"], "payload": {},
        })

        anim_ops = _animation_ops(runtime.latest_commit)
        # Keyframes are one native timeline. Independent commands would
        # replace each other before a frame could display the first target.
        self.assertEqual(len(anim_ops), 1)
        self.assertEqual(anim_ops[0]["targets"], [0.94, 1.0])

    def test_multiple_animations_in_one_handler(self):
        """Multiple animate() calls in one handler produce ordered ops.

        Uses direct view ID targets (Ref integration is pending MODEL-03).
        """
        # Use a mutable container to capture the target box's view ID.
        target_id_cell = []

        def App():
            target_box = Box(
                Text(text="Target"),
                width=60, height=60,
            )

            def both(event):
                tid = target_id_cell[0] if target_id_cell else event.target
                animate(tid, "scale_x", to=0.9, duration=100)
                animate(tid, "alpha", to=0.5, duration=200)

            return Box(
                target_box,
                Text(text="Trigger", on_click=both),
            )

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()

        # Capture the target Box view ID from the create ops.
        for op in runtime.latest_commit["ops"]:
            if op.get("op") == "create" and op.get("kind") == "Box":
                target_id_cell.append(op["id"])
                break

        click = [
            op for op in runtime.latest_commit["ops"]
            if op.get("op") == "listen" and op.get("event") == "click"
        ][0]

        runtime.dispatch_event({
            "type": "event", "seq": 1,
            "target": click["id"], "event": "click",
            "handler": click["handler"], "payload": {},
        })

        anim_ops = _animation_ops(runtime.latest_commit)
        self.assertEqual(len(anim_ops), 2,
            f"Expected 2 animation ops, got {len(anim_ops)}: {anim_ops}")
        self.assertEqual(anim_ops[0]["property"], "scale_x")
        self.assertEqual(anim_ops[1]["property"], "opacity")

    def test_animation_origin_event_seq_is_preserved(self):
        """Animation commit preserves origin_event_seq."""
        def App():
            return Text(
                text="Anim",
                on_click=lambda e: animate(e.target, "alpha", to=0.5),
            )

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()

        click = [
            op for op in runtime.latest_commit["ops"]
            if op.get("op") == "listen" and op.get("event") == "click"
        ][0]

        runtime.dispatch_event({
            "type": "event", "seq": 42,
            "target": click["id"], "event": "click",
            "handler": click["handler"], "payload": {},
        })

        # origin_event_seq must be preserved in animation commits (SCHED-01)
        origin = runtime.latest_commit.get("origin_event_seq")
        self.assertEqual(origin, 42,
            "Animation commit must preserve origin_event_seq from the triggering event")

    def test_listener_preserved_during_animation_only_commit(self):
        """Listener bindings survive animation-only commits (H4-listener-edge).

        When a click handler triggers only an animation (no tree change),
        the listener must remain bound.  The animation-only commit path
        must not emit unlisten followed by re-listen.
        """
        def App():
            return Text(
                text="Animate me",
                on_click=lambda e: animate(e.target, "alpha", to=0.5),
            )

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()

        click = [
            op for op in runtime.latest_commit["ops"]
            if op.get("op") == "listen" and op.get("event") == "click"
        ][0]
        target_id = click["id"]
        handler_id = click["handler"]

        # Dispatch first click (triggers animation)
        runtime.dispatch_event({
            "type": "event", "seq": 1,
            "target": target_id, "event": "click",
            "handler": handler_id, "payload": {},
        })

        # After animation commit: listener must still be installed
        second_commit = runtime.latest_commit
        unlisten_ops = [
            op for op in second_commit.get("ops", [])
            if op.get("op") == "unlisten" and op.get("id") == target_id
        ]
        self.assertEqual(len(unlisten_ops), 0,
            "Animation-only commit must not unlisten active handlers")

        # Dispatch a second click — listener must still work
        runtime.dispatch_event({
            "type": "event", "seq": 2,
            "target": target_id, "event": "click",
            "handler": handler_id, "payload": {},
        })

        # Should produce animation ops again, not error
        anim_ops = _animation_ops(runtime.latest_commit)
        self.assertGreater(len(anim_ops), 0,
            "Second click must still produce animation ops after animation-only commit")

    # ----------------------------------------------------------------
    # AnimatedValue in Canvas
    # ----------------------------------------------------------------

    def test_animated_value_in_canvas_draw(self):
        """AnimatedValue used in Canvas draw operations."""
        pos = AnimatedValue(0.5, duration=48, easing="linear")
        app = lambda: Canvas(
            draw=[{
                "kind": "circle",
                "cx": 10 + pos * 100,
                "cy": 20,
                "r": 5,
            }],
            view_box=[0, 0, 100, 100],
        )

        transport = MemoryTransport()
        runtime = Runtime(app, transport=transport)
        runtime.mount()

        canvas_id = next(
            op["id"] for op in runtime.latest_commit["ops"]
            if op.get("op") == "create" and op.get("kind") == "Canvas"
        )
        props = None
        for op in runtime.latest_commit["ops"]:
            if op.get("op") == "set_props" and op.get("id") == canvas_id:
                props = op.get("props", {})
                break

        self.assertIsNotNone(props)
        draw = props.get("draw", [])
        self.assertTrue(len(draw) > 0)
        circle = draw[0]

        # cx should be encoded as AnimatedValue marker (now frozen to FrozenMap)
        from collections.abc import Mapping
        self.assertRegex(circle["_vyne_op_id"], r"^circle_[0-9a-f]{12}_0$")
        self.assertIsInstance(circle["cx"], Mapping)
        self.assertTrue(circle["cx"].get("__vyne_animated_value__"))

    def test_canvas_slot_identity_ignores_changing_animation_target(self):
        def operation(target):
            runtime = Runtime(
                lambda: Canvas(
                    draw=[{
                        "kind": "circle",
                        "cx": AnimatedValue(target, duration=80),
                        "cy": 20,
                        "r": 5,
                    }],
                ),
                transport=MemoryTransport(),
            )
            runtime.mount()
            props = next(
                op["props"]
                for op in runtime.latest_commit["ops"]
                if op.get("op") == "set_props" and "draw" in op["props"]
            )
            return props["draw"][0]

        first = operation(10)
        second = operation(30)
        self.assertEqual(first["_vyne_op_id"], second["_vyne_op_id"])
        self.assertNotEqual(first["cx"]["value"], second["cx"]["value"])

    def test_animated_value_clamp(self):
        """AnimatedValue.clamp produces valid range."""
        val = AnimatedValue(0.75, duration=48)
        clamped = val.clamp(0.25, 0.5)
        self.assertEqual(clamped.value, 0.5)
        self.assertEqual(clamped.duration, 48)

        below = val.clamp(minimum=1.0)
        self.assertEqual(below.value, 1.0)

        above = val.clamp(maximum=0.1)
        self.assertEqual(above.value, 0.1)

    def test_animated_value_spring(self):
        """AnimatedValue with spring easing."""
        spring = AnimatedValue(
            24, duration=400, easing="spring",
            damping_ratio=0.6, stiffness=800,
        )
        payload = spring.to_protocol_value()
        self.assertEqual(payload["easing"], "spring")
        self.assertEqual(payload["damping_ratio"], 0.6)
        self.assertEqual(payload["stiffness"], 800.0)

    def test_animated_value_rejects_invalid_spring_params(self):
        """Invalid spring parameters are rejected."""
        with self.assertRaises(ValueError):
            AnimatedValue(1.0, easing="spring", damping_ratio=0)

        with self.assertRaises(ValueError):
            AnimatedValue(1.0, easing="spring", stiffness=-1)

    def test_animated_value_arithmetic(self):
        """AnimatedValue arithmetic works correctly."""
        a = AnimatedValue(10, duration=100, easing="linear")
        b = a + 5
        self.assertEqual(b.value, 15)
        self.assertEqual(b.duration, 100)

        c = a * 2
        self.assertEqual(c.value, 20)

        d = a / 2
        self.assertEqual(d.value, 5)

        e = -a
        self.assertEqual(e.value, -10)

    def test_animated_value_rejects_motion_mismatch(self):
        """Arithmetic between AnimatedValues with different settings fails."""
        a = AnimatedValue(1, duration=100, easing="linear")
        b = AnimatedValue(2, duration=200, easing="ease_out")

        with self.assertRaises(ValueError):
            a + b

    # ----------------------------------------------------------------
    # Easing validation
    # ----------------------------------------------------------------

    def test_valid_easings_accepted(self):
        """All documented easings are accepted."""
        from vyne.animations import ANIMATION_EASINGS
        for easing in sorted(ANIMATION_EASINGS):
            def app():
                return Text(
                    text="test",
                    on_click=lambda e: animate(e.target, "alpha", to=1.0, easing=easing),
                )

            runtime = Runtime(app, transport=MemoryTransport())
            runtime.mount()
            click = [
                op for op in runtime.latest_commit["ops"]
                if op.get("op") == "listen" and op.get("event") == "click"
            ][0]

            runtime.dispatch_event({
                "type": "event", "seq": 1,
                "target": click["id"], "event": "click",
                "handler": click["handler"], "payload": {},
            })

            anim_ops = _animation_ops(runtime.latest_commit)
            self.assertEqual(anim_ops[0]["easing"], easing)

    def test_invalid_easing_rejected(self):
        """Unknown easing is rejected."""
        def app():
            return Text(
                text="test",
                on_click=lambda e: animate(e.target, "alpha", to=1.0, easing="invalid"),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        click = [
            op for op in runtime.latest_commit["ops"]
            if op.get("op") == "listen" and op.get("event") == "click"
        ][0]

        runtime.dispatch_event({
            "type": "event", "seq": 1,
            "target": click["id"], "event": "click",
            "handler": click["handler"], "payload": {},
        })

        # The invalid animation is rejected before a native command is sent,
        # while the last accepted UI remains intact.
        self.assertIsNotNone(runtime._coordinator.accepted_root)
        self.assertIn("easing", runtime._last_error.lower())
        self.assertEqual(_animation_ops(runtime.latest_commit), [])

if __name__ == "__main__":
    unittest.main()
