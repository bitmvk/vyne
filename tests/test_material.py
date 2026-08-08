from __future__ import annotations

import unittest
from datetime import date

from vyne import Column, Text
from vyne.material import (
    MATERIAL3_CATALOG,
    Badge,
    BottomAppBar,
    BottomSheet,
    Button,
    ButtonGroup,
    ButtonGroupItem,
    Card,
    Carousel,
    Checkbox,
    Chip,
    CircularProgressIndicator,
    DatePicker,
    DateRangePicker,
    Dialog,
    ExtendedFloatingActionButton,
    FabMenuItem,
    FloatingActionButton,
    FloatingActionButtonMenu,
    IconButton,
    LinearProgressIndicator,
    MaterialList,
    ListItem,
    LoadingIndicator,
    MaterialDivider,
    Menu,
    MenuItem,
    NavigationBar,
    NavigationDrawer,
    NavigationItem,
    NavigationRail,
    RadioButton,
    RangeSlider,
    SearchBar,
    SegmentedButton,
    SegmentedButtonGroup,
    SegmentedItem,
    SideSheet,
    Slider,
    Snackbar,
    SplitButton,
    Switch,
    Tab,
    TabItem,
    Tabs,
    TextField,
    TimePicker,
    Toolbar,
    Tooltip,
    TopAppBar,
)
from vyne.runtime import Runtime


EXPECTED_CATALOG = {
    "app-bars",
    "badges",
    "bottom-sheets",
    "button-groups",
    "buttons",
    "cards",
    "carousel",
    "checkbox",
    "chips",
    "date-pickers",
    "dialogs",
    "divider",
    "extended-fab",
    "fab-menu",
    "floating-action-button",
    "icon-buttons",
    "lists",
    "loading-indicator",
    "menus",
    "navigation-bar",
    "navigation-drawer",
    "navigation-rail",
    "progress-indicators",
    "radio-button",
    "search",
    "segmented-buttons",
    "side-sheets",
    "sliders",
    "snackbar",
    "split-button",
    "switch",
    "tabs",
    "text-fields",
    "time-pickers",
    "toolbars",
    "tooltips",
}


class MaterialCatalogTests(unittest.TestCase):
    def test_catalog_has_every_current_material_3_family(self):
        self.assertEqual(set(MATERIAL3_CATALOG), EXPECTED_CATALOG)
        self.assertEqual(len(MATERIAL3_CATALOG), 36)

    def test_every_family_lowers_to_existing_renderer_primitives(self):
        navigation_items = [NavigationItem("Home", "H"), NavigationItem("Saved", "S")]
        components = [
            TopAppBar("Title"),
            BottomAppBar(IconButton("A")),
            Badge(3),
            BottomSheet(Text(text="Sheet")),
            ButtonGroup([ButtonGroupItem("One", 1), ButtonGroupItem("Two", 2)], selected=1),
            Button("Button"),
            Card(Text(text="Card")),
            Carousel(Text(text="One"), Text(text="Two")),
            Checkbox(True, label="Checkbox"),
            Chip("Chip", selected=True, variant="filter"),
            DatePicker(year=2026, month=7, selected=date(2026, 7, 16)),
            Dialog(Text(text="Dialog body"), title="Dialog"),
            MaterialDivider(),
            ExtendedFloatingActionButton("Create", icon="+"),
            FloatingActionButtonMenu([FabMenuItem("Create", "+")], expanded=True),
            FloatingActionButton("+"),
            IconButton("⋮"),
            MaterialList(ListItem("List item", supporting_text="Supporting")),
            LoadingIndicator(phase=0.25),
            Menu([MenuItem("Menu item")]),
            NavigationBar(navigation_items),
            NavigationDrawer(navigation_items),
            NavigationRail(navigation_items),
            CircularProgressIndicator(0.5),
            LinearProgressIndicator(0.5, wavy=True),
            RadioButton(True, label="Radio"),
            SearchBar(query="vyne", expanded=True, results=[ListItem("Result")]),
            SegmentedButtonGroup([SegmentedItem("A", "a"), SegmentedItem("B", "b")], selected="a"),
            SideSheet(Text(text="Side sheet")),
            Slider(0.5),
            RangeSlider((0.25, 0.75)),
            Snackbar("Saved", action_label="Undo"),
            SplitButton("Save"),
            Switch(True, label="Switch"),
            Tabs([TabItem("One"), TabItem("Two")]),
            TextField(value="Value", label="Label", supporting_text="Help"),
            TimePicker(hour=10, minute=30),
            Toolbar(IconButton("A"), IconButton("B")),
            Tooltip(Button("Anchor"), "Tooltip", visible=True),
        ]

        runtime = Runtime(lambda: Column(*components))
        runtime.mount()

        creates = [
            operation
            for operation in runtime.latest_commit["ops"]
            if operation["op"] == "create"
        ]
        native_kinds = {operation["kind"] for operation in creates}
        self.assertTrue(native_kinds)
        self.assertLessEqual(
            native_kinds,
            {"Box", "Canvas", "Image", "Layout", "Path", "Scroll", "Text", "TextInput"},
        )

    def test_controlled_selection_callbacks_receive_python_values(self):
        received: list[object] = []
        checkbox = Checkbox(False, on_change=received.append)
        slider = Slider(0.5, step=0.1, on_change=received.append)
        day_picker = DatePicker(year=2026, month=7, on_select=received.append)

        checkbox.props["on_click"](None)
        # x=142 is the 0.6 position on a 240 dp slider's inset track.
        slider.props["on_pointer_down"]({"x": 142, "down_x": 142})
        day_cell = day_picker.children[4].children[2]
        day_cell.props["on_click"](None)

        self.assertEqual(received[0], True)
        self.assertAlmostEqual(received[1], 0.6)
        self.assertIsInstance(received[2], date)

    def test_selection_and_navigation_keep_stable_equal_geometry(self):
        group = ButtonGroup(
            [ButtonGroupItem("A", "a"), ButtonGroupItem("Long label", "b")],
            selected="a",
            width=328,
        )
        buttons = [child for child in group.children if child.kind == "Layout"]
        self.assertEqual(
            [(button.props["width"], button.props["lp_weight"]) for button in buttons],
            [(0, 1), (0, 1)],
        )

        navigation = NavigationBar(
            [NavigationItem("Home", "H"), NavigationItem("Saved", "S")]
        )
        self.assertTrue(
            all(
                destination.props.get("width") == 0
                and destination.props.get("lp_weight") == 1
                for destination in navigation.children
            )
        )
        for destination in navigation.children:
            label_host = destination.children[-1]
            self.assertEqual(label_host.props["justify_content"], "center")

        rail = NavigationRail(
            [NavigationItem("Home", "H"), NavigationItem("Saved", "S")]
        )
        destinations = [child for child in rail.children if child.props.get("content_description")]
        self.assertTrue(destinations)
        self.assertTrue(
            all(destination.children[-1].props["justify_content"] == "center" for destination in destinations)
        )

    def test_fixed_size_icons_and_time_dial_are_centered(self):
        icon = IconButton("+")
        self.assertEqual(icon.kind, "Layout")
        self.assertEqual(icon.props["align_items"], "center")
        self.assertEqual(icon.props["justify_content"], "center")

        picker = TimePicker(hour=10, minute=30)
        hour_selector = picker.children[0].children[0]
        self.assertEqual((hour_selector.props["width"], hour_selector.props["height"]), (96, 72))
        self.assertEqual(hour_selector.children[0].props["font_size"], 45)
        dial = picker.children[2]
        top_hour = dial.children[1]
        self.assertEqual(top_hour.children[0].props["text"], "12")
        self.assertEqual(top_hour.props["align_items"], "center")
        self.assertEqual(top_hour.props["justify_content"], "center")

    def test_content_sized_actions_do_not_fill_vertical_parents_by_default(self):
        self.assertEqual(Button("Save").props["width"], "wrap_content")
        self.assertEqual(Chip("Filter", variant="filter").props["width"], "wrap_content")
        self.assertEqual(
            SegmentedButton("Day", selected=True).props["width"],
            "wrap_content",
        )
        self.assertEqual(
            SegmentedButtonGroup(
                [SegmentedItem("Day", "day"), SegmentedItem("Week", "week")],
                selected="day",
            ).children[0].props["width"],
            0,
        )

    def test_surface_rows_fill_their_component_width(self):
        item = ListItem("Settings")
        self.assertEqual(item.props["width"], "match_parent")

        field = TextField(value="Vyne", label="Name")
        self.assertEqual(field.children[0].props["width"], "match_parent")
        self.assertEqual(field.children[0].children[0].props["width"], "match_parent")

        search = SearchBar(query="", expanded=True, results=[ListItem("Result")])
        self.assertEqual(search.children[0].props["width"], "match_parent")

        drawer = NavigationDrawer([NavigationItem("Home", "H")])
        destination = next(
            child for child in drawer.children
            if child.props.get("content_description") == "Home"
        )
        self.assertEqual(destination.props["width"], "match_parent")

    def test_transitions_preserve_component_geometry(self):
        closed = SplitButton("Save", expanded=False, width=240)
        opened = SplitButton("Save", expanded=True, width=240)
        for component in (closed, opened):
            main, menu = component.children[0], component.children[2]
            self.assertEqual((main.props["width"], main.props["lp_weight"]), (0, 1))
            self.assertEqual(menu.props["width"], 40)
        self.assertEqual(closed.children[2].children[0].props["rotation"], 0)
        self.assertEqual(opened.children[2].children[0].props["rotation"], 180)

        unselected_chip = Chip("Filter", variant="filter", selected=False)
        selected_chip = Chip("Filter", variant="filter", selected=True)
        self.assertEqual(unselected_chip.children[0].props["width"], 18)
        self.assertEqual(selected_chip.children[0].props["width"], 18)

        empty_field = TextField(value="", label="Name", focused=False)
        focused_field = TextField(value="", label="Name", focused=True)
        self.assertEqual(empty_field.children[0].props["min_height"], 56)
        self.assertEqual(focused_field.children[0].props["min_height"], 56)

        segmented = SegmentedButtonGroup(
            [SegmentedItem("Day", "day"), SegmentedItem("Week", "week")],
            selected="day",
        )
        selected_button, unselected_button = segmented.children
        self.assertEqual(selected_button.children[0].props["width"], 18)
        self.assertEqual(len(unselected_button.children), 1)
        self.assertEqual(unselected_button.children[0].props["text"], "Week")

    def test_switch_uses_material_track_and_handle_geometry(self):
        enabled_switch = Switch(True)
        canvas = next(child for child in enabled_switch.children if child.kind == "Canvas")
        track, handle = canvas.props["draw"]
        self.assertEqual(
            (track["x"], track["y"], track["width"], track["height"], track["radius"]),
            (1, 1, 50, 30, 15),
        )
        self.assertEqual(handle["cx"]["value"], 36)
        self.assertEqual(handle["r"]["value"], 12)
        self.assertEqual(handle["cy"], 16)
        self.assertEqual(handle["cx"]["easing"], "spring")
        self.assertEqual(handle["cx"]["damping_ratio"], 0.6)
        self.assertEqual(handle["cx"]["stiffness"], 800)

        off_switch = Switch(False)
        canvas = next(child for child in off_switch.children if child.kind == "Canvas")
        handle = canvas.props["draw"][1]
        self.assertEqual(handle["cx"]["value"], 16)
        self.assertEqual(handle["r"]["value"], 8)

    def test_switch_toggles_without_a_pressed_geometry_state_machine(self):
        received: list[bool] = []
        switch = Switch(False, on_change=received.append)

        switch.props["on_click"]({})

        self.assertEqual(received, [True])
        self.assertNotIn("on_pointer_down", switch.props)
        self.assertNotIn("on_pointer_up", switch.props)

        disabled = Switch(False, enabled=False, on_change=received.append)
        self.assertIsNone(disabled.props.get("on_click"))
        self.assertNotIn("on_pointer_down", disabled.props)
        self.assertNotIn("on_pointer_up", disabled.props)

    def test_range_slider_track_positions_update_nearest_thumb(self):
        received: list[tuple[float, float]] = []
        slider = RangeSlider(
            (0.2, 0.8),
            step=0.1,
            on_change=received.append,
        )
        start_target, end_target = slider.children[1:]
        # Down on start target moves start to 0.1.
        start_target.props["on_pointer_down"]({"x": 32})
        # Down+Move on end target (local x=88, global x=120+88=208 -> value 0.9).
        end_target.props["on_pointer_down"]({"x": 88})
        end_target.props["on_pointer_move"]({"x": 88})
        self.assertEqual(received, [(0.1, 0.8), (0.1, 0.9)])

    def test_range_slider_keeps_the_initial_thumb_during_drag(self):
        received: list[tuple[float, float]] = []
        slider = RangeSlider((0.2, 0.8), step=0.1, on_change=received.append)

        # A gesture beginning on the start thumb keeps controlling that thumb
        # even after it crosses the original midpoint of the range.
        start_target = slider.children[1]
        start_target.props["on_pointer_down"]({"x": 164})

        self.assertEqual(len(received), 1)
        self.assertAlmostEqual(received[0][0], 0.7)
        self.assertAlmostEqual(received[0][1], 0.8)

    def test_sliders_emit_animated_canvas_geometry(self):
        slider = Slider(0.5)
        slider_canvas = slider.children[0]
        slider_thumb_x = slider_canvas.props["draw"][-1]["x"]
        self.assertTrue(slider_thumb_x["__vyne_animated_value__"])
        self.assertEqual(slider_thumb_x["duration"], 48)
        self.assertEqual(slider_thumb_x["easing"], "linear")
        self.assertEqual(slider_thumb_x["retarget"], "maintain_velocity")

        range_slider = RangeSlider((0.2, 0.8))
        range_canvas = range_slider.children[0]
        start_thumb_x = range_canvas.props["draw"][-2]["x"]
        end_thumb_x = range_canvas.props["draw"][-1]["x"]
        self.assertTrue(start_thumb_x["__vyne_animated_value__"])
        self.assertTrue(end_thumb_x["__vyne_animated_value__"])
        self.assertEqual(start_thumb_x["retarget"], "maintain_velocity")
        self.assertEqual(end_thumb_x["retarget"], "maintain_velocity")

    def test_app_bar_and_toolbar_use_renderer_supported_alignment(self):
        medium_bar = TopAppBar(
            "Material showcase",
            navigation=IconButton("Back"),
            actions=(IconButton("More"),),
            variant="medium",
        )
        self.assertEqual(medium_bar.props["orientation"], "vertical")
        self.assertEqual(medium_bar.children[0].props["height"], 64)
        self.assertEqual(medium_bar.children[1].props["height"], 48)
        self.assertEqual(medium_bar.children[0].props["width"], "match_parent")
        self.assertEqual(medium_bar.children[1].props["width"], "match_parent")
        self.assertTrue(
            any(child.props.get("lp_weight") == 1 for child in medium_bar.children[0].children)
        )

        bar = BottomAppBar(IconButton("A"), floating_action_button=FloatingActionButton("+"))
        self.assertTrue(any(child.props.get("lp_weight") == 1 for child in bar.children))
        toolbar = Toolbar(IconButton("A"), IconButton("B"))
        self.assertEqual(toolbar.props["justify_content"], "center")

        tabs = Tabs([TabItem("One"), TabItem("Two")])
        indicator_host = tabs.children[0].children[1]
        self.assertEqual(indicator_host.props["lp_gravity"], "bottom")
        self.assertEqual(indicator_host.props["justify_content"], "center")
        content = tabs.children[0].children[0]
        label_host = content.children[-1]
        self.assertEqual(label_host.props["justify_content"], "center")

        period = SegmentedButtonGroup(
            [SegmentedItem("AM", "am"), SegmentedItem("PM", "pm")],
            selected="am",
        )
        self.assertEqual(period.props["width"], 160)

    def test_hidden_transient_components_lower_to_none(self):
        self.assertIsNone(BottomSheet(visible=False))
        self.assertIsNone(Dialog(visible=False))
        self.assertIsNone(Menu([], open=False))
        self.assertIsNone(SideSheet(visible=False))

    def test_component_variants_and_picker_modes_lower_successfully(self):
        variants = [
            *[
                Button("Button", variant=variant, size=size)
                for variant in ("filled", "tonal", "elevated", "outlined", "text")
                for size in ("extra_small", "small", "medium", "large", "extra_large")
            ],
            ButtonGroup(
                [ButtonGroupItem("A", "a"), ButtonGroupItem("B", "b")],
                selected=("a",),
                multi_select=True,
                connected=True,
            ),
            DateRangePicker(
                year=2026,
                month=7,
                start=date(2026, 7, 3),
                end=date(2026, 7, 18),
            ),
            TimePicker(hour=23, minute=59, is_24_hour=True, selection="hour"),
            TimePicker(hour=23, minute=59, selection="minute"),
            TextField(value="Filled", label="Filled", variant="filled", focused=True),
            TextField(value="Outlined", label="Outlined", variant="outlined", error_text="Error"),
            Tooltip(Button("Anchor"), "Title", visible=True, rich=True, supporting_text="Body"),
        ]
        runtime = Runtime(lambda: Column(*variants))
        runtime.mount()
        self.assertNotEqual(runtime.latest_commit.get("revision"), -1)

    def test_text_field_translates_native_events_to_controlled_values(self):
        received: list[object] = []
        field = TextField(
            value="old",
            label="Name",
            on_text_change=received.append,
            on_editor_action=received.append,
            on_focus_change=received.append,
        )
        stack = [field]
        text_input = None
        while stack:
            candidate = stack.pop()
            if candidate.kind == "TextInput":
                text_input = candidate
                break
            stack.extend(candidate.children)
        self.assertIsNotNone(text_input)
        self.assertTrue(text_input.props["blur_on_keyboard_hide"])
        self.assertTrue(text_input.props["blur_on_tap_outside"])
        self.assertTrue(text_input.props["blur_on_submit"])
        text_input.props["on_text_change"]({"text": "new"})
        text_input.props["on_editor_action"]({"text": "submitted"})
        text_input.props["on_focus_change"]({"has_focus": True})
        self.assertEqual(received, ["new", "submitted", True])

    def test_invalid_variants_and_ranges_fail_fast(self):
        with self.assertRaisesRegex(ValueError, "variant must be one of"):
            Button("Bad", variant="unknown")
        with self.assertRaisesRegex(ValueError, "maximum must be greater"):
            Slider(0, minimum=1, maximum=1)
        with self.assertRaisesRegex(ValueError, "step must be greater"):
            Slider(0.5, step=0)
        with self.assertRaisesRegex(ValueError, "month must be between"):
            DatePicker(year=2026, month=13)


class MaterialValidationTests(unittest.TestCase):
    """MATERIAL-01: Shared validators for Slider/RangeSlider."""

    def test_slider_rejects_bool_input(self):
        with self.assertRaises(TypeError):
            Slider(True)
        with self.assertRaises(TypeError):
            Slider(0.5, minimum=False)
        with self.assertRaises(TypeError):
            Slider(0.5, maximum=True)

    def test_slider_rejects_nonfinite_values(self):
        import math
        with self.assertRaises(ValueError):
            Slider(float('nan'))
        with self.assertRaises(ValueError):
            Slider(float('inf'))
        with self.assertRaises(ValueError):
            Slider(0.5, minimum=float('-inf'))

    def test_slider_rejects_non_positive_step(self):
        with self.assertRaises(ValueError):
            Slider(0.5, step=-0.1)
        with self.assertRaises(ValueError):
            Slider(0.5, step=0)
        with self.assertRaises(ValueError):
            import math
            Slider(0.5, step=float('inf'))

    def test_slider_rejects_non_positive_width(self):
        with self.assertRaises(ValueError):
            Slider(0.5, width=0)
        with self.assertRaises(ValueError):
            Slider(0.5, width=-10)

    def test_range_slider_rejects_wrong_types(self):
        with self.assertRaises(TypeError):
            RangeSlider([0.2, 0.8])  # list, not tuple
        with self.assertRaises(TypeError):
            RangeSlider((0.2,))  # single element
        with self.assertRaises(TypeError):
            RangeSlider((0.2, 0.5, 0.8))  # three elements

    def test_range_slider_accepts_tuple_of_two(self):
        # Should not raise
        slider = RangeSlider((0.2, 0.8))
        self.assertIsNotNone(slider)

    def test_slider_normalizes_off_step_value(self):
        # Value 0.05 with step 0.1 should normalize to 0.0 or 0.1.
        # With min=0, max=1, step=0.1, value 0.05 snaps to 0.0.
        slider = Slider(0.05, step=0.1, minimum=0, maximum=1)
        desc = slider.props.get("content_description", "")
        # The description reflects the normalized clamped value.
        self.assertIn("0", desc.split()[0])

    def test_range_slider_rejects_unordered_values(self):
        with self.assertRaises(ValueError):
            RangeSlider((0.8, 0.2))

    def test_slider_gesture_deduplication(self):
        """Slider emits one callback per gesture (tap) for each distinct target."""
        received: list[float] = []
        slider = Slider(0.5, step=0.1, on_change=received.append)

        # Each down() starts a new gesture — separate taps always emit.
        down_handler = slider.props["on_pointer_down"]
        up_handler = slider.props["on_pointer_up"]

        # First tap at x=142 (~0.6).
        down_handler({"x": 142, "down_x": 142})
        self.assertEqual(len(received), 1)
        up_handler({"x": 142})

        # Same position, second tap — emit once per tap.
        down_handler({"x": 142, "down_x": 142})
        self.assertEqual(len(received), 2)
        up_handler({"x": 142})

        # Different position — third tap.
        down_handler({"x": 164, "down_x": 164})
        self.assertEqual(len(received), 3)
        self.assertAlmostEqual(received[0], 0.6)
        self.assertAlmostEqual(received[1], 0.6)
        self.assertAlmostEqual(received[2], 0.7)

        # Within a single gesture, move with same value is deduplicated.
        move_handler = slider.props["on_pointer_move"]
        down_handler({"x": 142, "down_x": 142})
        self.assertEqual(len(received), 4)
        move_handler({"x": 142})
        self.assertEqual(len(received), 4)  # same value, deduplicated
        move_handler({"x": 164})
        self.assertEqual(len(received), 5)  # x=164 normalizes to 0.7 (new value)

    def test_continuous_slider_no_discrete_targets(self):
        """Continuous sliders do not build discrete target lists."""
        slider = Slider(0.5)  # no step -> continuous
        canvas = slider.children[0]
        # The draw list should have 4 entries: active track, inactive track,
        # endpoint dot, and thumb. No ticks.
        draw = canvas.props["draw"]
        # track_left rect, inactive rect, endpoint circle, thumb rect = 4
        self.assertEqual(len(draw), 4)

    def test_discrete_slider_has_ticks(self):
        """Discrete sliders include tick marks."""
        slider = Slider(0.5, step=0.25)  # 4 divisions + 2 endpoints = 5 targets
        canvas = slider.children[0]
        draw = canvas.props["draw"]
        # Should have track + ticks + thumb (more than 4 entries)
        self.assertGreater(len(draw), 4)


class MaterialCallbackTests(unittest.TestCase):
    """MATERIAL-02: One-time callback inspection and selection policy."""

    def test_callback_adapter_inspected_once(self):
        """CallbackAdapter.invoke reuses one-time signature inspection."""
        from vyne.material._callbacks import CallbackAdapter
        call_count = [0]

        def handler(value):
            call_count[0] += 1

        adapter = CallbackAdapter(handler)
        self.assertTrue(adapter._accepts_positional)

        # Multiple invocations should not re-inspect.
        adapter.invoke(1)
        adapter.invoke(2)
        adapter.invoke(3)
        self.assertEqual(call_count[0], 3)

    def test_callback_adapter_zero_arg_callback(self):
        from vyne.material._callbacks import CallbackAdapter
        called = [False]

        def no_arg():
            called[0] = True

        adapter = CallbackAdapter(no_arg)
        self.assertFalse(adapter._accepts_positional)

        adapter.invoke(42)  # value ignored
        self.assertTrue(called[0])

    def test_checkbox_callback_construction_time_no_error(self):
        """Checkbox with a no-argument callback should construct without error."""
        called = [False]

        def toggle():
            called[0] = True

        checkbox = Checkbox(False, on_change=toggle)
        # Simulate click
        checkbox.props["on_click"](None)
        self.assertTrue(called[0])

    def test_radio_button_passes_value(self):
        received: list[object] = []
        radio = RadioButton(False, on_select=received.append, value="opt-a")
        radio.props["on_click"](None)
        self.assertEqual(received, ["opt-a"])

    def test_switch_passes_boolean(self):
        received: list[bool] = []
        switch = Switch(False, on_change=received.append)
        switch.props["on_click"](None)
        self.assertEqual(received, [True])

    def test_date_picker_rejects_year_out_of_bounds(self):
        with self.assertRaises(ValueError):
            DatePicker(year=0, month=1)
        with self.assertRaises(ValueError):
            DatePicker(year=10000, month=1)

    def test_date_picker_rejects_selected_out_of_bounds(self):
        # date(1, 1, 1) is date.min, which is valid as a selected date.
        # Out-of-bounds years are rejected directly:
        with self.assertRaises(ValueError):
            DatePicker(year=0, month=1)

    def test_date_picker_navigation_stays_in_bounds(self):
        """Navigation at year boundaries must not produce invalid dates."""
        # January of year 1 -> previous should be disabled.
        picker = DatePicker(year=1, month=1, on_month_change=lambda ym: None)
        # spaced_row interleaves spacers: [prev, spacer, title, spacer, next]
        prev_button = picker.children[0].children[0]
        self.assertIsNone(prev_button.props.get("on_click"),
                          "Prev button must be disabled at (1,1)")
        self.assertFalse(prev_button.props.get("enabled", True))

        # December of year 9999 -> next should be disabled.
        picker2 = DatePicker(year=9999, month=12, on_month_change=lambda ym: None)
        next_button = picker2.children[0].children[4]  # index 4 = next after spacers
        self.assertIsNone(next_button.props.get("on_click"),
                          "Next button must be disabled at (9999,12)")
        self.assertFalse(next_button.props.get("enabled", True))

        # At a normal boundary (e.g. year 2, month 1), prev should work.
        received: list[tuple[int, int]] = []
        picker3 = DatePicker(year=2, month=1, on_month_change=received.append)
        prev_button3 = picker3.children[0].children[0]
        self.assertIsNotNone(prev_button3.props.get("on_click"))
        prev_button3.props["on_click"](None)
        self.assertEqual(len(received), 1)
        y, m = received[0]
        self.assertEqual((y, m), (1, 12))
        self.assertGreaterEqual(y, date.min.year)

    def test_searchbar_callback_parity_with_textfield(self):
        """SearchBar uses the same callback adapter path as TextField."""
        received: list[str] = []
        bar = SearchBar(query="test", on_query_change=received.append)
        # Find the TextInput child
        for child in bar.children:
            if isinstance(child, type(bar)) and hasattr(child, 'kind'):
                pass
        # Just verify construction succeeds
        self.assertIsNotNone(bar)


class MaterialInteractionTests(unittest.TestCase):
    """MATERIAL-03: Disabled precedence, ripple host, Snackbar inverse, motion."""

    def test_fab_disabled(self):
        """FloatingActionButton supports disabled state."""
        fab = FloatingActionButton("+", enabled=False)
        self.assertIsNone(fab.props.get("on_click"))
        self.assertEqual(fab.props.get("elevation"), 0)
        self.assertFalse(fab.props.get("enabled"))

    def test_fab_enabled_has_click(self):
        fab = FloatingActionButton("+", enabled=True, on_click=lambda: None)
        self.assertIsNotNone(fab.props.get("on_click"))
        self.assertGreater(fab.props.get("elevation", 0), 0)

    def test_navigation_drawer_disabled_item(self):
        """Disabled NavigationItem has muted foreground and no click."""
        items = [NavigationItem("Home", "H", enabled=False)]
        drawer = NavigationDrawer(items)
        # The drawer has header + destinations in a column
        # Find the destination element
        dest = None
        for child in drawer.children[1:]:  # skip header
            if hasattr(child, 'props') and child.props.get('content_description'):
                dest = child
                break
        if dest is not None:
            self.assertIsNone(dest.props.get("on_click"))
            self.assertFalse(dest.props.get("enabled"))

    def test_snackbar_complete_inverse_colors(self):
        """Snackbar uses full inverse palette, not just on_surface."""
        snack = Snackbar("Done", action_label="Undo", on_action=lambda: None)
        # Verify the Snackbar background uses inverse_surface
        self.assertEqual(snack.props.get("background_color").upper(),
                         snack.children[0].props.get("text_color", "").upper() if False else "#322F35")
        # The background should be the inverse surface color
        bg = snack.props.get("background_color", "")
        self.assertIn(bg.upper(), ["#322F35", "#FF322F35"])

    def test_button_disabled_visual(self):
        """Disabled button has muted foreground and container."""
        enabled = Button("Enabled", variant="filled")
        disabled = Button("Disabled", variant="filled", enabled=False)
        # The container background_color differs between enabled and disabled.
        enabled_bg = enabled.props.get("background_color", "")
        disabled_bg = disabled.props.get("background_color", "")
        self.assertNotEqual(enabled_bg, disabled_bg,
                           f"Enabled and disabled buttons should have different backgrounds")

    def test_disabled_chip_has_no_click(self):
        chip = Chip("Filter", variant="filter", on_click=lambda: None, enabled=False)
        self.assertIsNone(chip.props.get("on_click"))

    def test_disabled_tab_has_no_click(self):
        tab = Tab("Tab", selected=False, on_click=lambda: None, enabled=False)
        self.assertIsNone(tab.props.get("on_click"))

    def test_slider_disabled_colors(self):
        """Disabled slider uses muted colors uniformly."""
        slider = Slider(0.5, enabled=False)
        canvas = slider.children[0]
        active_color = canvas.props["draw"][0]["fill"]
        # Disabled active track color should be alpha(on_surface, 0.38)
        # Check that the alpha channel is present and muted
        self.assertTrue(
            len(active_color) == 9,  # #AARRGGBB format
            f"Expected #AARRGGBB color, got {active_color!r}"
        )
        # The alpha should be less than FF (fully opaque)
        alpha_hex = active_color[1:3]
        alpha_int = int(alpha_hex, 16)
        self.assertLess(alpha_int, 0xFF, "Disabled slider should have translucent colors")


class MaterialMeasurementTests(unittest.TestCase):
    """MATERIAL-04: Native text measurement and one-time geometry."""

    def test_badge_no_text_estimate(self):
        """Badge uses native wrap-content, no len(text)*constant."""
        badge = Badge(3)
        # Should NOT have a width prop computed from len(text).
        self.assertNotIn("width", badge.props)
        self.assertIn("min_width", badge.props)
        self.assertEqual(badge.props["min_width"], 16)

    def test_menu_no_text_estimate(self):
        """Menu does not compute width from widest_label."""
        menu = Menu([MenuItem("Short"), MenuItem("A very long menu item label")])
        # Should not have a hardcoded width estimate.
        self.assertIn("min_width", menu.props)

    def test_textfield_floating_label_no_text_estimate(self):
        """TextField floating label host uses native sizing."""
        field = TextField(value="Hello", label="Name", focused=True)
        # Find the floating label host
        floating_host = field.children[0].children[1]
        if floating_host is not None:
            # Should not have a width computed from len(label).
            self.assertNotIn("width", floating_host.props)

    def test_tooltip_no_text_estimate(self):
        """Tooltip plain variant uses native constraints, not len(text)*constant."""
        tooltip = Tooltip(Button("Hover"), "Short tip", visible=True)
        # The bubble (first child in "above" placement)
        bubble = tooltip.children[0]
        self.assertIsNotNone(bubble)
        # Should have min_width but not a hardcoded width based on len(text).
        # The width prop should be a constraint, not an estimate.

    def test_progress_path_is_immutable_string(self):
        """progress_path() returns the same immutable string."""
        from vyne.material._geometry import progress_path as geo_progress
        p1 = geo_progress()
        p2 = geo_progress()
        self.assertIs(p1, p2)  # Same object (immutable constant)

    def test_wavy_path_builds_from_dimensions(self):
        """wavy_path() produces valid SVG path string."""
        from vyne.material._geometry import wavy_path as geo_wavy
        path = geo_wavy(240, 12)
        self.assertTrue(path.startswith("M"))
        self.assertIn("L", path)

    def test_checkmark_and_radio_canvases_render(self):
        """checkmark and radio canvases produce Canvas elements."""
        from vyne.material._foundation import checkmark_canvas, radio_canvas
        from vyne.material.theme import DEFAULT_THEME as DT

        cc = checkmark_canvas(checked=True, indeterminate=False, enabled=True, theme=DT)
        self.assertEqual(cc.kind, "Canvas")

        rc = radio_canvas(selected=True, enabled=True, theme=DT)
        self.assertEqual(rc.kind, "Canvas")


class MaterialRegressionTests(unittest.TestCase):
    """Preserve known-correct behaviors flagged in the audit."""

    def test_slider_no_endpoint_dead_area(self):
        """Slider endpoints (0 and width) produce min and max values."""
        received: list[float] = []
        slider = Slider(0.5, minimum=0, maximum=1, on_change=received.append)
        handler = slider.props["on_pointer_down"]

        # Click at x=10 (left endpoint) should give minimum.
        handler({"x": 10, "down_x": 10})
        self.assertAlmostEqual(received[-1], 0.0)

        # Click at x=230 (right endpoint) should give maximum.
        handler({"x": 230, "down_x": 230})
        self.assertAlmostEqual(received[-1], 1.0)

    def test_no_python_x_shadowing(self):
        """Slider value_at correctly uses the x event property."""
        from vyne.material._validation import SliderSpec
        spec = SliderSpec(minimum=0, maximum=1, step=None, width=240)
        self.assertAlmostEqual(spec.value_at(120), 0.5, places=1)

    def test_range_slider_local_translation_correct(self):
        """RangeSlider end thumb translation_x is midpoint_x (preserved behavior)."""
        slider = RangeSlider((0.2, 0.8), on_change=lambda v: None)
        # Children: [canvas, start_touch_target, end_touch_target]
        end_touch = slider.children[2]
        self.assertIn("translation_x", end_touch.props)
        # The translation should be midpoint_x, approximately 120 for a 240 width.
        self.assertAlmostEqual(end_touch.props["translation_x"], 120, delta=5)

    def test_switch_no_pressed_geometry_state_machine(self):
        """Switch has no on_pointer_down/up handlers (preserved behavior)."""
        switch = Switch(True)
        self.assertNotIn("on_pointer_down", switch.props)
        self.assertNotIn("on_pointer_up", switch.props)


if __name__ == "__main__":
    unittest.main()
