"""Typed property definitions for Vyne widgets.

Each TypedDict defines the type-safe API surface for a widget constructor.
They serve as documentation and enable IDE autocompletion; at runtime,
available props are validated by Runtime._allowed_props_for() rather
than directly checked against these TypedDict definitions.

The ``total=False`` default means every prop is optional — only ``Required[...]``
fields (like ``text`` on Text, ``d`` on Path) are mandatory.
"""

from __future__ import annotations

from typing import Any, Literal, Required, TypedDict
from vyne.animations import AnimatedNode, AnimatedValue

EventCallback = Any
AnimatableNumber = int | float | AnimatedNode | AnimatedValue


class BaseProps(TypedDict, total=False):
    """Generic properties available on every primitive widget."""

    width: AnimatableNumber
    height: AnimatableNumber
    padding: int | float
    padding_top: int | float
    padding_bottom: int | float
    padding_start: int | float
    padding_end: int | float
    safe_area: bool
    margin_top: int | float
    margin_bottom: int | float
    margin_start: int | float
    margin_end: int | float
    background_color: str
    corner_radius: int | float
    corner_radius_top_left: int | float
    corner_radius_top_right: int | float
    corner_radius_bottom_right: int | float
    corner_radius_bottom_left: int | float
    border_width: int | float
    border_color: str
    enabled: bool
    visible: bool
    alpha: AnimatableNumber
    opacity: AnimatableNumber
    elevation: AnimatableNumber
    clickable: bool
    content_description: str
    focusable: bool
    min_width: int | float
    min_height: int | float
    rotation: AnimatableNumber
    rotation_x: AnimatableNumber
    rotation_y: AnimatableNumber
    scale_x: AnimatableNumber
    scale_y: AnimatableNumber
    translation_x: AnimatableNumber
    translation_y: AnimatableNumber
    text_alignment: str
    text_direction: str
    align_items: str
    justify_content: str
    lp_weight: float
    lp_gravity: str
    ripple_color: str
    pointer_capture_axis: Literal["horizontal", "vertical"]
    on_accessibility_progress: EventCallback
    on_click: EventCallback
    on_long_click: EventCallback
    on_pointer_cancel: EventCallback
    on_pointer_down: EventCallback
    on_pointer_move: EventCallback
    on_pointer_up: EventCallback
    on_focus_change: EventCallback


class ContainerProps(BaseProps, total=False):
    """Properties shared by primitives which can contain child views."""

    overflow: Literal["visible", "hidden"]


class BoxProps(ContainerProps, total=False):
    """Properties for Box primitive."""


class LayoutProps(ContainerProps, total=False):
    """Properties for Layout (LinearLayout) primitive."""

    orientation: Required[str]


class RowProps(ContainerProps, total=False):
    """Properties for Row composite."""


class ColumnProps(ContainerProps, total=False):
    """Properties for Column composite."""


class ScrollProps(ContainerProps, total=False):
    """Properties for Scroll (ScrollView) primitive."""


class TextProps(BaseProps, total=False):
    """Properties for Text primitive."""

    text: Required[str]
    text_color: str
    font_size: int | float
    line_height: int | float
    include_font_padding: bool


class TextInputProps(BaseProps, total=False):
    """Properties for TextInput primitive."""

    text: str
    hint: str
    text_color: str
    font_size: int | float
    focused: bool
    blur_on_keyboard_hide: bool
    blur_on_tap_outside: bool
    blur_on_submit: bool
    on_text_change: EventCallback
    on_editor_action: EventCallback
    on_focus_change: EventCallback


class ImageProps(BaseProps, total=False):
    """Properties for Image primitive."""

    source: str
    scale_type: str


class PathProps(BaseProps, total=False):
    """Properties for Path primitive — renders an SVG path string."""

    d: Required[str]
    stroke_color: str
    stroke_width: int | float
    stroke_line_cap: str
    stroke_line_join: str
    fill_color: str
    stroke_dash_array: str
    stroke_dash_offset: AnimatableNumber


class CanvasProps(BaseProps, total=False):
    """Properties for Canvas primitive — renders a JSON display list."""

    draw: list[dict[str, Any]]
    view_box: tuple[int | float, int | float, int | float, int | float] | list[int | float]
