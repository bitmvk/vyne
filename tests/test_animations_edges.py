"""Edge-case tests for AnimatedValue arithmetic and the animate() API.

Covers the numeric operator contract, spring validation, protocol lowering,
and the target-resolution rules (int / Ref / ViewHandle) that guard
against stale identity.
"""

from __future__ import annotations

import math
import unittest

from vyne import AnimationHandle, Box
from vyne.animations import (
    ANIMATED_VALUE_MARKER,
    AnimatedValue,
    animate,
    encode_animated_values,
    is_animated_value_payload,
)
from vyne.motion import RetargetPolicy, SetTarget, Spring, Tween
from vyne.refs import Ref, ViewHandle
from vyne.runtime import Runtime
from vyne.state import runtime_context
from vyne.transport import MemoryTransport
from vyne.values import FrozenMap


class AnimatedValueConstructionTests(unittest.TestCase):
    def test_rejects_non_finite_and_bool_values(self):
        for bad in (math.nan, math.inf, True, "1", None):
            with self.subTest(value=bad):
                with self.assertRaises(TypeError):
                    AnimatedValue(bad)

    def test_rejects_bad_duration(self):
        with self.assertRaises(ValueError):
            AnimatedValue(1.0, duration=-1)
        with self.assertRaises(ValueError):
            AnimatedValue(1.0, duration=1.5)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            AnimatedValue(1.0, duration=True)  # type: ignore[arg-type]
        AnimatedValue(1.0, duration=0)  # zero is legal (jump)

    def test_rejects_unknown_easing(self):
        with self.assertRaisesRegex(ValueError, "easing"):
            AnimatedValue(1.0, easing="wobble")

    def test_retarget_defaults_match_motion_spec_defaults(self):
        self.assertEqual(AnimatedValue(1.0).retarget, "restart")
        self.assertEqual(
            AnimatedValue(1.0, easing="spring").retarget,
            "maintain_velocity",
        )

    def test_rejects_unknown_or_non_string_retarget_policy(self):
        for bad in ("coast", True, 1):
            with self.subTest(retarget=bad):
                with self.assertRaisesRegex(ValueError, "retarget"):
                    AnimatedValue(1.0, retarget=bad)  # type: ignore[arg-type]

    def test_spring_parameters_require_spring_easing(self):
        with self.assertRaisesRegex(ValueError, "spring"):
            AnimatedValue(1.0, damping_ratio=0.5)
        with self.assertRaisesRegex(ValueError, "spring"):
            AnimatedValue(1.0, stiffness=200.0)

    def test_spring_parameter_validation(self):
        with self.assertRaisesRegex(ValueError, "damping"):
            AnimatedValue(1.0, easing="spring", damping_ratio=0)
        with self.assertRaisesRegex(ValueError, "stiffness"):
            AnimatedValue(1.0, easing="spring", stiffness=-10)
        with self.assertRaisesRegex(ValueError, "damping"):
            AnimatedValue(1.0, easing="spring", damping_ratio=math.nan)

    def test_spring_defaults_materialized(self):
        value = AnimatedValue(1.0, easing="spring")
        self.assertEqual(value.damping_ratio, 0.8)
        self.assertEqual(value.stiffness, 380.0)


class AnimatedValueArithmeticTests(unittest.TestCase):
    def test_full_operator_set(self):
        base = AnimatedValue(10.0, duration=100)
        self.assertEqual((base + 5).value, 15.0)
        self.assertEqual((5 + base).value, 15.0)
        self.assertEqual((base - 3).value, 7.0)
        self.assertEqual((30 - base).value, 20.0)
        self.assertEqual((base * 2).value, 20.0)
        self.assertEqual((2 * base).value, 20.0)
        self.assertEqual((base / 4).value, 2.5)
        self.assertEqual((40 / base).value, 4.0)
        self.assertEqual((-base).value, -10.0)

    def test_arithmetic_preserves_motion_settings(self):
        base = AnimatedValue(
            1.0,
            duration=123,
            easing="ease_in",
            retarget="maintain_velocity",
        )
        result = base * 3
        self.assertEqual(result.duration, 123)
        self.assertEqual(result.easing, "ease_in")
        self.assertEqual(result.retarget, "maintain_velocity")

    def test_arithmetic_between_matching_animated_values(self):
        a = AnimatedValue(2.0, duration=100)
        b = AnimatedValue(3.0, duration=100)
        self.assertEqual((a + b).value, 5.0)

    def test_arithmetic_requires_matching_motion_settings(self):
        a = AnimatedValue(2.0, duration=100)
        b = AnimatedValue(3.0, duration=200)
        with self.assertRaisesRegex(ValueError, "motion settings"):
            a + b
        c = AnimatedValue(2.0, duration=100, retarget="maintain_velocity")
        with self.assertRaisesRegex(ValueError, "motion settings"):
            a + c

    def test_arithmetic_rejects_bool_and_non_finite(self):
        base = AnimatedValue(1.0)
        for bad in (True, math.nan, math.inf, "x"):
            with self.subTest(other=bad):
                with self.assertRaises(TypeError):
                    base + bad

    def test_division_by_zero_both_directions(self):
        base = AnimatedValue(1.0)
        with self.assertRaises(ZeroDivisionError):
            base / 0
        zero = AnimatedValue(0.0)
        with self.assertRaises(ZeroDivisionError):
            1 / zero

    def test_clamp(self):
        base = AnimatedValue(5.0)
        self.assertEqual(base.clamp(minimum=6).value, 6.0)
        self.assertEqual(base.clamp(maximum=4).value, 4.0)
        self.assertEqual(base.clamp(0, 10).value, 5.0)
        self.assertEqual(base.clamp().value, 5.0)


class AnimatedValueLoweringTests(unittest.TestCase):
    def test_to_spec_mapping(self):
        tween = AnimatedValue(
            1.0,
            duration=250,
            easing="ease_in",
            retarget="maintain_velocity",
        ).to_spec()
        self.assertIsInstance(tween, Tween)
        self.assertEqual(tween.duration_ms, 250)
        self.assertEqual(tween.retarget, RetargetPolicy.MAINTAIN_VELOCITY)
        spring = AnimatedValue(1.0, easing="spring").to_spec()
        self.assertIsInstance(spring, Spring)
        self.assertEqual(spring.retarget, RetargetPolicy.MAINTAIN_VELOCITY)

    def test_protocol_value_shape(self):
        payload = AnimatedValue(0.5, duration=120).to_protocol_value(op_id="op-1")
        self.assertTrue(payload[ANIMATED_VALUE_MARKER])
        self.assertEqual(payload["_vyne_op_id"], "op-1")
        self.assertEqual(payload["retarget"], "restart")
        self.assertNotIn("stiffness", payload)
        spring = AnimatedValue(
            1.0,
            easing="spring",
            retarget="snap_to_end",
        ).to_protocol_value()
        self.assertIn("stiffness", spring)
        self.assertIn("damping_ratio", spring)
        self.assertEqual(spring["retarget"], "snap_to_end")
        self.assertNotIn("_vyne_op_id", spring)

    def test_encode_animated_values_recurses_containers(self):
        value = {
            "list": [AnimatedValue(1.0), (AnimatedValue(2.0),)],
            "frozen": FrozenMap([("x", AnimatedValue(3.0))]),
            "plain": 4,
        }
        encoded = encode_animated_values(value)
        self.assertTrue(is_animated_value_payload(encoded["list"][0]))
        self.assertTrue(is_animated_value_payload(encoded["list"][1][0]))
        self.assertTrue(is_animated_value_payload(encoded["frozen"]["x"]))
        self.assertEqual(encoded["plain"], 4)

    def test_is_animated_value_payload_requires_marker(self):
        self.assertFalse(is_animated_value_payload({"value": 1.0}))
        self.assertFalse(is_animated_value_payload(1.0))
        self.assertTrue(is_animated_value_payload(
            FrozenMap([(ANIMATED_VALUE_MARKER, True), ("value", 1.0)])
        ))


class AnimateTargetResolutionTests(unittest.TestCase):
    """animate() guards runtime context and target identity."""

    def _mounted_runtime(self) -> tuple[Runtime, int]:
        ref = Ref()
        transport = MemoryTransport()
        runtime = Runtime(lambda: Box(ref=ref), transport=transport)
        runtime.mount()
        create = next(op for op in transport.latest["ops"] if op["op"] == "create")
        return runtime, create["id"]

    def test_requires_runtime_context(self):
        with self.assertRaisesRegex(RuntimeError, "rendering or in event handlers"):
            animate(1, "alpha", to=0.5)

    def test_requires_render_or_event_phase(self):
        runtime, view_id = self._mounted_runtime()
        with runtime_context(runtime):
            with self.assertRaisesRegex(RuntimeError, "rendering or in event handlers"):
                animate(view_id, "alpha", to=0.5)

    def test_unknown_view_id_rejected(self):
        runtime, _ = self._mounted_runtime()
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                with self.assertRaisesRegex(ValueError, "unknown view id"):
                    animate(999_999, "alpha", to=0.5)
        finally:
            runtime._phase = None

    def test_stale_view_handle_rejected(self):
        runtime, view_id = self._mounted_runtime()
        handle = ViewHandle(view_id, "Box")
        handle._invalidate()
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                with self.assertRaisesRegex(RuntimeError, "stale"):
                    animate(handle, "alpha", to=0.5)
        finally:
            runtime._phase = None

    def test_unattached_ref_rejected(self):
        runtime, _ = self._mounted_runtime()
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                with self.assertRaisesRegex(RuntimeError, "not attached"):
                    animate(Ref(), "alpha", to=0.5)
        finally:
            runtime._phase = None

    def test_element_target_rejected(self):
        runtime, _ = self._mounted_runtime()
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                with self.assertRaisesRegex(TypeError, "int, Ref, or ViewHandle"):
                    animate(Box(), "alpha", to=0.5)  # type: ignore[arg-type]
        finally:
            runtime._phase = None

    def test_empty_keyframes_rejected(self):
        runtime, view_id = self._mounted_runtime()
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                with self.assertRaisesRegex(ValueError, "empty"):
                    animate(view_id, "alpha", to=[])
        finally:
            runtime._phase = None

    def test_keyframe_sequence_is_one_native_timeline(self):
        runtime, view_id = self._mounted_runtime()
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                animate(view_id, "alpha", from_=0.0, to=[0.5, 1.0, 0.25])
        finally:
            runtime._phase = None
        queued = runtime._anim_pending
        self.assertEqual(len(queued), 1)
        self.assertTrue(all(isinstance(cmd, SetTarget) for cmd in queued))
        self.assertEqual(queued[0].from_value, 0.0)
        self.assertEqual(queued[0].targets, (0.5, 1.0, 0.25))
        self.assertEqual({cmd.slot.node_id for cmd in queued}, {view_id})

    def test_spring_easing_produces_spring_spec(self):
        runtime, view_id = self._mounted_runtime()
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                animate(view_id, "scale_x", to=2.0, easing="spring")
        finally:
            runtime._phase = None
        self.assertIsInstance(runtime._anim_pending[0].spec, Spring)

    def test_explicit_retarget_policy_reaches_motion_spec(self):
        runtime, view_id = self._mounted_runtime()
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                animate(
                    view_id,
                    "translation_x",
                    to=20.0,
                    easing="linear",
                    retarget="maintain_velocity",
                )
        finally:
            runtime._phase = None
        spec = runtime._anim_pending[0].spec
        self.assertIsInstance(spec, Tween)
        self.assertEqual(spec.retarget, RetargetPolicy.MAINTAIN_VELOCITY)

    def test_animate_rejects_unknown_retarget_policy(self):
        runtime, view_id = self._mounted_runtime()
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                with self.assertRaisesRegex(ValueError, "retarget"):
                    animate(view_id, "opacity", to=0.5, retarget="coast")
        finally:
            runtime._phase = None

    def test_alpha_alias_normalizes_and_returns_handle(self):
        runtime, view_id = self._mounted_runtime()
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                handle = animate(view_id, "alpha", to=0.5)
        finally:
            runtime._phase = None
        self.assertIsInstance(handle, AnimationHandle)
        self.assertEqual(handle.slot.property, "opacity")

    def test_rejects_non_animatable_property_and_out_of_domain_target(self):
        runtime, view_id = self._mounted_runtime()
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                with self.assertRaisesRegex(ValueError, "not animatable"):
                    animate(view_id, "text", to=1)
                with self.assertRaises(ValueError):
                    animate(view_id, "opacity", to=1.5)
        finally:
            runtime._phase = None

    def test_rejects_invalid_lifecycle_callbacks_and_spring_parameters(self):
        runtime, view_id = self._mounted_runtime()
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                with self.assertRaisesRegex(TypeError, "on_complete"):
                    animate(
                        view_id,
                        "opacity",
                        to=0.5,
                        on_complete=42,  # type: ignore[arg-type]
                    )
                with self.assertRaisesRegex(ValueError, "easing='spring'"):
                    animate(
                        view_id,
                        "opacity",
                        to=0.5,
                        damping_ratio=0.8,
                    )
        finally:
            runtime._phase = None

    def test_valid_ref_target_resolves_to_node_id(self):
        ref = Ref()
        transport = MemoryTransport()
        runtime = Runtime(lambda: Box(ref=ref), transport=transport)
        runtime.mount()
        handle = ref.current
        self.assertIsNotNone(handle)
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                animate(ref, "alpha", to=0.5)
        finally:
            runtime._phase = None
        self.assertEqual(runtime._anim_pending[0].slot.node_id, handle.node_id)


if __name__ == "__main__":
    unittest.main()
