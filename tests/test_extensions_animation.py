"""Extension scalar-animation acceptance tests.

Typed numeric extension props are animatable automatically through the same
MotionCommand pipeline as core numeric props.  These tests use the shared
TimerRing fixture (``progress`` is declared as a float with min=0 and max=1).
"""

from __future__ import annotations

import unittest

from vyne import Box, animate
from vyne.elements import Element
from vyne.runtime import Runtime
from vyne.state import runtime_context
from vyne.transport import MemoryTransport

from tests.support.extension_kinds import (
    activate_extension_kinds,
    deactivate_extension_kinds,
)


def setUpModule() -> None:
    activate_extension_kinds()


def tearDownModule() -> None:
    deactivate_extension_kinds()


def _motion_ops(runtime: Runtime) -> list[dict]:
    return [
        op
        for op in runtime.latest_commit["ops"]
        if op.get("op") == "motion_set_target"
    ]


class ExtensionAnimationTests(unittest.TestCase):
    def _mounted_timer_ring(self) -> tuple[Runtime, int]:
        transport = MemoryTransport()
        runtime = Runtime(lambda: Box(Element("TimerRing", props={"progress": 0.2})),
                          transport=transport)
        runtime.mount()
        create = next(
            op
            for op in transport.latest["ops"]
            if op.get("op") == "create" and op.get("kind") == "TimerRing"
        )
        return runtime, create["id"]

    def test_typed_numeric_extension_prop_animates(self):
        runtime, view_id = self._mounted_timer_ring()
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                handle = animate(view_id, "progress", to=0.8, duration=240)
        finally:
            runtime._phase = None
        self.assertEqual(handle.status, "queued")
        command = runtime._anim_pending[0]
        self.assertEqual(command.slot.to_key(), f"view:{view_id}:prop:progress")
        self.assertEqual(command.targets, (0.8,))
        self.assertEqual(command.spec.duration_ms, 240)

    def test_typed_numeric_extension_prop_domain_is_enforced(self):
        runtime, view_id = self._mounted_timer_ring()
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                with self.assertRaisesRegex(ValueError, "<= 1.0"):
                    animate(view_id, "progress", to=1.5)
        finally:
            runtime._phase = None
        self.assertEqual(runtime._anim_pending, [])

    def test_opaque_extension_prop_is_still_not_animatable(self):
        runtime, view_id = self._mounted_timer_ring()
        runtime._phase = "event"
        try:
            with runtime_context(runtime):
                with self.assertRaisesRegex(ValueError, "not animatable"):
                    animate(view_id, "ring_color", to=1)
        finally:
            runtime._phase = None


if __name__ == "__main__":
    unittest.main()
