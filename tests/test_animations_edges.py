"""Edge-case tests for the animate() API.

Covers the numeric operator contract, spring validation, protocol lowering,
and the target-resolution rules (int / Ref / ViewHandle) that guard
against stale identity.
"""

from __future__ import annotations

import math
import unittest
from weakref import ref as weakref

from vyne import AnimationHandle, Box
from vyne.animations import (
    ANIMATED_NODE_MARKER,
    AnimatedNode,
    animate,
    encode_animated_values,
    is_animated_node_payload,
)
from vyne.motion import RetargetPolicy, SetTarget, Spring, Tween
from vyne.refs import Ref, ViewHandle
from vyne.runtime import Runtime
from vyne.state import runtime_context
from vyne.transport import MemoryTransport
from vyne.values import FrozenMap


class _RuntimeStub:
    """Weakref-able stand-in for the Runtime owner of an AnimatedNode."""


class AnimatedNodeEncodingTests(unittest.TestCase):
    """Wire encoding of AnimatedNode through the production path.

    These tests use real :class:`AnimatedNode` instances and
    ``encode_animated_values`` / ``is_animated_node_payload`` so a change to
    the marker shape fails here instead of silently passing a hand-rolled
    fixture.
    """

    def _node(self, initial: float = 1.0) -> AnimatedNode:
        return AnimatedNode(
            {"op": "value", "driver_id": 1, "initial": initial},
            runtime=weakref(_RuntimeStub()),
            driver_ids=frozenset({1}),
            initial=initial,
        )

    def test_encode_animated_values_recurses_containers(self):
        value = {
            "list": [self._node(1.0), (self._node(2.0),)],
            "frozen": FrozenMap([("x", self._node(3.0))]),
            "plain": 4,
        }
        encoded = encode_animated_values(value)
        self.assertTrue(is_animated_node_payload(encoded["list"][0]))
        self.assertTrue(is_animated_node_payload(encoded["list"][1][0]))
        self.assertTrue(is_animated_node_payload(encoded["frozen"]["x"]))
        self.assertEqual(encoded["plain"], 4)

    def test_encode_animated_values_nested(self):
        data = {"outer": [{"inner": self._node(0.5)}]}
        encoded = encode_animated_values(data)
        inner = encoded["outer"][0]["inner"]
        self.assertTrue(is_animated_node_payload(inner))
        self.assertTrue(inner[ANIMATED_NODE_MARKER])

    def test_encode_leaves_plain_values_untouched(self):
        original = {"a": [1, "x", None, True]}
        self.assertEqual(encode_animated_values(original), original)

    def test_is_animated_node_payload_requires_marker(self):
        self.assertFalse(is_animated_node_payload({"value": 1.0}))
        self.assertFalse(is_animated_node_payload(1.0))
        self.assertFalse(is_animated_node_payload([]))
        self.assertTrue(
            is_animated_node_payload(
                FrozenMap([(ANIMATED_NODE_MARKER, True), ("value", 1.0)])
            )
        )
        # The production payload shape is recognized.
        self.assertTrue(
            is_animated_node_payload(self._node(2.0).to_protocol_value())
        )


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
