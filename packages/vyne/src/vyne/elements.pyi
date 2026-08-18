"""Type stubs for ``vyne.elements``.

GENERATED FILE. DO NOT EDIT.

Regenerate with:
    uv run python scripts/generate_schema_stubs.py

Source of truth: ``vyne.spec.schema_v2``.
"""

# schema-v2 source hash: 7a5762a4a4283a2c

from typing import Any, Literal, TypeAlias, TypedDict, Unpack

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from vyne.animations import AnimatedNode
from vyne.refs import Ref
from vyne.style import Decoration
from vyne.values import FrozenMap

EventCallback = Callable[..., Any]
AnimatableNumber = int | float | AnimatedNode
ElementKey: TypeAlias = str | int | tuple[ElementKey, ...]

class BaseProps(TypedDict, total=False):
    accessibility_checked: bool | None
    accessibility_range_current: AnimatableNumber | None
    accessibility_range_max: AnimatableNumber | None
    accessibility_range_min: AnimatableNumber | None
    accessibility_role: Literal['adjustable', 'button', 'checkbox', 'dropdown_list', 'header', 'image', 'keyboard_key', 'link', 'none', 'progress_bar', 'radio_button', 'search', 'slider', 'switch', 'tab', 'text', 'toolbar'] | None
    accessibility_selected: bool | None
    accessibility_state_checked: bool | None
    accessibility_state_description: str | None
    accessibility_state_selected: bool | None
    alpha: AnimatableNumber | None
    background_color: str | None
    border_color: str | None
    border_width: AnimatableNumber | None
    clickable: bool | None
    content_description: str | None
    corner_radius: AnimatableNumber | None
    corner_radius_bottom_left: AnimatableNumber | None
    corner_radius_bottom_right: AnimatableNumber | None
    corner_radius_top_left: AnimatableNumber | None
    corner_radius_top_right: AnimatableNumber | None
    decoration: Decoration | dict[str, Any] | None
    elevation: AnimatableNumber | None
    enabled: bool | None
    focusable: bool | None
    height: str | int | float | AnimatedNode | None
    key: ElementKey | None
    lp_gravity: Literal['bottom', 'bottom|end', 'bottom|start', 'center', 'center_horizontal', 'center_vertical', 'end', 'start', 'top', 'top|end', 'top|start'] | None
    lp_weight: AnimatableNumber | None
    margin_bottom: AnimatableNumber | None
    margin_end: AnimatableNumber | None
    margin_start: AnimatableNumber | None
    margin_top: AnimatableNumber | None
    min_height: AnimatableNumber | None
    min_width: AnimatableNumber | None
    on_accessibility_progress: EventCallback | None
    on_click: EventCallback | None
    on_long_click: EventCallback | None
    on_pointer_cancel: EventCallback | None
    on_pointer_down: EventCallback | None
    on_pointer_move: EventCallback | None
    on_pointer_up: EventCallback | None
    opacity: AnimatableNumber | None
    padding: AnimatableNumber | None
    padding_bottom: AnimatableNumber | None
    padding_end: AnimatableNumber | None
    padding_start: AnimatableNumber | None
    padding_top: AnimatableNumber | None
    pointer_capture_axis: Literal['horizontal', 'vertical'] | None
    ref: Ref | None
    ripple_color: str | None
    rotation: AnimatableNumber | None
    rotation_x: AnimatableNumber | None
    rotation_y: AnimatableNumber | None
    safe_area: bool | None
    scale_x: AnimatableNumber | None
    scale_y: AnimatableNumber | None
    text_alignment: Literal['center', 'end', 'start'] | None
    text_direction: Literal['inherit', 'ltr', 'rtl'] | None
    translation_x: AnimatableNumber | None
    translation_y: AnimatableNumber | None
    visible: bool | None
    width: str | int | float | AnimatedNode | None

class ContainerProps(BaseProps, total=False):
    align_items: Literal['center', 'end', 'start', 'stretch'] | None
    justify_content: Literal['center', 'end', 'space_around', 'space_between', 'space_evenly', 'start'] | None
    max_height: AnimatableNumber | None
    max_width: AnimatableNumber | None
    overflow: Literal['hidden', 'visible'] | None

class BoxProps(ContainerProps, total=False):
    ...

class LayoutProps(ContainerProps, total=False):
    orientation: Literal['horizontal', 'vertical'] | None

class RowProps(ContainerProps, total=False):
    ...

class ColumnProps(ContainerProps, total=False):
    ...

class ScrollProps(ContainerProps, total=False):
    interactive_scrollbar: bool | None

class TextProps(BaseProps, total=False):
    font_size: AnimatableNumber | None
    include_font_padding: bool | None
    line_height: AnimatableNumber | None
    text: str | None
    text_color: str | None

class TextInputProps(BaseProps, total=False):
    blur_on_keyboard_hide: bool | None
    blur_on_submit: bool | None
    blur_on_tap_outside: bool | None
    focused: bool | None
    font_size: AnimatableNumber | None
    hint: str | None
    on_editor_action: EventCallback | None
    on_focus_change: EventCallback | None
    on_text_change: EventCallback | None
    text: str | None
    text_color: str | None

class ImageProps(BaseProps, total=False):
    scale_type: Literal['center_crop', 'center_inside', 'fit_center'] | None
    source: str | None

class PathProps(BaseProps, total=False):
    commands: list[Any] | tuple[Any, ...] | None
    d: str | None
    fill_color: str | None
    stroke_color: str | None
    stroke_dash_array: tuple[int | float, ...] | str | None
    stroke_dash_offset: AnimatableNumber | None
    stroke_line_cap: Literal['butt', 'round', 'square'] | None
    stroke_line_join: Literal['bevel', 'miter', 'round'] | None
    stroke_width: AnimatableNumber | None

class CanvasProps(BaseProps, total=False):
    draw: list[Any] | None
    view_box: list[int | float] | tuple[int | float, ...] | None

class HorizontalScrollProps(ContainerProps, total=False):
    interactive_scrollbar: bool | None


@dataclass(frozen=True)
class Element:
    kind: str
    # Runtime keeps the frozen FrozenMap; the constructor accepts any
    # mapping (converted and frozen in ``__post_init__``).
    props: Mapping[str, Any] | FrozenMap = ...
    children: tuple[Element, ...] = ()

def Box(*children: Any, **props: Unpack[BoxProps]) -> Element: ...
def Layout(*children: Any, **props: Unpack[LayoutProps]) -> Element: ...
def Row(*children: Any, **props: Unpack[RowProps]) -> Element: ...
def Column(*children: Any, **props: Unpack[ColumnProps]) -> Element: ...
def Scroll(*children: Any, **props: Unpack[ScrollProps]) -> Element: ...
def Text(**props: Unpack[TextProps]) -> Element: ...
def TextInput(**props: Unpack[TextInputProps]) -> Element: ...
def Image(**props: Unpack[ImageProps]) -> Element: ...
def Path(**props: Unpack[PathProps]) -> Element: ...
def Canvas(**props: Unpack[CanvasProps]) -> Element: ...
def _horizontal_scroll(*children: Any, **props: Unpack[HorizontalScrollProps]) -> Element: ...
def normalize_child(child: Any) -> Element: ...
def normalize_children(children: tuple[Any, ...]) -> tuple[Element, ...]: ...
def event_name_for_prop(prop_name: str) -> str | None: ...
