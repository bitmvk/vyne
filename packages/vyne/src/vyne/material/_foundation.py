"""Shared lowering helpers for Python-owned Material components."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

from vyne.animations import AnimatedValue
from vyne.elements import Box, Canvas, Column, Element, Row, Text
from vyne.material._callbacks import CallbackAdapter, prepare_handler
from vyne.material._geometry import progress_path as _progress_path
from vyne.material._geometry import wavy_path as _wavy_path
from vyne.material._validation import alpha
from vyne.material.theme import MaterialTheme, TypeStyle


Callback = Callable[..., Any]


def invoke(callback: Callback | None, value: Any) -> None:
    """Invoke a controlled-component callback with a value when accepted.

    Uses :class:`CallbackAdapter` for one-time signature inspection.
    """
    if callback is None:
        return
    CallbackAdapter(callback).invoke(value)


def value_handler(callback: Callback | None, value: Any) -> Callback | None:
    """Create an event handler that calls *callback* with *value*.

    Uses :func:`prepare_handler` from ``_callbacks`` for one-time inspection.
    """
    return prepare_handler(callback, value)


def text(
    value: str,
    *,
    color: str,
    typography: TypeStyle,
    align: str | None = None,
    description: str | None = None,
    **props: Any,
) -> Element:
    if align is not None:
        props["text_alignment"] = align
    if description is not None:
        props["content_description"] = description
    return Text(
        text=value,
        text_color=color,
        font_size=typography.font_size,
        line_height=typography.line_height,
        include_font_padding=False,
        **props,
    )


def slot(
    content: Element | str | int | None,
    *,
    color: str,
    typography: TypeStyle,
    description: str | None = None,
) -> Element | None:
    if content is None:
        return None
    if isinstance(content, Element):
        return content
    return text(
        str(content),
        color=color,
        typography=typography,
        description=description,
    )


def spacer(*, width: float | None = None, height: float | None = None) -> Element:
    props: dict[str, Any] = {}
    if width is not None:
        props["width"] = width
    if height is not None:
        props["height"] = height
    return Box(**props)


def spaced_row(
    children: Iterable[Element | None],
    gap: float,
    **props: Any,
) -> Element:
    resolved = [child for child in children if child is not None]
    interleaved: list[Element] = []
    for index, child in enumerate(resolved):
        if index:
            interleaved.append(spacer(width=gap, height=1))
        interleaved.append(child)
    return Row(*interleaved, **props)


def spaced_column(
    children: Iterable[Element | None],
    gap: float,
    **props: Any,
) -> Element:
    resolved = [child for child in children if child is not None]
    interleaved: list[Element] = []
    for index, child in enumerate(resolved):
        if index:
            interleaved.append(spacer(height=gap, width=1))
        interleaved.append(child)
    return Column(*interleaved, **props)


def checkmark_canvas(
    *,
    checked: bool,
    indeterminate: bool = False,
    enabled: bool,
    theme: MaterialTheme,
    size: float = 18,
) -> Element:
    colors = theme.colors
    active = colors.primary if enabled else alpha(colors.on_surface, 0.38)
    inactive = colors.outline if enabled else alpha(colors.on_surface, 0.38)
    if checked or indeterminate:
        mark = (
            "M4 9 L14 9"
            if indeterminate
            else "M4.5 9 L7.5 12 L13.8 5.7"
        )
        draw = [
            {
                "kind": "round_rect",
                "x": 0,
                "y": 0,
                "width": 18,
                "height": 18,
                "radius": 2,
                "fill": active,
            },
            {
                "kind": "path",
                "d": mark,
                "stroke": colors.on_primary,
                "stroke_width": 2,
                "stroke_cap": "square",
                "stroke_join": "miter",
            },
        ]
    else:
        draw = [
            {
                "kind": "round_rect",
                "x": 1,
                "y": 1,
                "width": 16,
                "height": 16,
                "radius": 1,
                "stroke": inactive,
                "stroke_width": 2,
            }
        ]
    return Canvas(draw=draw, view_box=[0, 0, 18, 18], width=size, height=size)


def radio_canvas(
    *,
    selected: bool,
    enabled: bool,
    theme: MaterialTheme,
    size: float = 20,
) -> Element:
    color = (
        theme.colors.primary
        if selected and enabled
        else theme.colors.on_surface_variant
        if enabled
        else alpha(theme.colors.on_surface, 0.38)
    )
    draw: list[dict[str, Any]] = [
        {
            "kind": "circle",
            "cx": 10,
            "cy": 10,
            "r": 9,
            "stroke": color,
            "stroke_width": 2,
        }
    ]
    if selected:
        draw.append({"kind": "circle", "cx": 10, "cy": 10, "r": 5, "fill": color})
    return Canvas(draw=draw, view_box=[0, 0, 20, 20], width=size, height=size)


def switch_canvas(
    *,
    checked: bool,
    enabled: bool,
    theme: MaterialTheme,
) -> Element:
    colors = theme.colors
    track = (
        colors.primary
        if checked and enabled
        else alpha(colors.on_surface, 0.12)
        if checked
        else colors.surface_container_highest
        if enabled
        else alpha(colors.on_surface, 0.12)
    )
    outline = track if checked else (
        colors.outline if enabled else alpha(colors.on_surface, 0.12)
    )
    thumb = (
        colors.on_primary
        if checked and enabled
        else alpha(colors.surface, 0.8)
        if checked
        else colors.outline
        if enabled
        else alpha(colors.on_surface, 0.38)
    )
    # Python owns the Material geometry and motion choice. The native Canvas
    # only integrates this generic spring between declarative numeric targets.
    target_radius = 12 if checked else 8
    target_cx = 36 if checked else 16
    radius = AnimatedValue(
        target_radius,
        duration=400,
        easing="spring",
        damping_ratio=0.6,
        stiffness=800,
    )
    cx = AnimatedValue(
        target_cx,
        duration=400,
        easing="spring",
        damping_ratio=0.6,
        stiffness=800,
    )
    draw = [
        {
            "kind": "round_rect",
            "x": 1,
            "y": 1,
            "width": 50,
            "height": 30,
            "radius": 15,
            "fill": track,
            "stroke": outline,
            "stroke_width": 2,
        },
        {"kind": "circle", "cx": cx, "cy": 16, "r": radius, "fill": thumb},
    ]
    return Canvas(draw=draw, view_box=[0, 0, 52, 32], width=52, height=32)


def progress_path() -> str:
    """Return the canonical progress circle path string (24×24)."""
    return _progress_path()


def wavy_path(width: float, height: float, cycles: int = 8) -> str:
    """Build a wavy-line SVG path string for the given dimensions."""
    return _wavy_path(width, height, cycles)


def require_choice(value: str, *, name: str, choices: Sequence[str]) -> str:
    if value not in choices:
        expected = ", ".join(choices)
        raise ValueError(f"{name} must be one of: {expected}")
    return value
