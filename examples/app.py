"""Vyne Lab — interactive framework showcase.

The framework checkout launches this module by default with ``vyne run``.
It intentionally exercises native-frame animation, asynchronous Python
callbacks, typed styling, Canvas drawing, static and dynamic virtualized lists,
controlled inputs, and the complete public Material widget set.
"""

from __future__ import annotations

import asyncio
from datetime import date

from vyne import (
    Animated,
    AppContext,
    Box,
    Canvas,
    Column,
    CornerRadius,
    Decoration,
    List,
    Ref,
    Ripple,
    Row,
    Scroll,
    Shadow,
    Stroke,
    Text,
    animate,
    component,
    run_app,
    state,
)
from vyne_material import (
    Badge,
    Badged,
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
    ColorScheme,
    DatePicker,
    DateRangePicker,
    Dialog,
    ExtendedFloatingActionButton,
    FabMenuItem,
    FloatingActionButton,
    FloatingActionButtonMenu,
    FloatingToolbar,
    IconButton,
    LinearProgressIndicator,
    LinearWavyProgressIndicator,
    ListItem,
    LoadingIndicator,
    MaterialDivider,
    MaterialList,
    MaterialTheme,
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

THEME = MaterialTheme(
    colors=ColorScheme(
        primary="#6750E8",
        on_primary="#FFFFFF",
        primary_container="#E7DEFF",
        on_primary_container="#23105A",
        secondary="#5D5A72",
        on_secondary="#FFFFFF",
        secondary_container="#E4E1F9",
        on_secondary_container="#1A182B",
        tertiary="#A33E72",
        on_tertiary="#FFFFFF",
        tertiary_container="#FFD8E8",
        on_tertiary_container="#3D0024",
        surface="#FCF8FF",
        on_surface="#1C1B22",
        surface_variant="#E7E1EC",
        on_surface_variant="#49454F",
        surface_container_lowest="#FFFFFF",
        surface_container_low="#F7F2FA",
        surface_container="#F1ECF4",
        surface_container_high="#EBE5EE",
        surface_container_highest="#E4DFE7",
        outline="#79747E",
        outline_variant="#CAC4D0",
    )
)

COLORS = THEME.colors
PANEL_WIDTH = 296

_KEYFRAME_REF = Ref()
_ASYNC_PULSE_REF = Ref()


def _title(text: str, supporting: str):
    return Column(
        Text(
            text=text,
            font_size=26,
            line_height=32,
            text_color=COLORS.on_surface,
            include_font_padding=False,
        ),
        Text(
            text=supporting,
            font_size=14,
            line_height=20,
            text_color=COLORS.on_surface_variant,
            include_font_padding=False,
            margin_top=4,
        ),
        width="match_parent",
        margin_bottom=16,
    )


def _card(*children, tone: str = "surface", **props):
    backgrounds = {
        "surface": COLORS.surface_container_lowest,
        "soft": COLORS.primary_container,
        "dark": "#19172B",
        "rose": COLORS.tertiary_container,
    }
    return Column(
        *children,
        width="match_parent",
        padding=18,
        margin_bottom=14,
        background_color=backgrounds[tone],
        corner_radius=20,
        elevation=1 if tone == "surface" else 0,
        overflow="hidden",
        **props,
    )


def _eyebrow(text: str, *, inverse: bool = False):
    return Text(
        text=text.upper(),
        font_size=11,
        line_height=16,
        text_color="#BEB6FF" if inverse else COLORS.primary,
        include_font_padding=False,
    )


def _metric(label: str, value: str):
    return Column(
        Text(
            text=value,
            font_size=17,
            text_color=COLORS.on_surface,
            include_font_padding=False,
        ),
        Text(
            text=label,
            font_size=11,
            text_color=COLORS.on_surface_variant,
            include_font_padding=False,
            margin_top=2,
        ),
        width=0,
        lp_weight=1,
    )


@component
def MotionShowcase():
    forward = state(False)
    curve = state("ease_in_out")
    motion_status = state("Ready")
    active_handle = state(None)

    duration = 620
    timeline = Animated.Value(0.0)
    spring_x = Animated.Value(4.0)

    x = timeline.interpolate([0, 1], [4, 214])
    size = timeline.interpolate([0, 1], [42, 64])
    scale = timeline.interpolate([0, 1], [0.86, 1.18])
    opacity = timeline.interpolate([0, 1], [0.45, 1.0])
    rotation = timeline.interpolate([0, 1], [0, 330])
    tilt = timeline.interpolate([0, 1], [-18, 18])
    elevation = timeline.interpolate([0, 1], [1, 10])
    trim = timeline.interpolate([0, 1], [0.08, 1.0])
    dash = timeline.interpolate([0, 1], [0, 28])
    canvas_width = timeline.interpolate([0, 1], [56, 230])
    canvas_radius = timeline.interpolate([0, 1], [9, 22])
    canvas_opacity = timeline.interpolate([0, 1], [0.48, 0.95])
    vertical_offset = timeline.interpolate([0, 1], [0, 8])

    def reverse():
        next_forward = not forward.value
        forward.set(next_forward)
        destination = 1.0 if next_forward else 0.0
        Animated.parallel(
            [
                Animated.timing(
                    timeline,
                    to=destination,
                    duration=duration,
                    easing=curve.value,
                ),
                Animated.spring(
                    spring_x,
                    to=210 if next_forward else 4,
                    damping_ratio=0.62,
                    stiffness=240,
                ),
            ]
        ).start()

    async def keyframes_complete(event):
        motion_status.set(f"Native timeline #{event.animation_id} completed")
        await asyncio.sleep(0.22)
        motion_status.set("Async completion callback committed")

    def play_keyframes():
        motion_status.set("Four keyframes are running natively")
        active_handle.set(
            animate(
                _KEYFRAME_REF,
                x=[210, 70, 185, 0],
                duration=150,
                easing="ease_in_out",
                on_complete=keyframes_complete,
                on_cancel=lambda event: motion_status.set(
                    f"Timeline cancelled: {event.reason or 'requested'}"
                ),
            )
        )

    def cancel_keyframes():
        handle = active_handle.value
        if handle is None or handle.done:
            motion_status.set("No active timeline to cancel")
        elif handle.cancel():
            motion_status.set("Generation-safe cancellation queued")

    return Column(
        _title(
            "Motion, without Python frames",
            "Targets are committed in order; the native display clock owns every visible frame.",
        ),
        _card(
            _eyebrow("Declarative multi-property timeline", inverse=True),
            Text(
                text="One state change, ten live presentation slots",
                font_size=19,
                line_height=24,
                text_color="#FFFFFF",
                include_font_padding=False,
                margin_top=5,
            ),
            Box(
                Box(
                    Text(
                        text="V",
                        font_size=18,
                        text_color="#FFFFFF",
                        lp_gravity="center",
                    ),
                    width=size,
                    height=size,
                    translation_x=x,
                    translation_y=vertical_offset,
                    scale_x=scale,
                    scale_y=scale,
                    rotation=rotation,
                    rotation_x=tilt,
                    rotation_y=-tilt,
                    opacity=opacity,
                    elevation=elevation,
                    background_color="#806CFF",
                    corner_radius=18,
                ),
                width=PANEL_WIDTH,
                height=88,
                margin_top=18,
                margin_bottom=14,
                background_color="#28243F",
                corner_radius=18,
                overflow="visible",
            ),
            Row(
                Button(
                    "Reverse",
                    on_click=reverse,
                    theme=THEME,
                    content_description="motion-reverse",
                ),
                Button(
                    curve.value.replace("_", " "),
                    on_click=lambda: curve.set(
                        "overshoot" if curve.value == "ease_in_out" else "ease_in_out"
                    ),
                    variant="outlined",
                    theme=THEME,
                    margin_start=8,
                    content_description="motion-curve",
                ),
            ),
            tone="dark",
            content_description="motion-declarative-card",
        ),
        _card(
            _eyebrow("Spring and Canvas"),
            Text(
                text="Geometry, paint, trim and dash offset",
                font_size=18,
                text_color=COLORS.on_surface,
                margin_top=4,
                include_font_padding=False,
            ),
            Box(
                Box(
                    width=44,
                    height=44,
                    translation_x=spring_x,
                    background_color=COLORS.tertiary,
                    corner_radius=22,
                    elevation=4,
                ),
                width=PANEL_WIDTH,
                height=56,
                margin_top=14,
                background_color=COLORS.surface_container,
                corner_radius=28,
                overflow="visible",
            ),
            Canvas(
                draw=[
                    {
                        "kind": "round_rect",
                        "x": 6,
                        "y": 8,
                        "width": canvas_width,
                        "height": 28,
                        "radius": canvas_radius,
                        "fill": COLORS.primary,
                        "opacity": canvas_opacity,
                    },
                    {
                        "kind": "path",
                        "d": "M12,53 C70,18 150,84 280,49",
                        "stroke": COLORS.tertiary,
                        "stroke_width": 4,
                        "stroke_cap": "round",
                        "dash": [10, 6],
                        "dash_offset": dash,
                        "trim_end": trim,
                    },
                ],
                view_box=[0, 0, PANEL_WIDTH, 74],
                width=PANEL_WIDTH,
                height=74,
                margin_top=8,
                content_description="motion-canvas",
            ),
            Text(
                text="Spring velocity survives retargeting; Canvas operations keep stable presentation slots.",
                font_size=12,
                line_height=18,
                text_color=COLORS.on_surface_variant,
                margin_top=8,
            ),
        ),
        _card(
            _eyebrow("Imperative keyframes"),
            Text(
                text=motion_status.value,
                font_size=15,
                line_height=21,
                text_color=COLORS.on_surface,
                margin_top=5,
                content_description="motion-status",
            ),
            Box(
                Box(
                    width=42,
                    height=42,
                    background_color="#1B9AAA",
                    corner_radius=12,
                    ref=_KEYFRAME_REF,
                ),
                width=PANEL_WIDTH,
                height=58,
                margin_top=14,
                margin_bottom=12,
                background_color="#E1F5F5",
                corner_radius=16,
                overflow="visible",
            ),
            Row(
                Button(
                    "Play timeline",
                    on_click=play_keyframes,
                    theme=THEME,
                    content_description="motion-play-keyframes",
                ),
                Button(
                    "Cancel",
                    on_click=cancel_keyframes,
                    variant="text",
                    theme=THEME,
                    margin_start=6,
                    content_description="motion-cancel-keyframes",
                ),
            ),
        ),
        width="match_parent",
    )


@component
def AsyncShowcase():
    stage = state("Idle")
    progress = state(0.0)
    result = state("No payload loaded")
    request_id = state(0)
    side_taps = state(0)
    jobs_started = state(0)
    jobs_finished = state("")
    bar_progress = Animated.Value(0.0)

    def set_progress(value: float):
        progress.set(value)
        Animated.timing(
            bar_progress,
            to=value,
            duration=300,
            easing="ease_out",
        ).start()

    async def load_dashboard():
        current = request_id.value + 1
        request_id.set(current)
        stage.set("Request dispatched · UI already committed")
        set_progress(0.12)
        result.set("Waiting for simulated I/O…")
        animate(
            _ASYNC_PULSE_REF,
            opacity=[0.35, 1.0, 0.35, 1.0],
            duration=180,
            easing="ease_in_out",
        )
        await asyncio.sleep(0.34)

        stage.set("Response arrived · decoding")
        set_progress(0.62)
        result.set("Python resumed in a later commit")
        await asyncio.sleep(0.34)

        stage.set("Ready")
        set_progress(1.0)
        result.set(f"Dashboard payload #{current} rendered")

    async def race_job():
        job = jobs_started.value + 1
        jobs_started.set(job)
        delay = 0.62 if job % 2 else 0.18
        await asyncio.sleep(delay)
        jobs_finished.set(
            f"{jobs_finished.value} #{job}".strip()
        )

    bar_width = bar_progress.interpolate(
        [0, 1],
        [2, PANEL_WIDTH],
        extrapolate="clamp",
    )

    return Column(
        _title(
            "Async work stays visible",
            "State before and after await becomes separate ordered commits while native motion keeps running.",
        ),
        _card(
            _eyebrow("Await boundary", inverse=True),
            Text(
                text=stage.value,
                font_size=19,
                line_height=25,
                text_color="#FFFFFF",
                margin_top=5,
                content_description="async-stage",
            ),
            Text(
                text=result.value,
                font_size=13,
                line_height=19,
                text_color="#D7D1F5",
                margin_top=4,
                content_description="async-result",
            ),
            Box(
                Box(
                    width=bar_width,
                    height=8,
                    background_color="#9B8CFF",
                    corner_radius=4,
                ),
                width=PANEL_WIDTH,
                height=8,
                background_color="#35304D",
                corner_radius=4,
                margin_top=18,
                margin_bottom=16,
                overflow="hidden",
            ),
            Row(
                Button(
                    "Fetch dashboard",
                    on_click=load_dashboard,
                    theme=THEME,
                    content_description="async-fetch",
                ),
                Badged(
                    Button(
                        "Still responsive",
                        on_click=lambda: side_taps.set(side_taps.value + 1),
                        variant="outlined",
                        theme=THEME,
                        margin_start=8,
                        content_description="async-side-action",
                    ),
                    Badge(side_taps.value, theme=THEME),
                ),
            ),
            Box(
                Text(
                    text="native frames continue while Python sleeps",
                    text_color="#FFFFFF",
                    font_size=12,
                    lp_gravity="center",
                ),
                ref=_ASYNC_PULSE_REF,
                width="match_parent",
                height=38,
                margin_top=14,
                background_color="#2C2941",
                corner_radius=12,
                content_description="async-native-pulse",
            ),
            tone="dark",
        ),
        _card(
            _eyebrow("Concurrent callbacks"),
            Text(
                text="Tap twice: even jobs finish first",
                font_size=18,
                text_color=COLORS.on_surface,
                margin_top=5,
            ),
            Text(
                text=(
                    f"Started {jobs_started.value} · completion order:"
                    f" {jobs_finished.value or '—'}"
                ),
                font_size=13,
                line_height=19,
                text_color=COLORS.on_surface_variant,
                margin_top=6,
                margin_bottom=12,
                content_description="async-race-status",
            ),
            Button(
                "Start independent job",
                on_click=race_job,
                variant="tonal",
                theme=THEME,
                content_description="async-race",
            ),
        ),
        _card(
            _eyebrow("Commit model"),
            Row(
                _metric("before await", "Commit A"),
                _metric("native motion", "UI clock"),
                _metric("after await", "Commit B"),
                width="match_parent",
            ),
            LinearProgressIndicator(
                # The Canvas contract requires positive rectangle geometry.
                progress=max(0.01, progress.value),
                width=PANEL_WIDTH,
                height=6,
                theme=THEME,
                margin_top=16,
            ),
            Text(
                text="Other callbacks never wait for the fetch to return.",
                font_size=12,
                text_color=COLORS.on_surface_variant,
                margin_top=10,
            ),
        ),
        width="match_parent",
    )


@component
def StylingShowcase():
    warm = state(False)
    compact = state(False)

    accent = "#D6497D" if warm.value else COLORS.primary
    pale = "#FFE0EA" if warm.value else COLORS.primary_container
    ink = "#4B0B26" if warm.value else COLORS.on_primary_container

    decoration = Decoration.rectangle(
        fill=pale,
        stroke=Stroke(color=accent, width=1),
        corners=CornerRadius.all(24),
        shadow=Shadow(elevation=3),
        ripple=Ripple(color="#206750E8"),
    )

    return Column(
        _title(
            "Typed styling, flat native props",
            "Direct visual props and Decoration lower to ordinary validated renderer properties.",
        ),
        Column(
            _eyebrow("Direct props + Decoration"),
            Text(
                text="Composable surface",
                font_size=24,
                line_height=30,
                text_color=ink,
                include_font_padding=False,
                margin_top=7,
            ),
            Text(
                text="Solid fill · stroke · corners · elevation · bounded ripple",
                font_size=13,
                line_height=19,
                text_color=ink,
                margin_top=6,
            ),
            Row(
                Button(
                    "Change palette",
                    on_click=lambda: warm.set(not warm.value),
                    theme=THEME,
                    content_description="style-palette",
                ),
                Button(
                    "Compact",
                    on_click=lambda: compact.set(not compact.value),
                    variant="text",
                    theme=THEME,
                    margin_start=6,
                    content_description="style-density",
                ),
                margin_top=18,
            ),
            padding=12 if compact.value else 20,
            decoration=decoration,
            width="match_parent",
            margin_bottom=14,
            content_description="style-composed-card",
        ),
        _card(
            _eyebrow("Per-corner geometry"),
            Row(
                Box(
                    Text(text="TL", text_color="#FFFFFF", lp_gravity="center"),
                    width=78,
                    height=78,
                    background_color=accent,
                    corner_radius_top_left=30,
                    corner_radius_bottom_right=10,
                ),
                Box(
                    Text(text="BR", text_color=ink, lp_gravity="center"),
                    width=78,
                    height=78,
                    margin_start=12,
                    background_color=pale,
                    border_width=2,
                    border_color=accent,
                    corner_radius_top_right=10,
                    corner_radius_bottom_left=30,
                ),
                align_items="center",
                margin_top=12,
            ),
            Text(
                text="Independent corner radii are preserved instead of approximated.",
                font_size=12,
                line_height=18,
                text_color=COLORS.on_surface_variant,
                margin_top=12,
            ),
        ),
        _card(
            _eyebrow("Typography and precedence"),
            Text(
                text="Display / 28",
                text_color=accent,
                font_size=28,
                line_height=34,
                include_font_padding=False,
            ),
            Text(
                text="Body copy uses direct visual properties.",
                text_color=COLORS.on_surface_variant,
                font_size=15,
                line_height=22,
                margin_top=5,
            ),
            Text(
                text="Each visual property is explicit",
                text_color=COLORS.primary,
                font_size=13,
                margin_top=12,
            ),
        ),
        _card(
            _eyebrow("Native state styling"),
            Row(
                Box(
                    Text(text="Ripple", text_color="#FFFFFF", lp_gravity="center"),
                    width=88,
                    height=48,
                    background_color=accent,
                    corner_radius=24,
                    ripple_color="#40FFFFFF",
                    on_click=lambda: warm.set(not warm.value),
                ),
                Box(
                    Text(text="Shadow", text_color=ink, lp_gravity="center"),
                    width=88,
                    height=48,
                    margin_start=16,
                    background_color=pale,
                    corner_radius=14,
                    elevation=8,
                ),
            ),
            tone="rose" if warm.value else "surface",
        ),
        width="match_parent",
    )


@component
def ControlsShowcase():
    name = state("")
    checked = state(False)
    enabled = state(True)
    filter_on = state(False)
    segment = state("motion")
    slider_value = state(0.38)

    return Column(
        _title(
            "Controlled native components",
            "Inputs, gestures and accessibility events round-trip through Python-owned state.",
        ),
        _card(
            _eyebrow("Text input"),
            TextField(
                value=name.value,
                label="Your name",
                placeholder="Type here",
                supporting_text="Native EditText, controlled by Python",
                leading="Aa",
                variant="outlined",
                on_text_change=name.set,
                theme=THEME,
                width="match_parent",
                content_description="controls-name",
                margin_top=10,
            ),
            Text(
                text=f"Hello, {name.value or 'explorer'}",
                font_size=16,
                text_color=COLORS.primary,
                margin_top=12,
                content_description="controls-greeting",
            ),
        ),
        _card(
            _eyebrow("Selection"),
            Checkbox(
                checked.value,
                label="Enable motion",
                on_change=checked.set,
                theme=THEME,
            ),
            Switch(
                enabled.value,
                label="Live updates",
                supporting_text="Toggle remains fully controlled",
                on_change=enabled.set,
                theme=THEME,
            ),
            Row(
                Chip(
                    "Filter",
                    variant="filter",
                    selected=filter_on.value,
                    on_change=filter_on.set,
                    theme=THEME,
                ),
                Chip(
                    "Suggestion",
                    variant="suggestion",
                    elevated=True,
                    leading="✦",
                    theme=THEME,
                    margin_start=8,
                ),
                margin_top=6,
            ),
        ),
        _card(
            _eyebrow("Gesture-driven Canvas"),
            Slider(
                slider_value.value,
                minimum=0,
                maximum=1,
                on_change=slider_value.set,
                width=PANEL_WIDTH,
                theme=THEME,
                margin_top=8,
            ),
            Text(
                text=f"Value {slider_value.value:.3f}",
                font_size=13,
                text_color=COLORS.on_surface_variant,
                content_description="controls-slider-value",
            ),
            LinearProgressIndicator(
                progress=slider_value.value,
                width=PANEL_WIDTH,
                height=8,
                theme=THEME,
                margin_top=12,
            ),
        ),
        _card(
            _eyebrow("Segmented navigation"),
            SegmentedButtonGroup(
                [
                    SegmentedItem("Motion", "motion"),
                    SegmentedItem("Async", "async"),
                    SegmentedItem("Visuals", "visuals"),
                ],
                selected=segment.value,
                on_select=segment.set,
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=12,
                content_description="controls-segments",
            ),
            Text(
                text=f"Selected: {segment.value}",
                font_size=13,
                text_color=COLORS.on_surface_variant,
                margin_top=10,
                content_description="controls-segment-value",
            ),
        ),
        Row(
            Button("Filled", theme=THEME),
            Button("Tonal", variant="tonal", theme=THEME, margin_start=7),
            Button("Text", variant="text", theme=THEME, margin_start=4),
            width="match_parent",
            margin_bottom=18,
        ),
        width="match_parent",
    )



_STATIC_LIST_ITEMS = range(30_000)
_STATIC_LIST_COLORS = ("#6750E8", "#A33E72", "#1B9AAA", "#5D5A72", "#386A20")


def _static_list_item(item, _index):
    color = _STATIC_LIST_COLORS[item % len(_STATIC_LIST_COLORS)]
    return Column(
        Text(
            text=f"Static item {item:,}",
            font_size=15,
            text_color="#FFFFFF",
            include_font_padding=False,
        ),
        Text(
            text="Immutable range · stable key",
            font_size=11,
            line_height=16,
            text_color="#EAE4FF",
            margin_top=5,
            include_font_padding=False,
        ),
        width="match_parent",
        height="match_parent",
        padding=14,
        margin_end=8,
        background_color=color,
        corner_radius=18,
    )


def _dynamic_list_item(item, index):
    return Row(
        Box(
            Text(
                text=str(index + 1),
                text_color="#FFFFFF",
                font_size=13,
                lp_gravity="center",
            ),
            width=38,
            height=38,
            background_color=COLORS.primary if index % 2 == 0 else COLORS.tertiary,
            corner_radius=19,
        ),
        Column(
            Text(
                text=f"Dynamic item {item}",
                font_size=15,
                text_color=COLORS.on_surface,
                include_font_padding=False,
            ),
            Text(
                text=f"Stable key {item}",
                font_size=11,
                text_color=COLORS.on_surface_variant,
                margin_top=3,
                include_font_padding=False,
            ),
            width=0,
            lp_weight=1,
            margin_start=12,
        ),
        width="match_parent",
        height="match_parent",
        padding_start=12,
        padding_end=12,
        align_items="center",
        background_color=(
            COLORS.surface_container_lowest
            if index % 2 == 0
            else COLORS.surface_container_low
        ),
        content_description=f"dynamic-item-{item}",
    )


@component
def ListsShowcase():
    items = state(tuple(range(30_000)))
    next_item = state(30_000)

    def append_item():
        item = next_item.value
        next_item.set(item + 1)
        items.set(items.value + (item,))

    def remove_item():
        if items.value:
            items.set(items.value[:-1])

    def reverse_items():
        items.set(tuple(reversed(items.value)))

    return Column(
        _title(
            "Static and dynamic lists",
            "Both use the same generic virtual-list engine and native scroll mechanics.",
        ),
        _card(
            _eyebrow("Static horizontal data"),
            Text(
                text="30,000 immutable items",
                font_size=18,
                text_color=COLORS.on_surface,
                margin_top=4,
                margin_bottom=12,
            ),
            List(
                _STATIC_LIST_ITEMS,
                render_item=_static_list_item,
                key_for_item=lambda item, _index: item,
                item_extent=140,
                axis="horizontal",
                initial_item_count=3,
                width="match_parent",
                height=108,
                key="showcase-static-list",
                content_description="static-list",
            ),
        ),
        Row(
            Button(
                "Add",
                on_click=append_item,
                theme=THEME,
                content_description="dynamic-list-add",
            ),
            Button(
                "Remove",
                on_click=remove_item,
                variant="outlined",
                theme=THEME,
                margin_start=7,
                content_description="dynamic-list-remove",
            ),
            Button(
                "Reverse",
                on_click=reverse_items,
                variant="text",
                theme=THEME,
                margin_start=3,
                content_description="dynamic-list-reverse",
            ),
            align_items="center",
        ),
        Text(
            text=f"{len(items.value):,} state-owned rows · add, remove, or reorder",
            font_size=12,
            text_color=COLORS.on_surface_variant,
            margin_top=9,
            margin_bottom=10,
            content_description="dynamic-list-count",
        ),
        List(
            items.value,
            render_item=_dynamic_list_item,
            key_for_item=lambda item, _index: item,
            item_extent=64,
            initial_item_count=8,
            width="match_parent",
            height=0,
            lp_weight=1,
            key="showcase-dynamic-list",
            background_color=COLORS.surface_container_low,
            corner_radius=18,
            overflow="hidden",
            content_description="dynamic-list",
        ),
        width="match_parent",
        height="match_parent",
        padding_start=16,
        padding_end=16,
        padding_top=20,
        padding_bottom=16,
        background_color=COLORS.surface,
        content_description="showcase-lists",
    )


@component
def MaterialShowcase():
    toggled = state(True)
    choice = state("one")
    carousel_index = state(0)
    slider_value = state(0.42)
    range_value = state((0.2, 0.78))
    field_value = state("Vyne")
    query = state("native")
    selected_tab = state(0)
    selected_date = state(date(2026, 7, 16))
    selected_range = state((date(2026, 7, 12), date(2026, 7, 18)))
    selected_time = state((10, 30))
    selected_time_part = state("hour")

    navigation_items = (
        NavigationItem("Home", "⌂", badge=3),
        NavigationItem("Saved", "☆"),
        NavigationItem("Profile", "●"),
    )

    return Column(
        _title(
            "Every Material widget",
            "One live example of every public Material constructor, all lowered to core primitives.",
        ),
        _card(
            _eyebrow("App bars"),
            TopAppBar(
                "Vyne Material",
                navigation=IconButton("←", theme=THEME),
                actions=(IconButton("⋮", theme=THEME),),
                subtitle="TopAppBar",
                theme=THEME,
                width="match_parent",
            ),
            BottomAppBar(
                IconButton("⌂", theme=THEME),
                IconButton("☆", theme=THEME),
                floating_action_button=FloatingActionButton("+", theme=THEME),
                theme=THEME,
                width="match_parent",
                margin_top=10,
            ),
            content_description="material-app-bars",
        ),
        _card(
            _eyebrow("Badges and buttons"),
            Row(
                Badge(7, theme=THEME),
                Badged(
                    IconButton("✉", theme=THEME),
                    Badge(3, theme=THEME),
                    width=48,
                    height=48,
                    margin_start=20,
                ),
                IconButton(
                    "♥",
                    variant="tonal",
                    selected=toggled.value,
                    on_click=lambda: toggled.set(not toggled.value),
                    theme=THEME,
                    margin_start=20,
                ),
                align_items="center",
                margin_top=12,
            ),
            Row(
                Button("Filled", theme=THEME),
                Button("Tonal", variant="tonal", theme=THEME, margin_start=7),
                Button("Text", variant="text", theme=THEME, margin_start=4),
                margin_top=10,
            ),
            ButtonGroup(
                (
                    ButtonGroupItem("One", "one"),
                    ButtonGroupItem("Two", "two"),
                ),
                selected=choice.value,
                on_select=choice.set,
                connected=True,
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=10,
            ),
            Row(
                FloatingActionButton("+", theme=THEME),
                ExtendedFloatingActionButton(
                    "Create",
                    icon="+",
                    theme=THEME,
                    margin_start=10,
                ),
                align_items="center",
                margin_top=12,
            ),
            FloatingActionButtonMenu(
                (
                    FabMenuItem("Create", "+"),
                    FabMenuItem("Edit", "✎"),
                ),
                expanded=True,
                theme=THEME,
                margin_top=12,
            ),
            SplitButton(
                "Save",
                expanded=toggled.value,
                on_menu_click=toggled.set,
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=12,
            ),
            content_description="material-buttons",
        ),
        _card(
            _eyebrow("Cards, carousel and dialog"),
            Card(
                Text(text="Card", text_color=COLORS.on_surface),
                Text(
                    text="Elevated Python-owned surface",
                    text_color=COLORS.on_surface_variant,
                    font_size=12,
                    margin_top=4,
                ),
                theme=THEME,
                width="match_parent",
                margin_top=10,
            ),
            Carousel(
                Box(
                    Text(text="First", text_color="#FFFFFF", lp_gravity="center"),
                    height=82,
                    background_color=COLORS.primary,
                ),
                Box(
                    Text(text="Second", text_color="#FFFFFF", lp_gravity="center"),
                    height=82,
                    background_color=COLORS.tertiary,
                ),
                active_index=carousel_index.value,
                on_index_change=carousel_index.set,
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=12,
            ),
            Dialog(
                Text(text="Dialog body", text_color=COLORS.on_surface),
                title="Dialog",
                icon="!",
                actions=(Button("OK", variant="text", theme=THEME),),
                theme=THEME,
                margin_top=12,
            ),
            content_description="material-surfaces",
        ),
        _card(
            _eyebrow("Sheets"),
            BottomSheet(
                Text(text="BottomSheet", text_color=COLORS.on_surface),
                modal=False,
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=10,
            ),
            SideSheet(
                Text(text="SideSheet", text_color=COLORS.on_surface),
                modal=False,
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=12,
            ),
            content_description="material-sheets",
        ),
        _card(
            _eyebrow("Lists, menus and divider"),
            MaterialList(
                ListItem(
                    "Inbox",
                    supporting_text="MaterialList + ListItem",
                    leading="✉",
                    trailing="12",
                    theme=THEME,
                ),
                MaterialDivider(inset=16, theme=THEME),
                ListItem("Settings", leading="⚙", theme=THEME),
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=10,
            ),
            Menu(
                (
                    MenuItem("Copy", leading="□"),
                    MenuItem("Paste", leading="▣", selected=True),
                ),
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=12,
            ),
            content_description="material-lists-menus",
        ),
        _card(
            _eyebrow("Progress"),
            Row(
                LoadingIndicator(phase=0.28, theme=THEME),
                CircularProgressIndicator(0.68, theme=THEME, margin_start=20),
                align_items="center",
                margin_top=12,
            ),
            LinearProgressIndicator(
                0.62,
                width=PANEL_WIDTH,
                height=6,
                theme=THEME,
                margin_top=14,
            ),
            LinearWavyProgressIndicator(
                0.48,
                width=PANEL_WIDTH,
                height=5,
                theme=THEME,
                margin_top=14,
            ),
            content_description="material-progress",
        ),
        _card(
            _eyebrow("Navigation"),
            NavigationBar(
                navigation_items,
                selected_index=0,
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=10,
            ),
            NavigationRail(
                navigation_items,
                selected_index=1,
                expanded=True,
                theme=THEME,
                margin_top=12,
            ),
            NavigationDrawer(
                navigation_items,
                selected_index=2,
                header=Text(
                    text="NavigationDrawer",
                    text_color=COLORS.on_surface,
                    margin_bottom=8,
                ),
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=12,
            ),
            content_description="material-navigation",
        ),
        _card(
            _eyebrow("Selection controls"),
            Checkbox(
                toggled.value,
                label="Checkbox",
                on_change=toggled.set,
                theme=THEME,
                margin_top=8,
            ),
            Switch(
                toggled.value,
                label="Switch",
                supporting_text="Shared controlled value",
                on_change=toggled.set,
                theme=THEME,
            ),
            RadioButton(
                toggled.value,
                label="RadioButton",
                value=True,
                on_select=lambda value: toggled.set(bool(value)),
                theme=THEME,
            ),
            Chip(
                "Filter chip",
                variant="filter",
                selected=toggled.value,
                on_change=toggled.set,
                theme=THEME,
            ),
            SegmentedButton(
                "Standalone",
                selected=choice.value == "one",
                on_click=lambda: choice.set("one"),
                theme=THEME,
                margin_top=10,
            ),
            SegmentedButtonGroup(
                (
                    SegmentedItem("One", "one"),
                    SegmentedItem("Two", "two"),
                    SegmentedItem("Three", "three"),
                ),
                selected=choice.value,
                on_select=choice.set,
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=10,
            ),
            content_description="material-selection",
        ),
        _card(
            _eyebrow("Sliders and text input"),
            Slider(
                slider_value.value,
                on_change=slider_value.set,
                width=PANEL_WIDTH,
                theme=THEME,
                margin_top=8,
            ),
            RangeSlider(
                range_value.value,
                on_change=range_value.set,
                width=PANEL_WIDTH,
                theme=THEME,
                margin_top=8,
            ),
            TextField(
                value=field_value.value,
                label="TextField",
                supporting_text="Controlled text",
                on_text_change=field_value.set,
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=12,
            ),
            SearchBar(
                query=query.value,
                expanded=True,
                on_query_change=query.set,
                on_search=query.set,
                results=(ListItem("Search result", theme=THEME),),
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=12,
            ),
            content_description="material-inputs",
        ),
        _card(
            _eyebrow("Date and time pickers"),
            DatePicker(
                year=2026,
                month=7,
                selected=selected_date.value,
                on_select=selected_date.set,
                theme=THEME,
                margin_top=10,
            ),
            DateRangePicker(
                year=2026,
                month=7,
                start=selected_range.value[0],
                end=selected_range.value[1],
                on_change=selected_range.set,
                theme=THEME,
                margin_top=14,
            ),
            TimePicker(
                hour=selected_time.value[0],
                minute=selected_time.value[1],
                selection=selected_time_part.value,
                on_change=selected_time.set,
                on_selection_change=selected_time_part.set,
                theme=THEME,
                margin_top=14,
            ),
            content_description="material-pickers",
        ),
        _card(
            _eyebrow("Feedback"),
            Snackbar(
                "Everything is native",
                action_label="Undo",
                icon="✓",
                theme=THEME,
                margin_top=10,
            ),
            Tooltip(
                Button("Tooltip anchor", variant="outlined", theme=THEME),
                "Tooltip",
                visible=True,
                rich=True,
                supporting_text="Long-press support is also available.",
                action=Button("Action", variant="text", theme=THEME),
                theme=THEME,
                margin_top=14,
            ),
            content_description="material-feedback",
        ),
        _card(
            _eyebrow("Tabs and toolbars"),
            Tab(
                "Standalone Tab",
                selected=True,
                icon="●",
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=10,
            ),
            Tabs(
                (TabItem("First"), TabItem("Second"), TabItem("Third")),
                selected_index=selected_tab.value,
                on_select=selected_tab.set,
                secondary=True,
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=10,
            ),
            Toolbar(
                IconButton("B", theme=THEME),
                IconButton("I", theme=THEME),
                IconButton("U", theme=THEME),
                floating=False,
                theme=THEME,
                width=PANEL_WIDTH,
                margin_top=12,
            ),
            FloatingToolbar(
                IconButton("←", theme=THEME),
                IconButton("→", theme=THEME),
                theme=THEME,
                margin_top=12,
            ),
            content_description="material-tabs-toolbars",
        ),
        width="match_parent",
        content_description="showcase-material",
    )


def App(context: AppContext):
    selected = state(0)

    panels = (
        MotionShowcase(),
        AsyncShowcase(),
        StylingShowcase(),
        ControlsShowcase(),
    )
    labels = ("Motion", "Async", "Visuals", "Controls", "Lists", "Material")
    if selected.value == 4:
        panel = ListsShowcase()
    elif selected.value == 5:
        panel = MaterialShowcase()
    else:
        panel = panels[selected.value]

    body = (
        panel
        if selected.value == 4
        else Scroll(
            Column(
                panel,
                padding_start=16,
                padding_end=16,
                padding_top=20,
                padding_bottom=28,
                width="match_parent",
            ),
            width="match_parent",
            height=0,
            lp_weight=1,
            background_color=COLORS.surface,
            content_description=f"showcase-{labels[selected.value].lower()}",
        )
    )

    return Column(
        Column(
            Row(
                Column(
                    Text(
                        text="VYNE LAB",
                        font_size=11,
                        text_color="#BDB4FF",
                        include_font_padding=False,
                    ),
                    Text(
                        text="Native UI, Python authored",
                        font_size=22,
                        line_height=28,
                        text_color="#FFFFFF",
                        include_font_padding=False,
                        margin_top=3,
                    ),
                    width=0,
                    lp_weight=1,
                ),
                Box(
                    Text(
                        text=f"launch {context.launch.sequence}",
                        font_size=11,
                        text_color="#FFFFFF",
                        lp_gravity="center",
                    ),
                    width=72,
                    height=30,
                    background_color="#34304B",
                    corner_radius=15,
                ),
                align_items="center",
            ),
            Text(
                text="Animations · lists · complete Material catalog",
                font_size=13,
                text_color="#D7D1F5",
                margin_top=10,
            ),
            padding_start=18,
            padding_end=18,
            padding_top=0,
            padding_bottom=16,
            background_color="#19172B",
            width="match_parent",
            content_description="showcase-header",
        ),
        Tabs(
            [TabItem(label) for label in labels],
            selected_index=selected.value,
            on_select=selected.set,
            secondary=True,
            theme=THEME,
            width="match_parent",
            content_description="showcase-tabs",
        ),
        body,
        width="match_parent",
        height="match_parent",
        safe_area=True,
        # The root owns the system inset regions, so its dark fill also keeps
        # edge-to-edge status-bar icons legible.
        background_color="#19172B",
        content_description="showcase-root",
    )


run_app(App)
