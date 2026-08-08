from __future__ import annotations

import unittest

from vyne import (
    Animated,
    AnimationGroupHandle,
    Box,
    Canvas,
    component,
    state,
)
from vyne.animations import ANIMATED_NODE_MARKER, _AnimationPlan, animate
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport


def _click(runtime: Runtime, sequence: int = 1) -> None:
    target, node = next(
        (node_id, node)
        for node_id, node in runtime._coordinator.accepted_index.items()
        if "click" in node.listeners
    )
    runtime.dispatch_event({
        "type": "event",
        "seq": sequence,
        "target": target,
        "event": "click",
        "handler": node.listeners["click"],
        "payload": {},
    })


def _complete(runtime: Runtime, handle, sequence: int) -> None:
    runtime.dispatch_event({
        "type": "event",
        "seq": sequence,
        "target": handle.slot.node_id,
        "event": "__vyne_system__",
        "handler": 0,
        "payload": {
            "type": "animation_lifecycle",
            "animation_id": handle.id,
            "status": "completed",
            "node_id": handle.slot.node_id,
            "property": handle.slot.property,
        },
    })


class DirectAnimationApiTests(unittest.TestCase):
    def test_named_destinations_start_together(self):
        handles = []

        def app():
            return Box(
                on_click=lambda event: handles.append(
                    animate(event.target, x=80, y=-8, opacity=0.5)
                )
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        _click(runtime)

        self.assertIsInstance(handles[0], AnimationGroupHandle)
        operations = runtime.latest_commit["ops"]
        self.assertEqual(
            {operation["property"] for operation in operations},
            {"translation_x", "translation_y", "opacity"},
        )
        self.assertEqual({operation["animation_id"] for operation in operations}, {
            child.id for child in handles[0].children
        })

    def test_scale_shorthand_expands_to_both_axes(self):
        runtime = Runtime(
            lambda: Box(
                on_click=lambda event: animate(
                    event.target,
                    scale=[0.94, 1.0],
                    duration=90,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        _click(runtime)

        operations = runtime.latest_commit["ops"]
        self.assertEqual(
            {operation["property"] for operation in operations},
            {"scale_x", "scale_y"},
        )
        self.assertTrue(all(operation["targets"] == [0.94, 1.0] for operation in operations))

    def test_legacy_positional_form_remains_supported(self):
        runtime = Runtime(
            lambda: Box(
                on_click=lambda event: animate(
                    event.target,
                    "opacity",
                    to=0.25,
                )
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()
        _click(runtime)
        self.assertEqual(runtime.latest_commit["ops"][0]["property"], "opacity")


class AdvancedAnimationApiTests(unittest.TestCase):
    def test_value_is_stable_and_serializes_an_expression(self):
        values = []

        @component
        def app():
            tick = state(0)
            progress = Animated.Value(0)
            values.append(progress)
            return Box(
                translation_x=4 + progress * 20,
                opacity=progress.clamp(0, 1),
                on_click=lambda: tick.set(tick.value + 1),
            )

        runtime = Runtime(lambda: app(), transport=MemoryTransport())
        runtime.mount()
        _click(runtime)

        self.assertIs(values[0], values[-1])
        node = next(iter(runtime._coordinator.accepted_index.values()))
        marker = node.props["translation_x"]
        self.assertTrue(marker[ANIMATED_NODE_MARKER])
        self.assertEqual(marker["expression"]["op"], "add")

    def test_one_driver_command_updates_multiple_bindings(self):
        plans = []

        @component
        def app():
            progress = Animated.Value(0)
            plans[:] = [progress]
            return Box(
                Box(
                    translation_x=progress.interpolate(
                        input_range=[0, 1],
                        output_range=[4, 214],
                    ),
                    opacity=progress,
                ),
                Canvas(
                    draw=[{
                        "kind": "circle",
                        "cx": 10 + progress * 100,
                        "cy": 20,
                        "r": 5,
                    }],
                ),
                on_click=lambda: Animated.timing(
                    progress,
                    to=1,
                    duration=620,
                ).start(),
            )

        runtime = Runtime(lambda: app(), transport=MemoryTransport())
        runtime.mount()
        _click(runtime)

        operations = runtime.latest_commit["ops"]
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]["op"], "motion_driver_set_target")
        self.assertEqual(operations[0]["driver_id"], plans[0].driver_id)
        self.assertEqual(operations[0]["targets"], [1.0])

    def test_sequence_compiles_to_one_native_driver_timeline(self):
        @component
        def app():
            x = Animated.Value(0)
            timeline = Animated.sequence([
                Animated.timing(x, to=10, duration=100),
                Animated.timing(x, to=20, duration=100),
                Animated.timing(x, to=0, duration=100),
            ])
            return Box(
                translation_x=x,
                on_click=lambda: timeline.start(),
            )

        runtime = Runtime(lambda: app(), transport=MemoryTransport())
        runtime.mount()
        _click(runtime)

        self.assertEqual(
            runtime.latest_commit["ops"][0]["targets"],
            [10.0, 20.0, 0.0],
        )

    def test_mixed_sequence_advances_on_ordered_lifecycle(self):
        handles = []

        @component
        def app():
            x = Animated.Value(0)
            timeline = Animated.sequence([
                Animated.timing(x, to=20, duration=100),
                Animated.spring(x, to=0),
            ])
            return Box(
                translation_x=x,
                on_click=lambda: handles.append(timeline.start()),
            )

        runtime = Runtime(lambda: app(), transport=MemoryTransport())
        runtime.mount()
        _click(runtime)
        first = handles[0]._current
        self.assertEqual(runtime.latest_commit["ops"][0]["spec_type"], "tween")

        _complete(runtime, first, 2)

        self.assertEqual(runtime.latest_commit["ops"][0]["spec_type"], "spring")

    def test_parallel_can_compose_a_sequence_with_another_driver(self):
        handles = []

        @component
        def app():
            x = Animated.Value(0)
            opacity = Animated.Value(1)
            plan = Animated.parallel([
                Animated.sequence([
                    Animated.timing(x, to=20, duration=100),
                    Animated.timing(x, to=0, duration=140),
                ]),
                Animated.timing(opacity, to=0.5, duration=240),
            ])
            return Box(
                translation_x=x,
                opacity=opacity,
                on_click=lambda: handles.append(plan.start()),
            )

        runtime = Runtime(lambda: app(), transport=MemoryTransport())
        runtime.mount()
        _click(runtime)

        group = handles[0]
        sequence, opacity = group.children
        first_x = sequence._current
        self.assertEqual(len(runtime.latest_commit["ops"]), 2)

        _complete(runtime, first_x, 2)
        second_x = sequence._current
        self.assertNotEqual(first_x.id, second_x.id)

        _complete(runtime, opacity, 3)
        self.assertFalse(group.done)
        _complete(runtime, second_x, 4)
        self.assertTrue(group.done)
        self.assertEqual(group.status, "completed")

    def test_parallel_rejects_two_branches_for_the_same_driver(self):
        @component
        def app():
            x = Animated.Value(0)
            return Box(
                translation_x=x,
                on_click=lambda: Animated.parallel([
                    Animated.timing(x, to=10),
                    Animated.spring(x, to=20),
                ]).start(),
            )

        runtime = Runtime(lambda: app(), transport=MemoryTransport())
        runtime.mount()
        _click(runtime)
        self.assertIn(
            "cannot animate the same Animated.Value twice",
            runtime._last_error,
        )

    def test_direct_animation_rejects_driver_bound_slot(self):
        @component
        def app():
            x = Animated.Value(0)
            return Box(
                translation_x=x,
                on_click=lambda event: animate(event.target, x=10),
            )

        runtime = Runtime(lambda: app(), transport=MemoryTransport())
        runtime.mount()
        revision = runtime.revision
        _click(runtime)
        self.assertEqual(runtime.revision, revision)
        self.assertIn("bound to Animated.Value", runtime._last_error)

    def test_unmounted_component_releases_its_driver(self):
        @component
        def child():
            opacity = Animated.Value(1)
            return Box(opacity=opacity)

        def app():
            visible = state(True)
            return Box(
                child() if visible.value else None,
                on_click=lambda: visible.set(False),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        self.assertEqual(set(runtime._animated_drivers), {1})

        _click(runtime)

        self.assertEqual(runtime._animated_drivers, {})

    def test_failed_render_releases_new_driver(self):
        def app():
            Animated.Value(0)
            raise RuntimeError("injected render failure")

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()

        self.assertEqual(runtime._animated_drivers, {})
        self.assertIn("injected render failure", runtime._last_error)

    def test_parallel_rejects_unknown_plan_subtype(self):
        class UnknownPlan(_AnimationPlan):
            pass

        with self.assertRaisesRegex(TypeError, "Unsupported animation plan"):
            Animated.parallel([UnknownPlan()]).start()


if __name__ == "__main__":
    unittest.main()
