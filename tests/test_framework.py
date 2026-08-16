from __future__ import annotations

import unittest

from vyne import (
    animate,
    Box,
    Canvas,
    Column,
    component,
    Image,
    Layout,
    latest,
    Path,
    Row,
    Scroll,
    Text,
    TextInput,
    state,
)
from vyne.runtime import Runtime
from vyne.protocol import validate_message
from vyne.transport import MemoryTransport

from tests.support.runtime_helpers import (
    dispatch_native_event,
    find_listeners as _listeners,
    props_for_kind as _props_for_kind,
    set_props as _set_props,
)


class FrameworkTests(unittest.TestCase):
    def test_component_state_invalidates_only_its_native_subtree(self):
        calls = {"root": 0, "counter": 0, "sibling": 0}
        sibling_clicks: list[str] = []

        @component
        def Counter():
            calls["counter"] += 1
            count = state(0)
            return Column(
                Text(text=f"Count: {count.value}"),
                Text(text="Increment", on_click=lambda: count.set(count.value + 1)),
            )

        @component
        def Sibling():
            calls["sibling"] += 1
            return Text(text="Sibling", on_click=lambda: sibling_clicks.append("clicked"))

        def App():
            calls["root"] += 1
            return Column(Counter(), Sibling())

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()
        counter_listener, sibling_listener = _listeners(runtime.latest_commit, "click")
        sibling_node_before = runtime._coordinator.accepted_index[sibling_listener["id"]]

        dispatch_native_event(runtime, counter_listener)

        # SCHED-04: full reconciliation always re-executes root when any
        # descendant is dirty (descendant_dirty propagates up).
        self.assertEqual(calls, {"root": 2, "counter": 2, "sibling": 1})
        self.assertIs(
            runtime._coordinator.accepted_index[sibling_listener["id"]],
            sibling_node_before,
        )
        self.assertEqual(
            _set_props(runtime.latest_commit, "text"),
            [{"op": "set_prop", "id": 3, "name": "text", "value": "Count: 1"}],
        )

        # A scoped render must not garbage-collect handlers in untouched siblings.
        dispatch_native_event(runtime, sibling_listener, seq=2)
        self.assertEqual(sibling_clicks, ["clicked"])

    def test_component_props_rerender_scope_during_parent_render(self):
        calls = {"child": 0}

        @component
        def Child(label: str):
            calls["child"] += 1
            return Text(text=label)

        def App():
            label = state("first")
            return Column(
                Child(label.value),
                Text(text="Change", on_click=lambda: label.set("second")),
            )

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()
        listener = _listeners(runtime.latest_commit, "click")[0]
        dispatch_native_event(runtime, listener)

        self.assertEqual(calls["child"], 2)
        self.assertIn(
            {"op": "set_prop", "id": 2, "name": "text", "value": "second"},
            runtime.latest_commit["ops"],
        )

    def test_clean_component_output_skips_validation_and_diff(self):
        @component
        def StaticSection():
            return Column(*(Text(text=f"Static {index}") for index in range(50)))

        def App():
            value = state(0)
            return Column(
                StaticSection(),
                Text(text=str(value.value), on_click=lambda: value.set(value.value + 1)),
            )

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()
        cached_element = runtime._root_scope.children[0].output
        listener = _listeners(runtime.latest_commit, "click")[0]
        dispatch_native_event(runtime, listener)

        self.assertIs(runtime._root_scope.children[0].output, cached_element)
        self.assertEqual(len(_set_props(runtime.latest_commit, "text")), 1)

    def test_state_from_an_unmounted_component_is_inert(self):
        child_states = []

        @component
        def Child():
            value = state(0)
            child_states.append(value)
            return Text(text=str(value.value))

        def App():
            visible = state(True)
            return Column(
                Child() if visible.value else None,
                Text(text="Hide", on_click=lambda: visible.set(False)),
            )

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()
        listener = _listeners(runtime.latest_commit, "click")[0]
        dispatch_native_event(runtime, listener)
        revision = runtime.revision

        child_states[0].set(1)

        self.assertEqual(runtime.revision, revision)

    def test_latest_event_delivery_and_pointer_axis_are_serialized(self):
        def handle_move(event):
            return None

        runtime = Runtime(
            lambda: Box(
                pointer_capture_axis="horizontal",
                on_pointer_move=latest(handle_move),
            )
        )
        runtime.mount()

        self.assertTrue(
            any(
                operation.get("op") == "listen_latest"
                and operation.get("event") == "pointer_move"
                for operation in runtime.latest_commit["ops"]
            )
        )
        props = _props_for_kind(runtime.latest_commit, "Box")[0]
        self.assertEqual(props["pointer_capture_axis"], "horizontal")

    def test_render_commit_contains_supported_primitives(self):
        def App():
            return Box(
                Layout(
                    Text(text="hello"),
                    Row(Text(text="tap"), TextInput(hint="name")),
                    Path(d="M0,0 L10,10"),
                    Canvas(
                        view_box=[0, 0, 18, 18],
                        draw=[
                            {
                                "kind": "round_rect",
                                "x": 1,
                                "y": 1,
                                "width": 16,
                                "height": 16,
                                "radius": 2,
                                "stroke": "#000000",
                                "stroke_width": 2,
                            }
                        ],
                    ),
                    Image(source="sample"),
                    Box(width=40, height=2, background_color="#E0E0E0"),
                    orientation="vertical",
                ),
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        kinds = [
            op["kind"]
            for op in transport.latest["ops"]
            if op.get("op") == "create"
        ]
        self.assertEqual(
            kinds,
            [
                "Box",
                "Layout",
                "Text",
                "Layout",
                "Text",
                "TextInput",
                "Path",
                "Canvas",
                "Image",
                "Box",
            ],
        )

    def test_layout_orientation_is_required(self):
        def App():
            return Layout(Text(text="hello"), orientation="horizontal")

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        layout_props = _props_for_kind(transport.latest, "Layout")
        self.assertEqual(layout_props[0].get("orientation"), "horizontal")

    def test_layout_alignment_props_are_serialized(self):
        def App():
            return Row(
                Text(text="hello"),
                align_items="center",
                justify_content="end",
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        layout_props = _props_for_kind(transport.latest, "Layout")
        self.assertEqual(layout_props[0].get("orientation"), "horizontal")
        self.assertEqual(layout_props[0].get("align_items"), "center")
        self.assertEqual(layout_props[0].get("justify_content"), "end")

    def test_lp_weight_props_are_serialized(self):
        def App():
            return Layout(
                Text(text="first"),
                Text(text="fills remaining", lp_weight=1.0),
                orientation="vertical",
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        text_props = _props_for_kind(runtime.latest_commit, "Text")
        self.assertEqual(text_props[1].get("text"), "fills remaining")
        self.assertEqual(text_props[1].get("lp_weight"), 1.0)

    def test_scroll_wraps_multiple_children(self):
        def App():
            return Scroll(Text(text="one"), Text(text="two"))

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        kinds = [
            op["kind"]
            for op in runtime.latest_commit["ops"]
            if op.get("op") == "create"
        ]
        self.assertEqual(kinds, ["Scroll", "Layout", "Text", "Text"])

    def test_identity_change_replaces_subtree_without_error_commit(self):
        def App():
            show_box = state(False)

            if show_box.value:
                return Box(Text(text="new"), key="root")
            return Text(
                text="old",
                key="root",
                on_click=lambda event: show_box.set(True),
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        listener = _listeners(runtime.latest_commit, "click")[0]
        dispatch_native_event(runtime, listener)

        ops = runtime.latest_commit["ops"]
        self.assertNotIn("clear", [op.get("op") for op in ops])
        self.assertNotIn("Error:", str(ops))
        self.assertIn({"op": "create", "id": 2, "kind": "Box"}, ops)

    def test_event_handler_id_is_stable_across_rerenders(self):
        def App():
            clicks = state(0)

            return Layout(
                Text(
                    text="Increment",
                    on_click=lambda: clicks.set(clicks.value + 1),
                ),
                Text(text=f"Clicks: {clicks.value}"),
                orientation="vertical",
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        listener = _listeners(runtime.latest_commit, "click")[0]
        dispatch_native_event(runtime, listener)

        dispatch_native_event(runtime, listener, seq=2)

        self.assertEqual(
            _set_props(runtime.latest_commit, "text")[0],
            {"op": "set_prop", "id": 3, "name": "text", "value": "Clicks: 2"},
        )

    def test_single_event_with_multiple_state_updates_emits_one_commit(self):
        def App():
            first = state(0)
            second = state(0)

            def update_both(event):
                first.set(1)
                second.set(1)

            return Text(text=f"{first.value}/{second.value}", on_click=update_both)

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        listener = _listeners(runtime.latest_commit, "click")[0]
        dispatch_native_event(runtime, listener)

        self.assertEqual(len(transport.messages), 2)
        self.assertEqual(
            runtime.latest_commit["ops"],
            [{"op": "set_prop", "id": 1, "name": "text", "value": "1/1"}],
        )

    def test_dispatch_events_batches_multiple_events_into_one_commit(self):
        def App():
            clicks = state(0)
            return Text(
                text=f"Clicks: {clicks.value}",
                on_click=lambda event: clicks.set(clicks.value + 1),
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        listener = _listeners(runtime.latest_commit, "click")[0]
        event = {
            "type": "event",
            "target": listener["id"],
            "event": "click",
            "handler": listener["handler"],
            "payload": {},
        }
        runtime.dispatch_events([{**event, "seq": 1}, {**event, "seq": 2}])

        self.assertEqual(len(transport.messages), 2)
        self.assertEqual(
            runtime.latest_commit["ops"],
            [{"op": "set_prop", "id": 1, "name": "text", "value": "Clicks: 2"}],
        )

    def test_pointer_event_payload_reaches_python_unchanged(self):
        received: list[tuple[str, float, float, int]] = []

        def record(event):
            received.append(
                (
                    event.name,
                    event.get("x"),
                    event.get("down_x"),
                    event.get("pointer_id"),
                )
            )

        runtime = Runtime(
            lambda: Box(
                on_pointer_down=record,
                on_pointer_move=record,
                on_pointer_up=record,
                on_pointer_cancel=record,
            ),
            transport=MemoryTransport(),
        )
        runtime.mount()

        listeners = {
            event: _listeners(runtime.latest_commit, event)[0]
            for event in {
                "pointer_down",
                "pointer_move",
                "pointer_up",
                "pointer_cancel",
            }
        }
        listener = listeners["pointer_move"]
        dispatch_native_event(
            runtime,
            listener,
            event="pointer_move",
            payload={
                "x": 72.5,
                "y": 8.0,
                "down_x": 24.0,
                "down_y": 8.0,
                "pointer_id": 3,
            },
        )

        self.assertEqual(received, [("pointer_move", 72.5, 24.0, 3)])

    def test_animate_queues_animation_op_from_event_handler(self):
        def App():
            return Text(
                text="Fade",
                on_click=lambda event: animate(event.target, "alpha", to=0.25),
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        listener = _listeners(runtime.latest_commit, "click")[0]
        dispatch_native_event(runtime, listener)

        self.assertEqual(
            runtime.latest_commit["ops"],
            [
                {
                    "op": "motion_set_target",
                    "animation_id": 1,
                    "slot_key": "view:1:prop:opacity",
                    "node_id": 1,
                    "property": "opacity",
                    "spec_type": "tween",
                    "targets": [0.25],
                    "duration_ms": 300,
                    "easing": "ease_out",
                    "retarget": "restart",
                }
            ],
        )

    def test_keyframe_animation_uses_the_live_value_without_an_explicit_start(self):
        def App():
            return Text(
                text="Press",
                on_click=lambda event: animate(
                    event.target,
                    "scale_x",
                    to=[0.94, 1.0],
                    duration=220,
                    easing="ease_in_out",
                ),
            )

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()
        listener = _listeners(runtime.latest_commit, "click")[0]
        dispatch_native_event(runtime, listener)

        # Multi-keyframe animation is one ordered native timeline.
        ops = runtime.latest_commit["ops"]
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["op"], "motion_set_target")
        self.assertEqual(ops[0]["targets"], [0.94, 1.0])
        self.assertEqual(ops[0]["easing"], "ease_in_out")
        self.assertNotIn("from_value", ops[0])

    def test_render_error_emits_standard_error_commit_and_resets_tree(self):
        def App():
            raise RuntimeError("boom")

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        self.assertEqual(
            runtime.latest_commit,
            {
                "type": "commit",
                "revision": 1,
                "ops": [
                    {"op": "clear", "id": 0},
                    {"op": "create", "id": 1, "kind": "Layout"},
                    {"op": "set_props", "id": 1, "props": {"orientation": "vertical"}},
                    {"op": "insert_child", "parent": 0, "child": 1, "index": 0},
                    {"op": "create", "id": 2, "kind": "Text"},
                    {"op": "set_props", "id": 2, "props": {"text": "Error: boom"}},
                    {"op": "insert_child", "parent": 1, "child": 2, "index": 0},
                ],
            },
        )
        self.assertIsNone(runtime._coordinator.accepted_root)
        self.assertEqual(runtime._coordinator.accepted_index, {})

    def test_queued_event_for_removed_node_is_ignored(self):
        def App():
            visible = state(True)
            clicks = state(0)

            if visible.value:
                return Layout(
                    Text(
                        text="Remove",
                        on_click=lambda: visible.set(False),
                    ),
                    Text(
                        text="Stale",
                        on_click=lambda: clicks.set(clicks.value + 1),
                    ),
                    Text(text=f"Clicks: {clicks.value}"),
                    orientation="vertical",
                )

            return Layout(
                Text(text=f"Clicks: {clicks.value}"),
                orientation="vertical",
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        listeners = _listeners(runtime.latest_commit, "click")
        remove_listener = listeners[0]
        stale_listener = listeners[1]

        dispatch_native_event(runtime, remove_listener)
        dispatch_native_event(runtime, stale_listener, seq=2)

        self.assertEqual(runtime.latest_commit["revision"], 2)

    def test_textinput_event_updates_state_and_rerenders(self):
        def App():
            name = state("")

            return Layout(
                Text(text=f"Hello {name.value or 'stranger'}"),
                TextInput(
                    text=name.value,
                    hint="Name",
                    on_text_change=lambda event: name.set(event.get("text")),
                ),
                orientation="vertical",
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        listener = _listeners(runtime.latest_commit, "text_change")[0]
        dispatch_native_event(
            runtime,
            listener,
            event="text_change",
            payload={"text": "Ada"},
        )

        self.assertEqual(len(transport.messages), 2)
        ops = runtime.latest_commit["ops"]
        self.assertNotIn("clear", [op.get("op") for op in ops])
        self.assertNotIn("create", [op.get("op") for op in ops])
        self.assertIn(
            {"op": "set_prop", "id": 2, "name": "text", "value": "Hello Ada"},
            ops,
        )
        self.assertNotIn(
            {"op": "set_prop", "id": 3, "name": "text", "value": "Ada"},
            ops,
        )

    def test_textinput_focus_is_controlled_from_python(self):
        def App():
            focused = state(False)
            return TextInput(
                focused=focused.value,
                blur_on_keyboard_hide=True,
                blur_on_tap_outside=True,
                blur_on_submit=True,
                on_focus_change=lambda event: focused.set(event.get("has_focus")),
            )

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()

        props = _props_for_kind(runtime.latest_commit, "TextInput")[0]
        self.assertEqual(
            {
                name: props[name]
                for name in {
                    "focused", "blur_on_keyboard_hide", "blur_on_tap_outside",
                    "blur_on_submit",
                }
            },
            {
                "focused": False,
                "blur_on_keyboard_hide": True,
                "blur_on_tap_outside": True,
                "blur_on_submit": True,
            },
        )

        listener = _listeners(runtime.latest_commit, "focus_change")[0]
        dispatch_native_event(
            runtime,
            listener,
            event="focus_change",
            payload={"has_focus": True},
        )
        # SCHED-02: the focus_change acknowledgement suppresses the
        # focused=True echo because native already holds that value.
        # The state change (focused=True) matches the acknowledged value,
        # so no set_prop is emitted for the echo.
        # But the TextInput was already created with focused=False, so
        # we check that no redundant set_prop is in the ops.
        focused_sets = [
            op for op in runtime.latest_commit["ops"]
            if op.get("op") == "set_prop"
            and op.get("id") == listener["id"]
            and op.get("name") == "focused"
        ]
        self.assertEqual(len(focused_sets), 0,
                         "focus_change acknowledgement should suppress focused echo")

    def test_textinput_focus_props_are_typed_and_input_only(self):
        invalid = Runtime(lambda: TextInput(focused="yes"), transport=MemoryTransport())
        invalid.mount()
        self.assertIn("focused must be bool", str(invalid.latest_commit))

        unsupported = Runtime(lambda: Text(text="No", focused=True), transport=MemoryTransport())
        unsupported.mount()
        self.assertIn("Unsupported prop 'focused' for Text", str(unsupported.latest_commit))

    def test_button_event_can_call_zero_arg_handler(self):
        def App():
            clicks = state(0)

            return Layout(
                Text(
                    text="Increment",
                    on_click=lambda: clicks.set(clicks.value + 1),
                ),
                Text(text=f"Clicks: {clicks.value}"),
                orientation="vertical",
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        listener = _listeners(runtime.latest_commit, "click")[0]
        dispatch_native_event(runtime, listener)

        self.assertEqual(
            _set_props(runtime.latest_commit, "text")[0],
            {"op": "set_prop", "id": 3, "name": "text", "value": "Clicks: 1"},
        )

    def test_path_data_is_compiled_before_it_reaches_android(self):
        def App():
            return Path(d="M0 0 10 10 L20 -0 Z")

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()

        commands = _props_for_kind(runtime.latest_commit, "Path")[0]["commands"]
        # Commands are frozen (tuple of FrozenMap with tuple values) after lowering.
        self.assertEqual(len(commands), 4)
        self.assertEqual(dict(commands[0]), {"cmd": "M", "values": (0.0, 0.0)})
        self.assertEqual(dict(commands[1]), {"cmd": "L", "values": (10.0, 10.0)})
        self.assertEqual(dict(commands[2]), {"cmd": "L", "values": (20.0, -0.0)})
        self.assertEqual(dict(commands[3]), {"cmd": "Z", "values": ()})

    def test_canvas_path_data_is_compiled_before_it_reaches_android(self):
        def App():
            return Canvas(draw=[{"kind": "path", "d": "M0 0 L10 10"}])

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()

        draw = _props_for_kind(runtime.latest_commit, "Canvas")[0]["draw"]
        self.assertNotIn("d", draw[0])
        # Commands are frozen after lowering: FrozenMap with tuple values.
        self.assertEqual(dict(draw[0]["commands"][1]), {"cmd": "L", "values": (10.0, 10.0)})

    def test_invalid_path_is_rejected_before_rendering(self):
        with self.assertRaisesRegex(ValueError, "incomplete coordinates"):
            Path(d="M 1")

    def test_conditional_state_call_emits_error_commit(self):
        def App():
            enabled = state(True)
            if enabled.value:
                state("conditional")
            return Text(text="toggle", on_click=lambda _: enabled.set(False))

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()
        listener = _listeners(runtime.latest_commit, "click")[0]
        runtime.dispatch_event(
            {
                "type": "event",
                "target": listener["id"],
                "event": "click",
                "handler": listener["handler"],
                "payload": {},
            }
        )

        # RE-1: Render errors with accepted UI preserve the tree.
        self.assertIsNotNone(runtime._coordinator.accepted_root,
                             "Tree must be preserved after handler-triggered render error")
        self.assertIsNotNone(runtime._last_error,
                             "Error should be recorded")
        self.assertIn("conditional or reordered", runtime._last_error)

    def test_state_is_rejected_from_event_handlers(self):
        def App():
            return Text(text="bad", on_click=lambda _: state(0))

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()
        listener = _listeners(runtime.latest_commit, "click")[0]
        runtime.dispatch_event(
            {
                "type": "event",
                "target": listener["id"],
                "event": "click",
                "handler": listener["handler"],
                "payload": {},
            }
        )

        # RE-1: Handler error with accepted UI preserves the tree.
        self.assertIsNotNone(runtime._coordinator.accepted_root,
                             "Tree must survive handler error with accepted UI")
        self.assertIsNotNone(runtime._last_error,
                             "Error should be recorded")
        self.assertIn("only be used while rendering", runtime._last_error)

    def test_event_handler_error_resets_python_tree(self):
        def App():
            def fail(event):
                raise RuntimeError("handler boom")

            return Text(text="fail", on_click=fail)

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()
        listener = _listeners(runtime.latest_commit, "click")[0]
        runtime.dispatch_event(
            {
                "type": "event",
                "target": listener["id"],
                "event": "click",
                "handler": listener["handler"],
                "payload": {},
            }
        )

        # RE-1: Handler error with accepted UI preserves the tree.
        self.assertIsNotNone(runtime._coordinator.accepted_root,
                             "Tree must survive handler error with accepted UI")
        self.assertIsNotNone(runtime._last_error,
                             "Error should be recorded")
        self.assertIn("handler boom", runtime._last_error)

    def test_duplicate_and_unhashable_keys_emit_error_commit(self):
        # Duplicate keys: should be caught by Runtime during validation.
        dup_children = (Text(text="a", key="same"), Text(text="b", key="same"))
        runtime = Runtime(lambda: Column(*dup_children), transport=MemoryTransport())
        runtime.mount()
        self.assertIsNone(runtime._coordinator.accepted_root)
        self.assertIn("Error:", str(runtime.latest_commit))

        # Unhashable keys: now rejected at Element construction (MODEL-02).
        with self.assertRaises(TypeError):
            Text(text="a", key=[])

    def test_non_finite_props_are_rejected_at_element_creation(self):
        with self.assertRaisesRegex(TypeError, "native bridge"):
            Text(text="bad", width=float("nan"))
        with self.assertRaises(ValueError):
            validate_message({
                "type": "commit", "revision": 1,
                "ops": [{
                    "op": "set_prop", "id": 1, "name": "opacity",
                    "value": float("inf"),
                }],
            })

    def test_unknown_direct_prop_emits_error_commit(self):
        runtime = Runtime(
            lambda: Text(text="bad", unsupported_prop=True),
            transport=MemoryTransport(),
        )
        runtime.mount()

        self.assertIsNone(runtime._coordinator.accepted_root)
        self.assertIn("Unsupported prop", str(runtime.latest_commit))

    def test_container_overflow_is_transported_and_validated(self):
        runtime = Runtime(
            lambda: Column(Text(text="shadow"), overflow="visible"),
            transport=MemoryTransport(),
        )
        runtime.mount()

        self.assertEqual(
            _props_for_kind(runtime.latest_commit, "Layout")[0]["overflow"],
            "visible",
        )

        defaults = Runtime(
            lambda: Column(Text(text="shadow")),
            transport=MemoryTransport(),
        )
        defaults.mount()
        self.assertEqual(
            _props_for_kind(defaults.latest_commit, "Layout")[0]["overflow"],
            "visible",
        )

        viewport = Runtime(
            lambda: Scroll(Text(text="content")),
            transport=MemoryTransport(),
        )
        viewport.mount()
        self.assertEqual(
            _props_for_kind(viewport.latest_commit, "Scroll")[0]["overflow"],
            "hidden",
        )

        invalid = Runtime(
            lambda: Box(overflow="scroll"),
            transport=MemoryTransport(),
        )
        invalid.mount()
        self.assertIsNone(invalid._coordinator.accepted_root)
        self.assertIn("overflow must be", str(invalid.latest_commit))

        leaf = Runtime(
            lambda: Text(text="bad", overflow="visible"),
            transport=MemoryTransport(),
        )
        leaf.mount()
        self.assertIsNone(leaf._coordinator.accepted_root)
        self.assertIn("Unsupported prop", str(leaf.latest_commit))


if __name__ == "__main__":
    unittest.main()
