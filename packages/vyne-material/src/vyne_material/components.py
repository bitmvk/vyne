"""Python-owned Material 3 Expressive component library.

Every public constructor in this module lowers to Vyne's existing renderer
primitives.  No Material component kind, state machine, or selection policy is
implemented by Kotlin.
"""

from __future__ import annotations

import calendar
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from vyne.elements import Box, Canvas, Column
from vyne.elements import Element, Row, TextInput
from vyne.component import component
from vyne.events import latest
from vyne_material._callbacks import normalize_selection
from vyne_material._foundation import (
    alpha,
    checkmark_canvas,
    invoke,
    progress_path,
    radio_canvas,
    require_choice,
    slot,
    spaced_column,
    spaced_row,
    spacer,
    switch_canvas,
    text,
    value_handler,
    wavy_path,
)
from vyne_material._validation import (
    RangeSliderGesture,
    SliderGesture,
    SliderSpec,
    resolve_ripple_color,
    slider_targets,
    validate_finite,
)
from vyne_material.theme import DEFAULT_THEME, MaterialTheme


Callback = Callable[..., Any]


def _clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp *value* into the inclusive [minimum, maximum] interval."""
    if minimum > maximum:
        raise ValueError("minimum must be <= maximum")
    return max(minimum, min(value, maximum))


@dataclass(frozen=True)
class ButtonGroupItem:
    label: str
    value: Any
    icon: Element | str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class FabMenuItem:
    label: str
    icon: Element | str
    on_click: Callback | None = None
    enabled: bool = True


@dataclass(frozen=True)
class MenuItem:
    label: str
    on_click: Callback | None = None
    leading: Element | str | None = None
    trailing: Element | str | None = None
    supporting_text: str | None = None
    enabled: bool = True
    selected: bool = False


@dataclass(frozen=True)
class NavigationItem:
    label: str
    icon: Element | str
    on_click: Callback | None = None
    selected_icon: Element | str | None = None
    badge: str | int | None = None
    enabled: bool = True


@dataclass(frozen=True)
class SegmentedItem:
    label: str
    value: Any
    icon: Element | str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class TabItem:
    label: str
    icon: Element | str | None = None
    enabled: bool = True


# ---------------------------------------------------------------------------
# App bars


def TopAppBar(
    title: str,
    *,
    navigation: Element | None = None,
    actions: Sequence[Element] = (),
    variant: str = "small",
    subtitle: str | None = None,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    """Material top app bar: small, medium, large, or flexible."""
    require_choice(variant, name="variant", choices=("small", "medium", "large", "flexible"))
    heights = {"small": 64, "medium": 112, "large": 152, "flexible": 120}
    title_style = (
        theme.typography.title_large
        if variant == "small"
        else theme.typography.headline_small
        if variant in ("medium", "flexible")
        else theme.typography.headline_medium
    )
    title_children = [
        text(title, color=theme.colors.on_surface, typography=title_style),
        text(
            subtitle,
            color=theme.colors.on_surface_variant,
            typography=theme.typography.body_medium,
        ) if subtitle else None,
    ]
    if variant == "small":
        title_block = spaced_column(
            title_children,
            2,
            width=0,
            lp_weight=1,
            justify_content="center",
        )
        return spaced_row(
            [navigation, title_block, *actions],
            8,
            align_items="center",
            padding_start=16,
            padding_end=16,
            height=heights[variant],
            background_color=theme.colors.surface,
            **props,
        )

    actions_host = spaced_row(
        actions,
        8,
        width=0,
        lp_weight=1,
        align_items="center",
        justify_content="end",
    )
    action_row = spaced_row(
        [navigation, actions_host],
        8,
        width="match_parent",
        height=64,
        padding_start=16,
        padding_end=16,
        align_items="center",
    )
    title_block = spaced_column(
        title_children,
        2,
        width="match_parent",
        padding_start=16,
        padding_end=16,
        height=heights[variant] - 64,
        justify_content="center",
    )
    return Column(
        action_row,
        title_block,
        height=heights[variant],
        background_color=theme.colors.surface,
        **props,
    )


def BottomAppBar(
    *actions: Element,
    floating_action_button: Element | None = None,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    children: list[Element | None] = [*actions]
    if floating_action_button is not None:
        # A zero-width weighted spacer is understood by Android's
        # LinearLayout and keeps the FAB pinned to the trailing edge.  The
        # renderer intentionally does not implement CSS-style space-between.
        children.extend([spacer(width=0, height=1), floating_action_button])
        children[-2] = replace(
            children[-2],
            props={**children[-2].props, "lp_weight": 1},
        )
    return spaced_row(
        children,
        4,
        height=80,
        padding_start=16,
        padding_end=16,
        align_items="center",
        background_color=theme.colors.surface_container,
        **props,
    )


# ---------------------------------------------------------------------------
# Badges


def Badge(
    value: str | int | None = None,
    *,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    if value is None:
        return Box(
            width=6,
            height=6,
            corner_radius=3,
            background_color=theme.colors.error,
            content_description="New notification",
            **props,
        )
    label = str(value)
    # Native wrap-content measurement: let Android size the Text, then pad.
    # No ``len(label) * constant`` estimate.
    return Row(
        text(label, color=theme.colors.on_error, typography=theme.typography.label_small),
        min_width=16,
        height=16,
        padding_start=4,
        padding_end=4,
        align_items="center",
        justify_content="center",
        corner_radius=8,
        background_color=theme.colors.error,
        content_description=label,
        **props,
    )


def Badged(content: Element, badge: Element, **props: Any) -> Element:
    positioned_badge = replace(
        badge,
        props={**badge.props, "lp_gravity": "top|end"},
    )
    return Box(
        content,
        positioned_badge,
        overflow="visible",
        **props,
    )


# ---------------------------------------------------------------------------
# Sheets


def BottomSheet(
    *children: Element,
    visible: bool = True,
    modal: bool = True,
    on_dismiss: Callback | None = None,
    show_drag_handle: bool = True,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element | None:
    if not visible:
        return None
    handle = None
    if show_drag_handle:
        handle = Box(
            width=32,
            height=4,
            corner_radius=2,
            background_color=theme.colors.on_surface_variant,
            lp_gravity="center_horizontal",
            on_click=on_dismiss,
            content_description="Dismiss sheet" if on_dismiss else "Sheet handle",
        )
    return spaced_column(
        [handle, *children],
        16,
        padding_top=12,
        padding_bottom=24,
        padding_start=24,
        padding_end=24,
        corner_radius_top_left=theme.shapes.extra_large,
        corner_radius_top_right=theme.shapes.extra_large,
        background_color=(
            theme.colors.surface_container_low
            if modal
            else theme.colors.surface_container
        ),
        elevation=1 if modal else 0,
        overflow="hidden",
        **props,
    )


def SideSheet(
    *children: Element,
    visible: bool = True,
    modal: bool = True,
    side: str = "end",
    on_dismiss: Callback | None = None,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element | None:
    if not visible:
        return None
    require_choice(side, name="side", choices=("start", "end"))
    close = IconButton(
        "×",
        on_click=on_dismiss,
        content_description="Close sheet",
        theme=theme,
        lp_gravity="end",
    ) if on_dismiss else None
    radius_props = (
        {"corner_radius_top_right": 28, "corner_radius_bottom_right": 28}
        if side == "start"
        else {"corner_radius_top_left": 28, "corner_radius_bottom_left": 28}
    )
    sheet_props = {
        "width": 360,
        "padding": 24,
        "background_color": (
            theme.colors.surface_container_low
            if modal
            else theme.colors.surface
        ),
        "elevation": 1 if modal else 0,
        "lp_gravity": side,
        **radius_props,
        **props,
    }
    return spaced_column([close, *children], 16, **sheet_props)


# ---------------------------------------------------------------------------
# Buttons and button groups


_BUTTON_HEIGHTS = {"extra_small": 32, "small": 40, "medium": 56, "large": 96, "extra_large": 136}
_BUTTON_RADII = {"extra_small": 16, "small": 20, "medium": 28, "large": 28, "extra_large": 28}


def Button(
    label: str | Element,
    *,
    on_click: Callback | None = None,
    variant: str = "filled",
    size: str = "small",
    leading: Element | str | None = None,
    trailing: Element | str | None = None,
    enabled: bool = True,
    content_description: str | None = None,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    require_choice(
        variant,
        name="variant",
        choices=("filled", "tonal", "elevated", "outlined", "text"),
    )
    require_choice(size, name="size", choices=tuple(_BUTTON_HEIGHTS))
    # Material buttons size to their content unless the caller explicitly
    # asks them to fill or weight a parent.  Vyne's vertical Layout children
    # otherwise default to MATCH_PARENT, which turns every button in a Column
    # into an unintended full-width action.
    props.setdefault("width", "wrap_content")
    colors = theme.colors
    if not enabled:
        container = alpha(colors.on_surface, 0.12) if variant != "text" else "#00000000"
        foreground = alpha(colors.on_surface, 0.38)
        border_color = alpha(colors.on_surface, 0.12) if variant == "outlined" else None
    elif variant == "filled":
        container, foreground, border_color = colors.primary, colors.on_primary, None
    elif variant == "tonal":
        container, foreground, border_color = (
            colors.secondary_container,
            colors.on_secondary_container,
            None,
        )
    elif variant == "elevated":
        container, foreground, border_color = colors.surface_container_low, colors.primary, None
    elif variant == "outlined":
        container, foreground, border_color = "#00000000", colors.primary, colors.outline
    else:
        container, foreground, border_color = "#00000000", colors.primary, None

    label_style = theme.typography.label_large
    label_element = (
        label
        if isinstance(label, Element)
        else text(label, color=foreground, typography=label_style)
    )
    leading_element = slot(leading, color=foreground, typography=label_style)
    trailing_element = slot(trailing, color=foreground, typography=label_style)
    border_props = (
        {"border_width": 1, "border_color": border_color}
        if border_color is not None
        else {}
    )
    component_props = {
        "height": _BUTTON_HEIGHTS[size],
        "min_width": _BUTTON_HEIGHTS[size],
        "padding_start": 24 if size != "extra_small" else 12,
        "padding_end": 24 if size != "extra_small" else 12,
        "align_items": "center",
        "justify_content": "center",
        "background_color": container,
        "corner_radius": _BUTTON_RADII[size],
        "elevation": 1 if variant == "elevated" and enabled else 0,
        "ripple_color": alpha(foreground, 0.12),
        "enabled": enabled,
        "on_click": on_click if enabled else None,
        "content_description": content_description,
        **border_props,
        **props,
    }
    return spaced_row([leading_element, label_element, trailing_element], 8, **component_props)


def ButtonGroup(
    items: Sequence[ButtonGroupItem],
    *,
    selected: Any | Sequence[Any] | None = None,
    on_select: Callback | None = None,
    multi_select: bool = False,
    connected: bool = False,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    # Selection callbacks receive the proposed next value directly.
    normalized = normalize_selection(
        selected,
        [item.value for item in items],
        multi=multi_select,
    )
    selected_values: set[Any]
    if multi_select:
        selected_values = set(normalized) if normalized else set()
    else:
        selected_values = {normalized} if normalized is not None else set()
    children: list[Element] = []
    for index, item in enumerate(items):
        is_selected = item.value in selected_values
        if multi_select:
            next_selection = tuple(
                candidate.value
                for candidate in items
                if (candidate.value in selected_values) != (candidate.value == item.value)
            )
        else:
            next_selection = item.value
        if connected:
            radius_props: dict[str, Any] = {
                "corner_radius_top_left": 20 if index == 0 else 4,
                "corner_radius_bottom_left": 20 if index == 0 else 4,
                "corner_radius_top_right": 20 if index == len(items) - 1 else 4,
                "corner_radius_bottom_right": 20 if index == len(items) - 1 else 4,
            }
        else:
            radius_props = {}
        # Reuse the callback via a lightweight closure.
        def _make_handler(val: Any) -> Callback | None:
            if on_select is None:
                return None

            def _h(_event: Any) -> None:
                on_select(val)

            return _h
        children.append(
            Button(
                item.label,
                leading=item.icon,
                enabled=item.enabled,
                variant="tonal" if is_selected else "outlined",
                on_click=_make_handler(next_selection),
                # Selection changes color, never geometry.
                width=0,
                lp_weight=1,
                theme=theme,
                **radius_props,
            )
        )
    return spaced_row(children, 2 if connected else 8, **props)


def IconButton(
    icon: Element | str,
    *,
    on_click: Callback | None = None,
    variant: str = "standard",
    selected: bool = False,
    enabled: bool = True,
    size: str = "small",
    content_description: str | None = None,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    require_choice(variant, name="variant", choices=("standard", "filled", "tonal", "outlined"))
    sizes = {"extra_small": 32, "small": 40, "medium": 56, "large": 96}
    require_choice(size, name="size", choices=tuple(sizes))
    colors = theme.colors
    if not enabled:
        foreground = alpha(colors.on_surface, 0.38)
        container = alpha(colors.on_surface, 0.12) if variant != "standard" else "#00000000"
    elif selected:
        foreground, container = colors.on_primary, colors.primary
    elif variant == "filled":
        foreground, container = colors.on_primary, colors.primary
    elif variant == "tonal":
        foreground, container = colors.on_secondary_container, colors.secondary_container
    else:
        foreground, container = colors.on_surface_variant, "#00000000"
    icon_element = slot(
        icon,
        color=foreground,
        typography=theme.typography.title_large,
        description=content_description,
    )
    border_props = (
        {"border_width": 1, "border_color": colors.outline}
        if variant == "outlined"
        else {}
    )
    dimension = sizes[size]
    return Row(
        icon_element,
        width=dimension,
        height=dimension,
        align_items="center",
        justify_content="center",
        corner_radius=dimension / 2,
        background_color=container,
        ripple_color=alpha(foreground, 0.12),
        enabled=enabled,
        on_click=on_click if enabled else None,
        content_description=content_description,
        **border_props,
        **props,
    )


def FloatingActionButton(
    icon: Element | str,
    *,
    on_click: Callback | None = None,
    size: str = "medium",
    color: str = "primary_container",
    enabled: bool = True,
    content_description: str | None = None,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    sizes = {"small": 40, "medium": 56, "large": 96}
    require_choice(size, name="size", choices=tuple(sizes))
    require_choice(
        color,
        name="color",
        choices=("primary", "primary_container", "secondary_container", "tertiary_container"),
    )
    colors = theme.colors
    container = getattr(colors, color)
    foreground = getattr(colors, f"on_{color}")
    if not enabled:
        container = alpha(colors.on_surface, 0.12)
        foreground = alpha(colors.on_surface, 0.38)
    dimension = sizes[size]
    return Row(
        slot(icon, color=foreground, typography=theme.typography.headline_small),
        width=dimension,
        height=dimension,
        align_items="center",
        justify_content="center",
        corner_radius=theme.shapes.large if size != "large" else theme.shapes.extra_large,
        background_color=container,
        ripple_color=alpha(foreground, 0.12) if enabled else alpha(colors.on_surface, 0.0),
        elevation=6 if enabled else 0,
        on_click=on_click if enabled else None,
        content_description=content_description,
        enabled=enabled,
        **props,
    )


def ExtendedFloatingActionButton(
    label: str,
    *,
    icon: Element | str | None = None,
    on_click: Callback | None = None,
    expanded: bool = True,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    if not expanded and icon is not None:
        return FloatingActionButton(icon, on_click=on_click, theme=theme, **props)
    return Button(
        label,
        leading=icon,
        on_click=on_click,
        variant="tonal",
        size="medium",
        elevation=6,
        theme=theme,
        **props,
    )


def FloatingActionButtonMenu(
    items: Sequence[FabMenuItem],
    *,
    expanded: bool,
    on_toggle: Callback | None = None,
    toggle_icon: Element | str = "+",
    close_icon: Element | str = "×",
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    menu_items: list[Element] = []
    if expanded:
        for item in items:
            menu_items.append(
                spaced_row(
                    [
                        Button(
                            item.label,
                            on_click=item.on_click,
                            enabled=item.enabled,
                            variant="elevated",
                            theme=theme,
                        ),
                        FloatingActionButton(
                            item.icon,
                            on_click=item.on_click,
                            size="small",
                            theme=theme,
                        ),
                    ],
                    8,
                    align_items="center",
                    justify_content="end",
                )
            )
    menu_items.append(
        FloatingActionButton(
            close_icon if expanded else toggle_icon,
            on_click=value_handler(on_toggle, not expanded),
            content_description="Close actions" if expanded else "Open actions",
            theme=theme,
        )
    )
    return spaced_column(menu_items, 12, align_items="end", **props)


def SplitButton(
    label: str,
    *,
    on_click: Callback | None = None,
    on_menu_click: Callback | None = None,
    expanded: bool = False,
    variant: str = "filled",
    size: str = "small",
    enabled: bool = True,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    require_choice(
        variant,
        name="variant",
        choices=("filled", "tonal", "elevated", "outlined", "text"),
    )
    require_choice(size, name="size", choices=tuple(_BUTTON_HEIGHTS))
    colors = theme.colors
    if not enabled:
        menu_foreground = alpha(colors.on_surface, 0.38)
    elif variant == "filled":
        menu_foreground = colors.on_primary
    elif variant == "tonal":
        menu_foreground = colors.on_secondary_container
    else:
        menu_foreground = colors.primary
    main = Button(
        label,
        on_click=on_click,
        variant=variant,
        size=size,
        enabled=enabled,
        corner_radius_top_right=4,
        corner_radius_bottom_right=4,
        theme=theme,
        width=0,
        lp_weight=1,
    )
    menu = Button(
        text(
            "⌄",
            color=menu_foreground,
            typography=(
                theme.typography.title_medium
                if size in ("extra_small", "small")
                else theme.typography.title_large
            ),
            rotation=180 if expanded else 0,
        ),
        on_click=value_handler(on_menu_click, not expanded),
        variant=variant,
        size=size,
        enabled=enabled,
        content_description="Show menu" if not expanded else "Hide menu",
        corner_radius_top_left=4,
        corner_radius_bottom_left=4,
        width=_BUTTON_HEIGHTS[size],
        min_width=_BUTTON_HEIGHTS[size],
        padding_start=0,
        padding_end=0,
        theme=theme,
    )
    return spaced_row([main, menu], 2, **props)


# ---------------------------------------------------------------------------
# Cards, carousel, and dialogs


def Card(
    *children: Element,
    variant: str = "elevated",
    on_click: Callback | None = None,
    enabled: bool = True,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    require_choice(variant, name="variant", choices=("elevated", "filled", "outlined"))
    colors = theme.colors
    background = (
        colors.surface_container_low
        if variant == "elevated"
        else colors.surface_container_highest
        if variant == "filled"
        else colors.surface
    )
    border_props = (
        {"border_width": 1, "border_color": colors.outline_variant}
        if variant == "outlined"
        else {}
    )
    return Column(
        *children,
        padding=16,
        background_color=background,
        corner_radius=theme.shapes.medium,
        elevation=1 if variant == "elevated" else 0,
        ripple_color=alpha(colors.on_surface, 0.12),
        on_click=on_click if enabled else None,
        enabled=enabled,
        overflow="hidden",
        **border_props,
        **props,
    )


def Carousel(
    *items: Element,
    active_index: int = 0,
    on_index_change: Callback | None = None,
    show_controls: bool = True,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    if not items:
        return Box(**props)
    index = max(0, min(len(items) - 1, active_index))
    active = Box(
        items[index],
        corner_radius=theme.shapes.extra_large,
        overflow="hidden",
        width=0,
        lp_weight=1,
    )
    if not show_controls or len(items) == 1:
        return Box(active, **props)
    previous_index = (index - 1) % len(items)
    next_index = (index + 1) % len(items)
    return spaced_row(
        [
            IconButton(
                "‹",
                on_click=value_handler(on_index_change, previous_index),
                content_description="Previous item",
                theme=theme,
            ),
            active,
            IconButton(
                "›",
                on_click=value_handler(on_index_change, next_index),
                content_description="Next item",
                theme=theme,
            ),
        ],
        8,
        align_items="center",
        **props,
    )


def Dialog(
    *children: Element,
    title: str | None = None,
    icon: Element | str | None = None,
    actions: Sequence[Element] = (),
    visible: bool = True,
    on_dismiss: Callback | None = None,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element | None:
    if not visible:
        return None
    heading_content = slot(icon, color=theme.colors.secondary, typography=theme.typography.headline_small)
    heading = (
        Row(
            heading_content,
            align_items="center",
            justify_content="center",
        )
        if heading_content is not None
        else None
    )
    title_element = (
        text(
            title,
            color=theme.colors.on_surface,
            typography=theme.typography.headline_small,
            align="center" if heading is not None else None,
        )
        if title
        else None
    )
    action_row = spaced_row(actions, 8, justify_content="end") if actions else None
    dismiss = (
        IconButton(
            "×",
            on_click=on_dismiss,
            content_description="Dismiss dialog",
            theme=theme,
            lp_gravity="end",
        )
        if on_dismiss
        else None
    )
    return spaced_column(
        [dismiss, heading, title_element, *children, action_row],
        16,
        min_width=280,
        padding=24,
        corner_radius=theme.shapes.extra_large,
        background_color=theme.colors.surface_container_high,
        elevation=6,
        **props,
    )


def MaterialDivider(
    *,
    orientation: str = "horizontal",
    inset: float = 0,
    thickness: float = 1,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    require_choice(orientation, name="orientation", choices=("horizontal", "vertical"))
    if orientation == "horizontal":
        props.setdefault("margin_start", inset)
        props.setdefault("margin_end", inset)
        props.setdefault("height", thickness)
    else:
        props.setdefault("margin_top", inset)
        props.setdefault("margin_bottom", inset)
        props.setdefault("width", thickness)
    return Box(
        background_color=theme.colors.outline_variant,
        **props,
    )


# ---------------------------------------------------------------------------
# Lists and menus


def MaterialList(*items: Element, theme: MaterialTheme = DEFAULT_THEME, **props: Any) -> Element:
    return Column(*items, background_color=theme.colors.surface, **props)


def ListItem(
    headline: str,
    *,
    supporting_text: str | None = None,
    overline: str | None = None,
    leading: Element | str | None = None,
    trailing: Element | str | None = None,
    selected: bool = False,
    enabled: bool = True,
    on_click: Callback | None = None,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    props.setdefault("width", "match_parent")
    colors = theme.colors
    foreground = colors.on_surface if enabled else alpha(colors.on_surface, 0.38)
    leading_element = slot(leading, color=colors.on_surface_variant, typography=theme.typography.title_large)
    trailing_element = slot(trailing, color=colors.on_surface_variant, typography=theme.typography.label_small)
    if leading_element is not None:
        leading_element = Row(
            leading_element,
            width=24,
            height=24,
            align_items="center",
            justify_content="center",
        )
    if trailing_element is not None:
        trailing_element = Row(
            trailing_element,
            min_width=24,
            height=24,
            align_items="center",
            justify_content="center",
        )
    text_block = spaced_column(
        [
            text(overline, color=colors.on_surface_variant, typography=theme.typography.label_small) if overline else None,
            text(headline, color=foreground, typography=theme.typography.body_large),
            text(
                supporting_text,
                color=colors.on_surface_variant if enabled else foreground,
                typography=theme.typography.body_medium,
            ) if supporting_text else None,
        ],
        2,
        width=0,
        lp_weight=1,
        justify_content="center",
    )
    lines = 1 + int(supporting_text is not None) + int(overline is not None)
    height = {1: 56, 2: 72, 3: 88}[lines]
    return spaced_row(
        [
            leading_element,
            text_block,
            trailing_element,
        ],
        16,
        min_height=height,
        padding_start=16,
        padding_end=16,
        align_items="center",
        background_color=colors.secondary_container if selected else colors.surface,
        ripple_color=alpha(colors.on_surface, 0.12),
        on_click=on_click if enabled else None,
        enabled=enabled,
        **props,
    )


def Menu(
    items: Sequence[MenuItem],
    *,
    open: bool = True,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element | None:
    if not open:
        return None
    if items:
        # Native wrap-content: use ``width`` as a natural upper bound
        # and ``min_width`` for the lower bound, instead of
        # ``len(label) * constant`` estimates (MATERIAL-04).
        props.setdefault("min_width", 112)
        props.setdefault("width", 280)
    children = [
        ListItem(
            item.label,
            supporting_text=item.supporting_text,
            leading=item.leading,
            trailing=item.trailing,
            selected=item.selected,
            enabled=item.enabled,
            on_click=item.on_click,
            theme=theme,
        )
        for item in items
    ]
    return Column(
        *children,
        padding_top=8,
        padding_bottom=8,
        corner_radius=theme.shapes.extra_small,
        background_color=theme.colors.surface_container,
        elevation=3,
        overflow="hidden",
        **props,
    )


# ---------------------------------------------------------------------------
# Loading and progress indicators


def LoadingIndicator(
    *,
    phase: float = 0.0,
    size: float = 48,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    """Expressive morph-style loading glyph controlled by ``phase``."""
    normalized = phase % 1.0
    points = 8
    draw: list[dict[str, Any]] = []
    for index in range(points):
        angle = normalized * math.tau + index * math.tau / points
        distance = 14 + 3 * math.sin(normalized * math.tau + index)
        radius = 2.5 + 2.5 * ((index + normalized * points) % points) / points
        draw.append(
            {
                "kind": "circle",
                "cx": 24 + math.cos(angle) * distance,
                "cy": 24 + math.sin(angle) * distance,
                "r": radius,
                "fill": theme.colors.primary,
            }
        )
    return Canvas(
        draw=draw,
        view_box=[0, 0, 48, 48],
        width=size,
        height=size,
        content_description="Loading",
        **props,
    )


def CircularProgressIndicator(
    progress: float | None = None,
    *,
    phase: float = 0.0,
    size: float = 48,
    stroke_width: float = 4,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    value = 0.25 if progress is None else max(0.0, min(1.0, progress))
    description = "Loading" if progress is None else f"{round(value * 100)} percent"
    return Canvas(
        draw=[
            {
                "kind": "path",
                "d": progress_path(),
                "stroke": theme.colors.secondary_container,
                "stroke_width": stroke_width,
                "stroke_cap": "round",
            },
            {
                "kind": "path",
                "d": progress_path(),
                "stroke": theme.colors.primary,
                "stroke_width": stroke_width,
                "stroke_cap": "round",
                "trim_end": value,
            },
        ],
        view_box=[0, 0, 24, 24],
        width=size,
        height=size,
        rotation=phase * 360,
        content_description=description,
        **props,
    )


def LinearProgressIndicator(
    progress: float | None = None,
    *,
    phase: float = 0.0,
    width: float = 240,
    height: float = 4,
    wavy: bool = False,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    value = ((phase % 1.0) * 0.65 + 0.2) if progress is None else max(0.0, min(1.0, progress))
    if wavy:
        draw = [
            {
                "kind": "path",
                "d": wavy_path(width, max(height, 12)),
                "stroke": theme.colors.secondary_container,
                "stroke_width": height,
                "stroke_cap": "round",
            },
            {
                "kind": "path",
                "d": wavy_path(width, max(height, 12)),
                "stroke": theme.colors.primary,
                "stroke_width": height,
                "stroke_cap": "round",
                "trim_end": value,
            },
        ]
        view_height = max(height, 12)
    else:
        draw = [
            {"kind": "round_rect", "x": 0, "y": 0, "width": width, "height": height, "radius": height / 2, "fill": theme.colors.secondary_container},
            {"kind": "round_rect", "x": 0, "y": 0, "width": width * value, "height": height, "radius": height / 2, "fill": theme.colors.primary},
        ]
        view_height = height
    description = "Loading" if progress is None else f"{round(value * 100)} percent"
    return Canvas(
        draw=draw,
        view_box=[0, 0, width, view_height],
        width=width,
        height=view_height,
        content_description=description,
        **props,
    )


def LinearWavyProgressIndicator(*args: Any, **kwargs: Any) -> Element:
    kwargs["wavy"] = True
    return LinearProgressIndicator(*args, **kwargs)


# ---------------------------------------------------------------------------
# Navigation


def _navigation_destination(
    item: NavigationItem,
    *,
    selected: bool,
    vertical: bool,
    weighted: bool = False,
    theme: MaterialTheme,
) -> Element:
    colors = theme.colors
    foreground = (
        colors.on_secondary_container
        if selected
        else colors.on_surface_variant
        if item.enabled
        else alpha(colors.on_surface, 0.38)
    )
    icon = item.selected_icon if selected and item.selected_icon is not None else item.icon
    icon_element = slot(icon, color=foreground, typography=theme.typography.title_large)
    if item.badge is not None and icon_element is not None:
        icon_element = Badged(
            Row(
                icon_element,
                width=24,
                height=24,
                align_items="center",
                justify_content="center",
            ),
            Badge(item.badge, theme=theme),
        )
    indicator = Row(
        icon_element,
        width=64 if vertical else 56,
        height=32,
        padding_start=16,
        padding_end=16,
        align_items="center",
        justify_content="center",
        corner_radius=16,
        background_color=colors.secondary_container if selected else "#00000000",
        ripple_color=alpha(foreground, 0.12),
    )
    label_content = text(
        item.label,
        color=foreground,
        typography=theme.typography.label_medium,
    )
    # A Text child fills the width of a vertical LinearLayout on Android.  A
    # centered host keeps the visible label aligned with the indicator instead
    # of leaving the glyphs at the start edge of that full-width Text view.
    label = (
        Row(
            label_content,
            height=theme.typography.label_medium.line_height,
            align_items="center",
            justify_content="center",
        )
        if vertical
        else label_content
    )
    layout = spaced_column if vertical else spaced_row
    return layout(
        [indicator, label],
        4 if vertical else 12,
        min_width=64,
        min_height=64,
        padding=4,
        align_items="center",
        justify_content="center",
        enabled=item.enabled,
        on_click=item.on_click if item.enabled else None,
        content_description=item.label,
        width=0 if weighted else None,
        lp_weight=1 if weighted else None,
    )


def NavigationBar(
    items: Sequence[NavigationItem],
    *,
    selected_index: int = 0,
    short: bool = False,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    children = [
        _navigation_destination(
            item,
            selected=index == selected_index,
            vertical=not short,
            weighted=True,
            theme=theme,
        )
        for index, item in enumerate(items)
    ]
    return Row(
        *children,
        height=64 if short else 80,
        padding_start=8,
        padding_end=8,
        align_items="center",
        background_color=theme.colors.surface_container,
        **props,
    )


def NavigationRail(
    items: Sequence[NavigationItem],
    *,
    selected_index: int = 0,
    header: Element | None = None,
    expanded: bool = False,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    destinations = [
        _navigation_destination(
            item,
            selected=index == selected_index,
            vertical=not expanded,
            theme=theme,
        )
        for index, item in enumerate(items)
    ]
    return spaced_column(
        [header, *destinations],
        12,
        width=220 if expanded else 96,
        padding_top=24,
        padding_start=12,
        padding_end=12,
        align_items="center",
        background_color=theme.colors.surface,
        **props,
    )


def NavigationDrawer(
    items: Sequence[NavigationItem],
    *,
    selected_index: int = 0,
    header: Element | None = None,
    footer: Element | None = None,
    modal: bool = False,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    destinations: list[Element] = []
    for index, item in enumerate(items):
        selected = index == selected_index
        enabled = getattr(item, 'enabled', True)
        colors = theme.colors
        if not enabled:
            foreground = alpha(colors.on_surface, 0.38)
        elif selected:
            foreground = colors.on_secondary_container
        else:
            foreground = colors.on_surface_variant
        destinations.append(
            spaced_row(
                [
                    Row(
                        slot(item.selected_icon if selected and item.selected_icon else item.icon, color=foreground, typography=theme.typography.title_large),
                        width=24,
                        height=24,
                        align_items="center",
                        justify_content="center",
                    ),
                    text(
                        item.label,
                        color=foreground,
                        typography=theme.typography.label_large,
                        width=0,
                        lp_weight=1,
                    ),
                    Badge(item.badge, theme=theme) if item.badge is not None else None,
                ],
                12,
                min_height=56,
                padding_start=16,
                padding_end=16,
                align_items="center",
                background_color=theme.colors.secondary_container if selected else "#00000000",
                corner_radius=28,
                ripple_color=alpha(foreground, 0.12),
                enabled=item.enabled,
                on_click=item.on_click if item.enabled else None,
                content_description=item.label,
                width="match_parent",
            )
        )
    drawer_props = {
        "width": 360,
        "padding": 12,
        "corner_radius_top_right": theme.shapes.large if modal else 0,
        "corner_radius_bottom_right": theme.shapes.large if modal else 0,
        "background_color": (
            theme.colors.surface_container_low if modal else theme.colors.surface
        ),
        "elevation": 1 if modal else 0,
        **props,
    }
    return spaced_column([header, *destinations, footer], 4, **drawer_props)


# ---------------------------------------------------------------------------
# Selection controls


def Checkbox(
    checked: bool,
    *,
    on_change: Callback | None = None,
    label: str | None = None,
    indeterminate: bool = False,
    enabled: bool = True,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    control = Row(
        checkmark_canvas(
            checked=checked,
            indeterminate=indeterminate,
            enabled=enabled,
            theme=theme,
        ),
        width=48,
        height=48,
        align_items="center",
        justify_content="center",
        corner_radius=24,
        ripple_color=alpha(theme.colors.primary if checked else theme.colors.on_surface, 0.12),
    )
    foreground = theme.colors.on_surface if enabled else alpha(theme.colors.on_surface, 0.38)
    content = [
        control,
        text(label, color=foreground, typography=theme.typography.body_large) if label else None,
    ]
    return spaced_row(
        content,
        4,
        align_items="center",
        enabled=enabled,
        on_click=value_handler(on_change, not checked) if enabled else None,
        content_description=(f"{label}, " if label else "") + (
            "mixed" if indeterminate else "checked" if checked else "not checked"
        ),
        **props,
    )


def Switch(
    checked: bool,
    *,
    on_change: Callback | None = None,
    label: str | None = None,
    supporting_text: str | None = None,
    enabled: bool = True,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    label_block = None
    if label is not None:
        foreground = theme.colors.on_surface if enabled else alpha(theme.colors.on_surface, 0.38)
        label_block = spaced_column(
            [
                text(label, color=foreground, typography=theme.typography.body_large),
                text(
                    supporting_text,
                    color=theme.colors.on_surface_variant if enabled else foreground,
                    typography=theme.typography.body_medium,
                ) if supporting_text else None,
            ],
            2,
            width=0,
            lp_weight=1,
        )
    return spaced_row(
        [label_block, switch_canvas(checked=checked, enabled=enabled, theme=theme)],
        16,
        min_height=48,
        align_items="center",
        enabled=enabled,
        on_click=value_handler(on_change, not checked) if enabled else None,
        content_description=(f"{label}, " if label else "") + ("on" if checked else "off"),
        **props,
    )


def RadioButton(
    selected: bool,
    *,
    on_select: Callback | None = None,
    value: Any = True,
    label: str | None = None,
    enabled: bool = True,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    control = Row(
        radio_canvas(selected=selected, enabled=enabled, theme=theme),
        width=48,
        height=48,
        align_items="center",
        justify_content="center",
        corner_radius=24,
        ripple_color=alpha(theme.colors.primary if selected else theme.colors.on_surface, 0.12),
    )
    foreground = theme.colors.on_surface if enabled else alpha(theme.colors.on_surface, 0.38)
    return spaced_row(
        [control, text(label, color=foreground, typography=theme.typography.body_large) if label else None],
        4,
        align_items="center",
        enabled=enabled,
        on_click=value_handler(on_select, value) if enabled else None,
        content_description=(f"{label}, " if label else "") + ("selected" if selected else "not selected"),
        **props,
    )


def Chip(
    label: str,
    *,
    variant: str = "assist",
    selected: bool = False,
    elevated: bool = False,
    leading: Element | str | None = None,
    trailing: Element | str | None = None,
    on_click: Callback | None = None,
    on_change: Callback | None = None,
    enabled: bool = True,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    require_choice(variant, name="variant", choices=("assist", "filter", "input", "suggestion"))
    props.setdefault("width", "wrap_content")
    colors = theme.colors
    foreground = (
        colors.on_secondary_container
        if selected
        else colors.on_surface_variant
        if enabled
        else alpha(colors.on_surface, 0.38)
    )
    container = (
        colors.secondary_container
        if selected
        else colors.surface_container_low
        if elevated
        else "#00000000"
    )
    leading_content = "✓" if selected and variant == "filter" and leading is None else leading
    leading_element = slot(
        leading_content,
        color=foreground,
        typography=theme.typography.label_large,
    )
    if variant == "filter":
        # Filter chips reserve the selection-mark slot so toggling them cannot
        # resize the chip or shift the label.
        leading_element = Row(
            leading_element,
            width=18,
            height=18,
            align_items="center",
            justify_content="center",
        )
    handler = value_handler(on_change, not selected) if on_change is not None else on_click
    return spaced_row(
        [
            leading_element,
            text(label, color=foreground, typography=theme.typography.label_large),
            slot(trailing, color=foreground, typography=theme.typography.label_large),
        ],
        8,
        height=32,
        padding_start=12,
        padding_end=12,
        align_items="center",
        background_color=container,
        border_width=0 if selected or elevated else 1,
        border_color=colors.outline,
        corner_radius=8,
        elevation=1 if elevated else 0,
        ripple_color=alpha(foreground, 0.12),
        enabled=enabled,
        on_click=handler if enabled else None,
        content_description=label + (", selected" if selected else ""),
        **props,
    )


def SegmentedButton(
    label: str,
    *,
    selected: bool,
    on_click: Callback | None = None,
    icon: Element | str | None = None,
    enabled: bool = True,
    start: bool = True,
    end: bool = True,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    props.setdefault("width", "wrap_content")
    colors = theme.colors
    foreground = (
        colors.on_secondary_container
        if selected
        else colors.on_surface
        if enabled
        else alpha(colors.on_surface, 0.38)
    )
    leading = "✓" if selected and icon is None else icon
    leading_element = None
    if leading is not None:
        leading_element = Row(
            slot(leading, color=foreground, typography=theme.typography.label_large),
            width=18,
            height=18,
            align_items="center",
            justify_content="center",
        )
    return spaced_row(
        [
            leading_element,
            text(label, color=foreground, typography=theme.typography.label_large),
        ],
        8,
        height=40,
        padding_start=12,
        padding_end=12,
        align_items="center",
        justify_content="center",
        background_color=colors.secondary_container if selected else "#00000000",
        border_width=1,
        border_color=colors.outline,
        corner_radius_top_left=20 if start else 0,
        corner_radius_bottom_left=20 if start else 0,
        corner_radius_top_right=20 if end else 0,
        corner_radius_bottom_right=20 if end else 0,
        ripple_color=alpha(foreground, 0.12),
        enabled=enabled,
        on_click=on_click if enabled else None,
        content_description=label + (", selected" if selected else ""),
        **props,
    )


def SegmentedButtonGroup(
    items: Sequence[SegmentedItem],
    *,
    selected: Any | Sequence[Any],
    on_select: Callback | None = None,
    multi_select: bool = False,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    # Weighted segments need a definite parent width on Android. Give each
    # segment enough room for its selected icon, label, and horizontal inset;
    # callers can still provide a wider explicit width.
    props.setdefault("width", max(80, len(items) * 80))
    item_values = [item.value for item in items]
    normalized = normalize_selection(selected, item_values, multi=multi_select)
    selected_values: set[Any] = set(normalized) if multi_select and normalized else {normalized} if normalized is not None else set()
    children: list[Element] = []
    for index, item in enumerate(items):
        if multi_select:
            next_selection = tuple(
                candidate.value
                for candidate in items
                if (candidate.value in selected_values) != (candidate.value == item.value)
            )
        else:
            next_selection = item.value

        def _make_handler(val: Any) -> Callback | None:
            if on_select is None:
                return None

            def _h(_event: Any) -> None:
                on_select(val)

            return _h
        children.append(
            SegmentedButton(
                item.label,
                icon=item.icon,
                selected=item.value in selected_values,
                on_click=_make_handler(next_selection),
                enabled=item.enabled,
                start=index == 0,
                end=index == len(items) - 1,
                theme=theme,
                width=0,
                lp_weight=1,
            )
        )
    return Row(*children, **props)


# ---------------------------------------------------------------------------
# Sliders
#
# Validators and target lists live in _validation.py (shared across Slider,
# RangeSlider, and any future slider-like controls).


def Slider(
    value: float,
    *,
    minimum: float = 0,
    maximum: float = 1,
    step: float | None = None,
    on_change: Callback | None = None,
    enabled: bool = True,
    width: float = 240,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    # ---- immutable spec (MATERIAL-01) ---------------------------------------
    spec = SliderSpec(minimum=minimum, maximum=maximum, step=step, width=width)
    validated = validate_finite(value, "value")

    # Nearest-step initial normalisation.
    clamped = spec.normalize(validated)
    fraction = (clamped - spec.minimum) / (spec.maximum - spec.minimum)

    # Only build discrete targets when step is set (no dead work for continuous).
    targets = slider_targets(spec)
    # The thumb tracks the controlled value directly. A declarative Canvas
    # target animation is intentionally not used here: the supported
    # animation APIs are imperative and require a mounted view.
    active = theme.colors.primary if enabled else alpha(theme.colors.on_surface, 0.38)
    inactive = theme.colors.secondary_container if enabled else alpha(theme.colors.on_surface, 0.12)
    active_tick = theme.colors.on_primary if enabled else alpha(theme.colors.on_surface, 0.38)
    inactive_tick = theme.colors.on_surface_variant if enabled else alpha(theme.colors.on_surface, 0.38)
    thumb_x = 10 + (spec.width - 20) * fraction
    track_left = 2
    track_right = spec.width - 2
    thumb_gap = 6
    active_width = _clamp(
        thumb_x - thumb_gap - track_left,
        0,
        track_right - track_left,
    )
    inactive_start = _clamp(thumb_x + thumb_gap, track_left, track_right)
    inactive_width = _clamp(
        track_right - inactive_start, 0, track_right - track_left
    )

    # Ticks: only for discrete sliders.
    ticks: list[dict[str, Any]] = []
    if spec.is_discrete and targets:
        for target in targets[1:-1][:99]:
            x = 10 + (spec.width - 20) * (target - spec.minimum) / (spec.maximum - spec.minimum)
            ticks.append({"kind": "circle", "cx": x, "cy": 24, "r": 1, "fill": active_tick if x < thumb_x else inactive_tick})

    track_draw: list[dict[str, Any]] = [
        {"kind": "round_rect", "x": track_left, "y": 16, "width": active_width, "height": 16, "radius": 8, "fill": active},
        {"kind": "round_rect", "x": inactive_start, "y": 16, "width": inactive_width, "height": 16, "radius": 8, "fill": inactive},
        {"kind": "circle", "cx": spec.width - 10, "cy": 24, "r": 2 if fraction < 1 else 0, "fill": active},
    ]
    canvas = Canvas(
        draw=[
            *track_draw,
            *ticks,
            {"kind": "round_rect", "x": thumb_x - 2, "y": 2, "width": 4, "height": 44, "radius": 2, "fill": active},
        ],
        view_box=[0, 0, spec.width, 48],
        width=spec.width,
        height=48,
    )

    # ---- mount-local gesture state (MATERIAL-01) ----------------------------
    gesture = SliderGesture(spec, on_change)

    def _on_pointer_down(event: Any) -> None:
        gesture.down("single", float(event.get("x", thumb_x)))

    def _on_pointer_move(event: Any) -> None:
        pointer_x = float(event.get("x", thumb_x))
        # A controlled value update rerenders this function during the same
        # native pointer session. The listener keeps its mounted identity, but
        # this lightweight Python gesture helper is reconstructed. Resume the
        # already-captured native drag from the first move delivered to the
        # refreshed closure.
        if gesture.phase == "idle":
            gesture.down("single", pointer_x)
        else:
            gesture.move(pointer_x)

    def _on_pointer_up(event: Any) -> None:
        gesture.up()

    def _on_pointer_cancel(event: Any) -> None:
        gesture.cancel()

    pointer_handler_active = enabled and on_change is not None
    pointer_down = _on_pointer_down if pointer_handler_active else None
    pointer_move = latest(_on_pointer_move) if pointer_handler_active else None
    pointer_up = _on_pointer_up if pointer_handler_active else None
    pointer_cancel = _on_pointer_cancel if pointer_handler_active else None

    ripple_color = resolve_ripple_color(
        theme.colors, enabled=enabled, foreground=active,
    )
    return Box(
        canvas,
        width=spec.width,
        height=48,
        enabled=enabled,
        ripple_color=ripple_color,
        pointer_capture_axis="horizontal" if pointer_handler_active else None,
        on_pointer_down=pointer_down,
        on_pointer_move=pointer_move,
        on_pointer_up=pointer_up,
        on_pointer_cancel=pointer_cancel,
        content_description=f"{clamped:g} of {spec.maximum:g}",
        **props,
    )


def RangeSlider(
    values: tuple[float, float],
    *,
    minimum: float = 0,
    maximum: float = 1,
    step: float | None = None,
    on_change: Callback | None = None,
    enabled: bool = True,
    width: float = 240,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    # ---- immutable spec + validated ordered pair (MATERIAL-01) --------------
    spec = SliderSpec(minimum=minimum, maximum=maximum, step=step, width=width)
    start, end = SliderSpec.validate_range_slider_values(values, spec)

    start_fraction = (start - spec.minimum) / (spec.maximum - spec.minimum)
    end_fraction = (end - spec.minimum) / (spec.maximum - spec.minimum)

    targets = slider_targets(spec)
    # The thumbs track the controlled values directly. A declarative Canvas
    # target animation is intentionally not used here: the supported
    # animation APIs are imperative and require a mounted view.
    start_x = 10 + (spec.width - 20) * start_fraction
    end_x = 10 + (spec.width - 20) * end_fraction
    active = theme.colors.primary if enabled else alpha(theme.colors.on_surface, 0.38)
    inactive = theme.colors.secondary_container if enabled else alpha(theme.colors.on_surface, 0.12)
    active_tick = theme.colors.on_primary if enabled else alpha(theme.colors.on_surface, 0.38)
    inactive_tick = theme.colors.on_surface_variant if enabled else alpha(theme.colors.on_surface, 0.38)
    track_left = 2
    track_right = spec.width - 2
    thumb_gap = 6
    left_width = _clamp(
        start_x - thumb_gap - track_left,
        0,
        track_right - track_left,
    )
    active_start = _clamp(start_x + thumb_gap, track_left, track_right)
    active_width = _clamp(
        end_x - start_x - thumb_gap * 2,
        0,
        track_right - track_left,
    )
    right_start = _clamp(end_x + thumb_gap, track_left, track_right)
    right_width = _clamp(
        track_right - right_start, 0, track_right - track_left
    )
    track_draw: list[dict[str, Any]] = [
        {"kind": "round_rect", "x": track_left, "y": 16, "width": left_width, "height": 16, "radius": 8, "fill": inactive},
        {"kind": "round_rect", "x": active_start, "y": 16, "width": active_width, "height": 16, "radius": 8, "fill": active},
        {"kind": "round_rect", "x": right_start, "y": 16, "width": right_width, "height": 16, "radius": 8, "fill": inactive},
        {"kind": "circle", "cx": 10, "cy": 24, "r": 2 if start_fraction > 0 else 0, "fill": active},
        {"kind": "circle", "cx": spec.width - 10, "cy": 24, "r": 2 if end_fraction < 1 else 0, "fill": active},
    ]
    ticks: list[dict[str, Any]] = []
    if spec.is_discrete and targets:
        ticks = [
            {
                "kind": "circle",
                "cx": 10 + (spec.width - 20) * (target - spec.minimum) / (spec.maximum - spec.minimum),
                "cy": 24,
                "r": 1,
                "fill": active_tick if start < target < end else inactive_tick,
            }
            for target in targets[1:-1][:99]
        ]
    canvas = Canvas(
        draw=[
            *track_draw,
            *ticks,
            {"kind": "round_rect", "x": start_x - 2, "y": 2, "width": 4, "height": 44, "radius": 2, "fill": active},
            {"kind": "round_rect", "x": end_x - 2, "y": 2, "width": 4, "height": 44, "radius": 2, "fill": active},
        ],
        view_box=[0, 0, spec.width, 48],
        width=spec.width,
        height=48,
    )

    midpoint_x = (start_x + end_x) / 2

    # ---- mount-local gesture state (MATERIAL-01) ----------------------------
    range_gesture = RangeSliderGesture(spec, on_change, start, end)

    def _make_handler(method: Any, offset: float = 0.0) -> Any:
        def _h(event: Any) -> None:
            method(offset + float(event.get("x", 0)))
        return _h

    start_handler = enabled and on_change is not None
    end_handler = enabled and on_change is not None

    start_touch_target = Box(
        width=midpoint_x,
        height=48,
        pointer_capture_axis="horizontal",
        on_pointer_down=_make_handler(range_gesture.down_start) if start_handler else None,
        on_pointer_move=latest(_make_handler(range_gesture.move_start)) if start_handler else None,
        on_pointer_up=_make_handler(range_gesture.up_start) if start_handler else None,
        on_pointer_cancel=_make_handler(range_gesture.cancel_start) if start_handler else None,
    ) if start_handler else None
    end_touch_target = Box(
        width=spec.width - midpoint_x,
        height=48,
        translation_x=midpoint_x,
        pointer_capture_axis="horizontal",
        on_pointer_down=_make_handler(range_gesture.down_end, midpoint_x) if end_handler else None,
        on_pointer_move=latest(_make_handler(range_gesture.move_end, midpoint_x)) if end_handler else None,
        on_pointer_up=_make_handler(range_gesture.up_end) if end_handler else None,
        on_pointer_cancel=_make_handler(range_gesture.cancel_end) if end_handler else None,
    ) if end_handler else None

    ripple_color = resolve_ripple_color(
        theme.colors, enabled=enabled, foreground=active,
    )
    return Box(
        canvas,
        start_touch_target,
        end_touch_target,
        width=spec.width,
        height=48,
        enabled=enabled,
        ripple_color=ripple_color,
        content_description=f"{start:g} to {end:g}",
        **props,
    )


# ---------------------------------------------------------------------------
# Text fields and search


def TextField(
    *,
    value: str = "",
    label: str | None = None,
    placeholder: str | None = None,
    supporting_text: str | None = None,
    error_text: str | None = None,
    leading: Element | str | None = None,
    trailing: Element | str | None = None,
    prefix: str | None = None,
    suffix: str | None = None,
    variant: str = "filled",
    enabled: bool = True,
    focused: bool | None = None,
    blur_on_keyboard_hide: bool = True,
    blur_on_tap_outside: bool = True,
    blur_on_submit: bool = True,
    on_text_change: Callback | None = None,
    on_editor_action: Callback | None = None,
    on_focus_change: Callback | None = None,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    require_choice(variant, name="variant", choices=("filled", "outlined"))
    colors = theme.colors
    is_error = error_text is not None
    accent = colors.error if is_error else colors.primary
    foreground = colors.on_surface if enabled else alpha(colors.on_surface, 0.38)
    label_color = accent if focused or is_error else colors.on_surface_variant
    floating_label = (
        text(label, color=label_color, typography=theme.typography.body_small)
        if label and (focused or value)
        else None
    )
    # Controlled callbacks receive the proposed next value directly.
    input_props: dict[str, Any] = {
        "text": value,
        "hint": placeholder or (label if not floating_label else ""),
        "text_color": foreground,
        "font_size": theme.typography.body_large.font_size,
        "enabled": enabled,
        "blur_on_keyboard_hide": blur_on_keyboard_hide,
        "blur_on_tap_outside": blur_on_tap_outside,
        "blur_on_submit": blur_on_submit,
        "background_color": "#00000000",
        "width": 0,
        "lp_weight": 1,
        "on_text_change": (
            (lambda event: on_text_change(event.get("text", "")))
            if on_text_change is not None
            else None
        ),
        "on_editor_action": (
            (lambda event: on_editor_action(event.get("text", value)))
            if on_editor_action is not None
            else None
        ),
        "on_focus_change": (
            (lambda event: on_focus_change(bool(event.get("has_focus"))))
            if on_focus_change is not None
            else None
        ),
    }
    if focused is not None:
        input_props["focused"] = focused
    input_element = TextInput(**input_props)
    leading_element = slot(leading, color=colors.on_surface_variant, typography=theme.typography.title_large)
    trailing_element = slot(trailing, color=colors.on_surface_variant, typography=theme.typography.title_large)
    if leading_element is not None:
        leading_element = Row(
            leading_element,
            width=24,
            height=24,
            align_items="center",
            justify_content="center",
        )
    if trailing_element is not None:
        trailing_element = Row(
            trailing_element,
            width=24,
            height=24,
            align_items="center",
            justify_content="center",
        )
    input_row = spaced_row(
        [
            leading_element,
            text(prefix, color=colors.on_surface_variant, typography=theme.typography.body_large) if prefix else None,
            input_element,
            text(suffix, color=colors.on_surface_variant, typography=theme.typography.body_large) if suffix else None,
            trailing_element,
        ],
        8,
        min_height=56,
        padding_start=16,
        padding_end=16,
        padding_top=8 if floating_label else 0,
        align_items="center",
        width="match_parent",
    )
    floating_label_host = None
    if floating_label is not None and label is not None:
        # Native wrap-content: let the Row size to its Text child naturally.
        # No ``len(label) * constant`` estimate (MATERIAL-04).
        floating_label_host = Row(
            floating_label,
            padding_start=4,
            padding_end=4,
            align_items="center",
            justify_content="center",
            background_color=colors.surface if variant == "outlined" else "#00000000",
            translation_x=12,
            translation_y=-8 if variant == "outlined" else 4,
        )
    indicator = (
        Box(
            height=2 if focused or is_error else 1,
            width="match_parent",
            background_color=accent if focused or is_error else colors.on_surface_variant,
            lp_gravity="bottom",
        )
        if variant == "filled"
        else None
    )
    field = Box(
        input_row,
        floating_label_host,
        indicator,
        min_height=56,
        width="match_parent",
        background_color=colors.surface_container_highest if variant == "filled" else "#00000000",
        border_width=(2 if focused or is_error else 1) if variant == "outlined" else 0,
        border_color=accent if focused or is_error else colors.outline,
        corner_radius_top_left=theme.shapes.extra_small,
        corner_radius_top_right=theme.shapes.extra_small,
        corner_radius_bottom_left=theme.shapes.extra_small if variant == "outlined" else 0,
        corner_radius_bottom_right=theme.shapes.extra_small if variant == "outlined" else 0,
        overflow="visible",
    )
    support = error_text or supporting_text
    if variant == "outlined":
        # Reserve the half-label height which intentionally sits above the
        # outline.  Keeping this space even before focus prevents reflow.
        # Keep a little breathing room beyond the exact half-label height;
        # Android font metrics can extend above the nominal line box.
        props.setdefault("padding_top", 10)
    return spaced_column(
        [
            field,
            text(
                support,
                color=colors.error if is_error else colors.on_surface_variant,
                typography=theme.typography.body_small,
                margin_start=16,
                margin_end=16,
            ) if support else None,
        ],
        4,
        **props,
    )


def SearchBar(
    *,
    query: str = "",
    placeholder: str = "Search",
    expanded: bool = False,
    on_query_change: Callback | None = None,
    on_search: Callback | None = None,
    on_expanded_change: Callback | None = None,
    leading: Element | str = "⌕",
    trailing: Sequence[Element] = (),
    results: Sequence[Element] = (),
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    # Controlled callbacks receive the proposed next value directly.
    input_element = TextInput(
        text=query,
        hint=placeholder,
        text_color=theme.colors.on_surface,
        font_size=theme.typography.body_large.font_size,
        background_color="#00000000",
        width=0,
        lp_weight=1,
        on_text_change=(
            (lambda event: on_query_change(event.get("text", "")))
            if on_query_change is not None
            else None
        ),
        on_editor_action=(
            (lambda event: on_search(event.get("text", query)))
            if on_search is not None
            else None
        ),
        on_focus_change=(
            (lambda event: on_expanded_change(bool(event.get("has_focus"))))
            if on_expanded_change is not None
            else None
        ),
    )
    bar = spaced_row(
        [
            slot(leading, color=theme.colors.on_surface, typography=theme.typography.title_large),
            input_element,
            *trailing,
        ],
        8,
        min_height=56,
        padding_start=16,
        padding_end=16,
        align_items="center",
        background_color=theme.colors.surface_container_high,
        corner_radius=28,
        elevation=1,
        on_click=value_handler(on_expanded_change, True),
        width="match_parent",
    )
    if not expanded:
        return Box(bar, **props)
    return spaced_column(
        [bar, *results],
        4,
        padding=8,
        corner_radius=28,
        background_color=theme.colors.surface_container_high,
        elevation=6,
        **props,
    )


# ---------------------------------------------------------------------------
# Pickers
# ---------------------------------------------------------------------------


def _safe_month_calendar(
    year: int, month: int, first_weekday: int
) -> list[list[date | None]]:
    """Build a safe month-grid of dates without constructing year 0/10000.

    Returns a list of weeks, each a list of ``date`` or ``None`` (for
    boundary cells that would fall outside the valid date range).
    """
    cal = calendar.Calendar(firstweekday=first_weekday)
    # Build week lists from monthdatescalendar but guard each date.
    try:
        raw_weeks = cal.monthdatescalendar(year, month)
    except (ValueError, OverflowError):
        raw_weeks = cal.monthdayscalendar(year, month)
        # Fallback to day-number tuples for extreme boundary months.
        result: list[list[date | None]] = []
        for week_days in raw_weeks:
            week: list[date | None] = []
            for day_num in week_days:
                if day_num == 0:
                    week.append(None)
                    continue
                try:
                    week.append(date(year, month, day_num))
                except ValueError:
                    week.append(None)
            result.append(week)
        return result

    # Guard each date in the raw weeks.
    result = []
    for raw_week in raw_weeks:
        week: list[date | None] = []
        for d in raw_week:
            if d.year < date.min.year or d.year > date.max.year:
                week.append(None)
            else:
                week.append(d)
        result.append(week)
    return result


@component
def _DatePickerCell(
    day_value: date,
    *,
    in_month: bool,
    selected: bool,
    in_range: bool,
    selection_value: Any,
    on_activate: Callback | None,
    theme: MaterialTheme,
) -> Element:
    """One independently cached calendar cell.

    Selection changes usually invalidate only the old and new cells instead
    of rebuilding all 35–42 cells in the month grid.
    """
    foreground = (
        theme.colors.on_primary
        if selected
        else theme.colors.on_secondary_container
        if in_range
        else theme.colors.on_surface
        if in_month
        else alpha(theme.colors.on_surface, 0.38)
    )
    return Row(
        text(str(day_value.day), color=foreground, typography=theme.typography.body_medium, align="center"),
        width=40,
        height=40,
        align_items="center",
        justify_content="center",
        corner_radius=20,
        background_color=(
            theme.colors.primary
            if selected
            else theme.colors.secondary_container
            if in_range
            else "#00000000"
        ),
        ripple_color=alpha(theme.colors.primary, 0.12),
        on_click=value_handler(on_activate, selection_value) if in_month else None,
        enabled=in_month,
        content_description=day_value.isoformat(),
    )


@component
def _DatePickerWeek(
    cell_specs: tuple[tuple[Any, ...] | None, ...],
    theme: MaterialTheme,
) -> Element:
    cells: list[Element] = []
    for spec in cell_specs:
        if spec is None:
            cells.append(Box(width=40, height=40))
            continue
        day_value, in_month, selected, in_range, selection_value, on_activate = spec
        cells.append(
            _DatePickerCell(
                day_value,
                in_month=in_month,
                selected=selected,
                in_range=in_range,
                selection_value=selection_value,
                on_activate=on_activate,
                theme=theme,
            )
        )
    return Row(*cells, justify_content="center")


@component
def _DatePickerWeekdays(first_weekday: int, theme: MaterialTheme) -> Element:
    names = list(calendar.day_abbr)
    names = names[first_weekday:] + names[:first_weekday]
    return Row(
        *[
            text(name[:1], color=theme.colors.on_surface_variant, typography=theme.typography.body_small, width=40, align="center")
            for name in names
        ],
        justify_content="center",
    )


@component
def _DatePickerHeader(
    year: int,
    month: int,
    previous: tuple[int, int],
    following: tuple[int, int],
    prev_enabled: bool,
    next_enabled: bool,
    on_month_change: Callback | None,
    theme: MaterialTheme,
) -> Element:
    return spaced_row(
        [
            IconButton(
                "‹",
                on_click=value_handler(on_month_change, previous) if prev_enabled else None,
                enabled=prev_enabled,
                content_description="Previous month",
                theme=theme,
            ),
            text(
                f"{calendar.month_name[month]} {year}",
                color=theme.colors.on_surface,
                typography=theme.typography.title_large,
                width=0,
                lp_weight=1,
                align="center",
            ),
            IconButton(
                "›",
                on_click=value_handler(on_month_change, following) if next_enabled else None,
                enabled=next_enabled,
                content_description="Next month",
                theme=theme,
            ),
        ],
        8,
        align_items="center",
    )



def DatePicker(
    *,
    year: int,
    month: int,
    selected: date | None = None,
    on_select: Callback | None = None,
    selected_range: tuple[date | None, date | None] | None = None,
    on_range_select: Callback | None = None,
    on_month_change: Callback | None = None,
    first_weekday: int = 0,
    show_actions: bool = False,
    actions: Sequence[Element] = (),
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    # ---- boundary-safe validation (MATERIAL-02) --------------------------
    if not isinstance(year, int) or isinstance(year, bool):
        raise TypeError(f"year must be an int, got {type(year).__name__}")
    if not isinstance(month, int) or isinstance(month, bool):
        raise TypeError(f"month must be an int, got {type(month).__name__}")
    if not isinstance(first_weekday, int) or isinstance(first_weekday, bool):
        raise TypeError(f"first_weekday must be an int, got {type(first_weekday).__name__}")

    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")
    if not 0 <= first_weekday <= 6:
        raise ValueError("first_weekday must be between 0 and 6")
    if year < date.min.year or year > date.max.year:
        raise ValueError(
            f"year must be between {date.min.year} and {date.max.year}, got {year}"
        )
    if selected is not None:
        if not isinstance(selected, date):
            raise TypeError(f"selected must be a date or None, got {type(selected).__name__}")
        if selected < date.min or selected > date.max:
            raise ValueError(f"selected date {selected} is outside {date.min}..{date.max}")
    if selected_range is not None:
        if not isinstance(selected_range, tuple) or len(selected_range) != 2:
            raise TypeError("selected_range must be a tuple of (start, end)")
        r0, r1 = selected_range
        for i, v in enumerate((r0, r1)):
            if v is not None and not isinstance(v, date):
                raise TypeError(f"selected_range[{i}] must be date or None, got {type(v).__name__}")
        if r0 is not None and r1 is not None and r0 > r1:
            raise ValueError(f"selected_range start {r0} is after end {r1}")

    # ---- build a safe calendar grid without constructing year 0/10000 -----
    weeks = _safe_month_calendar(year, month, first_weekday)
    previous = (year - 1, 12) if month == 1 else (year, month - 1)
    following = (year + 1, 1) if month == 12 else (year, month + 1)
    # Disable boundary navigation.
    at_min = year == date.min.year and month == date.min.month
    at_max = year == date.max.year and month == date.max.month
    prev_enabled = not at_min
    next_enabled = not at_max

    header = _DatePickerHeader(
        year,
        month,
        previous,
        following,
        prev_enabled,
        next_enabled,
        on_month_change,
        theme,
    )
    weekday_row = _DatePickerWeekdays(first_weekday, theme)
    week_rows: list[Element] = []
    range_start, range_end = selected_range or (None, None)
    for week in weeks:
        cell_specs: list[tuple[Any, ...] | None] = []
        for day_val in week:
            if day_val is None:
                # Placeholder for boundary cells (no year 0/10000 dates).
                cell_specs.append(None)
                continue
            in_month = day_val.month == month
            is_endpoint = day_val == range_start or day_val == range_end
            is_in_range = (
                range_start is not None
                and range_end is not None
                and range_start <= day_val <= range_end
            )
            is_selected = selected == day_val or is_endpoint
            if on_range_select is not None:
                if range_start is None or range_end is not None:
                    next_selection = (day_val, None)
                elif day_val < range_start:
                    next_selection = (day_val, range_start)
                else:
                    next_selection = (range_start, day_val)
                on_activate = on_range_select
            else:
                next_selection = day_val
                on_activate = on_select
            cell_specs.append(
                (day_val, in_month, is_selected, is_in_range, next_selection, on_activate)
            )
        week_rows.append(_DatePickerWeek(tuple(cell_specs), theme))
    action_row = spaced_row(actions, 8, justify_content="end") if show_actions and actions else None
    return spaced_column(
        [header, weekday_row, *week_rows, action_row],
        8,
        width=328,
        padding=12,
        background_color=theme.colors.surface_container_high,
        corner_radius=theme.shapes.extra_large,
        elevation=6,
        **props,
    )


def DateRangePicker(
    *,
    year: int,
    month: int,
    start: date | None = None,
    end: date | None = None,
    on_change: Callback | None = None,
    **props: Any,
) -> Element:
    return DatePicker(
        year=year,
        month=month,
        selected_range=(start, end),
        on_range_select=on_change,
        **props,
    )


@component
def _TimePickerDialCell(
    label: str,
    *,
    selected: bool,
    next_time: tuple[int, int],
    on_change: Callback | None,
    x: float,
    y: float,
    theme: MaterialTheme,
) -> Element:
    return Row(
        text(
            label,
            color=theme.colors.on_primary if selected else theme.colors.on_surface,
            typography=theme.typography.body_large,
            align="center",
        ),
        width=36,
        height=36,
        align_items="center",
        justify_content="center",
        corner_radius=18,
        background_color=theme.colors.primary if selected else "#00000000",
        translation_x=x,
        translation_y=y,
        on_click=value_handler(on_change, next_time),
        content_description=label,
    )


@component
def _TimePickerPeriod(
    period: str,
    hour: int,
    minute: int,
    on_change: Callback | None,
    theme: MaterialTheme,
) -> Element:
    def change_period(value: str) -> None:
        next_hour = (
            (hour + 12) % 24
            if value == "pm" and hour < 12
            else hour % 12
            if value == "am" and hour >= 12
            else hour
        )
        invoke(on_change, (next_hour, minute))

    return SegmentedButtonGroup(
        [SegmentedItem("AM", "am"), SegmentedItem("PM", "pm")],
        selected=period,
        on_select=change_period,
        theme=theme,
    )


def TimePicker(
    *,
    hour: int,
    minute: int,
    selection: str = "hour",
    is_24_hour: bool = False,
    on_change: Callback | None = None,
    on_selection_change: Callback | None = None,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    require_choice(selection, name="selection", choices=("hour", "minute"))
    if not 0 <= hour <= 23:
        raise ValueError("hour must be between 0 and 23")
    if not 0 <= minute <= 59:
        raise ValueError("minute must be between 0 and 59")
    display_hour = hour if is_24_hour else (hour % 12 or 12)

    def time_selector(value: str, target: str) -> Element:
        selected = selection == target
        return Row(
            text(
                value,
                color=(
                    theme.colors.on_primary_container
                    if selected
                    else theme.colors.on_surface
                ),
                typography=theme.typography.display_medium,
            ),
            width=96,
            height=72,
            align_items="center",
            justify_content="center",
            background_color=(
                theme.colors.primary_container
                if selected
                else theme.colors.surface_container_highest
            ),
            corner_radius=theme.shapes.small,
            ripple_color=alpha(theme.colors.primary, 0.12),
            on_click=value_handler(on_selection_change, target),
            content_description=f"Select {target}",
        )

    header = spaced_row(
        [
            time_selector(str(display_hour).zfill(2), "hour"),
            text(":", color=theme.colors.on_surface, typography=theme.typography.display_medium),
            time_selector(str(minute).zfill(2), "minute"),
        ],
        8,
        align_items="center",
        justify_content="center",
    )
    dial_values = (
        list(range(0, 24))
        if is_24_hour and selection == "hour"
        else [12, *range(1, 12)]
        if selection == "hour"
        else list(range(0, 60, 5))
    )
    visible_values = dial_values
    dial_children: list[Element] = [
        Canvas(
            draw=[{"kind": "circle", "cx": 128, "cy": 128, "r": 126, "fill": theme.colors.surface_container_highest}],
            view_box=[0, 0, 256, 256],
            width=256,
            height=256,
        )
    ]
    current = hour if is_24_hour and selection == "hour" else display_hour if selection == "hour" else minute - minute % 5
    for index, dial_value in enumerate(visible_values):
        ring_index = index // 12
        angle = ((index % 12) / 12) * math.tau - math.pi / 2
        radius = 86 if ring_index == 0 else 54
        x = 110 + math.cos(angle) * radius
        y = 110 + math.sin(angle) * radius
        selected_value = dial_value == current
        next_hour = (
            dial_value
            if is_24_hour
            else (dial_value % 12) + (12 if hour >= 12 else 0)
        )
        next_time = (next_hour, minute) if selection == "hour" else (hour, dial_value)
        dial_children.append(
            _TimePickerDialCell(
                str(dial_value).zfill(2) if selection == "minute" else str(dial_value),
                selected=selected_value,
                next_time=next_time,
                on_change=on_change,
                x=x,
                y=y,
                theme=theme,
            )
        )
    dial = Box(*dial_children, width=256, height=256)
    period = None
    if not is_24_hour:
        period = _TimePickerPeriod(
            "pm" if hour >= 12 else "am",
            hour,
            minute,
            on_change,
            theme,
        )
    return spaced_column(
        [header, dial, period],
        16,
        width=328,
        padding=24,
        align_items="center",
        background_color=theme.colors.surface_container_high,
        corner_radius=theme.shapes.extra_large,
        **props,
    )


# ---------------------------------------------------------------------------
# Communication


def Snackbar(
    message: str,
    *,
    action_label: str | None = None,
    on_action: Callback | None = None,
    on_dismiss: Callback | None = None,
    icon: Element | str | None = None,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    """Complete inverse color scheme for Snackbar (MATERIAL-03).

    Uses the full ``inverse_*`` palette: surface, on_surface, primary.
    M3 requires the inverse family, not isolated field replacements.
    """
    colors = theme.colors
    # Full inverse theme: every color slot needed for the bar content.
    inverse_colors = replace(
        colors,
        primary=colors.inverse_primary,
        on_primary=colors.inverse_on_surface,
        on_surface=colors.inverse_on_surface,
        on_surface_variant=alpha(colors.inverse_on_surface, 0.74),
        surface=colors.inverse_surface,
        surface_container=colors.inverse_surface,
        surface_container_low=colors.inverse_surface,
        surface_container_high=colors.inverse_surface,
    )
    inverse_theme = replace(theme, colors=inverse_colors)
    action = (
        Button(action_label, on_click=on_action, variant="text", theme=inverse_theme)
        if action_label
        else None
    )
    dismiss = (
        IconButton("×", on_click=on_dismiss, content_description="Dismiss", theme=inverse_theme)
        if on_dismiss
        else None
    )
    return spaced_row(
        [
            slot(icon, color=colors.inverse_on_surface, typography=theme.typography.title_large),
            text(message, color=colors.inverse_on_surface, typography=theme.typography.body_medium, width=0, lp_weight=1),
            action,
            dismiss,
        ],
        8,
        min_height=48,
        padding_start=16,
        padding_end=8,
        align_items="center",
        background_color=colors.inverse_surface,
        corner_radius=theme.shapes.extra_small,
        elevation=3,
        **props,
    )


def Tooltip(
    anchor: Element,
    text_value: str,
    *,
    visible: bool = False,
    rich: bool = False,
    supporting_text: str | None = None,
    action: Element | None = None,
    on_show: Callback | None = None,
    on_dismiss: Callback | None = None,
    placement: str = "above",
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    require_choice(placement, name="placement", choices=("above", "below"))
    anchor_host = Row(
        anchor,
        align_items="center",
        justify_content="center",
        on_long_click=value_handler(on_show, True),
        content_description="Show tooltip" if on_show else None,
    )
    bubble = None
    if visible:
        if rich:
            bubble = spaced_column(
                [
                    text(text_value, color=theme.colors.on_surface_variant, typography=theme.typography.title_small),
                    text(supporting_text, color=theme.colors.on_surface_variant, typography=theme.typography.body_medium) if supporting_text else None,
                    action,
                ],
                8,
                width=240,
                min_width=200,
                padding=16,
                corner_radius=theme.shapes.medium,
                background_color=theme.colors.surface_container,
                elevation=2,
                on_click=value_handler(on_dismiss, False),
            )
        else:
            # Native wrap-content: use ``width`` as an upper bound and
            # ``min_width`` for the lower bound, instead of
            # ``len(text_value) * constant`` estimate (MATERIAL-04).
            bubble = Box(
                text(text_value, color=theme.colors.inverse_on_surface, typography=theme.typography.body_small),
                min_width=40,
                width=320,
                padding_start=8,
                padding_end=8,
                padding_top=4,
                padding_bottom=4,
                corner_radius=theme.shapes.extra_small,
                background_color=theme.colors.inverse_surface,
                on_click=value_handler(on_dismiss, False),
            )
    children = [bubble, anchor_host] if placement == "above" else [anchor_host, bubble]
    return spaced_column(children, 4, align_items="center", **props)


# ---------------------------------------------------------------------------
# Tabs and toolbars


def Tab(
    label: str,
    *,
    selected: bool,
    icon: Element | str | None = None,
    on_click: Callback | None = None,
    enabled: bool = True,
    secondary: bool = False,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    foreground = (
        theme.colors.primary
        if selected
        else theme.colors.on_surface_variant
        if enabled
        else alpha(theme.colors.on_surface, 0.38)
    )
    icon_content = slot(icon, color=foreground, typography=theme.typography.title_large)
    label_content = text(
        label,
        color=foreground,
        typography=theme.typography.label_large,
        align="center",
    )
    content = (
        spaced_row(
            [
                Row(
                    icon_content,
                    width=24,
                    height=24,
                    align_items="center",
                    justify_content="center",
                ) if icon_content is not None else None,
                label_content,
            ],
            8,
            align_items="center",
            justify_content="center",
            lp_gravity="center",
        )
        if secondary
        else spaced_column(
            [
                Row(
                    icon_content,
                    height=24,
                    align_items="center",
                    justify_content="center",
                ) if icon_content is not None else None,
                Row(
                    label_content,
                    height=theme.typography.label_large.line_height,
                    align_items="center",
                    justify_content="center",
                ),
            ],
            2,
            align_items="center",
            justify_content="center",
            lp_gravity="center",
        )
    )
    indicator = Box(
        width=24 if not secondary else 64,
        height=3,
        corner_radius_top_left=3,
        corner_radius_top_right=3,
        background_color=theme.colors.primary,
        visible=selected,
    )
    indicator_host = Row(
        indicator,
        width="match_parent",
        height=3,
        justify_content="center",
        lp_gravity="bottom",
    )
    return Box(
        content,
        indicator_host,
        min_width=64,
        height=48 if secondary else 64,
        padding_start=12,
        padding_end=12,
        ripple_color=alpha(foreground, 0.12),
        enabled=enabled,
        on_click=on_click if enabled else None,
        content_description=label + (", selected" if selected else ""),
        **props,
    )


def Tabs(
    items: Sequence[TabItem],
    *,
    selected_index: int = 0,
    on_select: Callback | None = None,
    secondary: bool = False,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    children = [
        Tab(
            item.label,
            icon=item.icon,
            selected=index == selected_index,
            on_click=value_handler(on_select, index),
            enabled=item.enabled,
            secondary=secondary,
            theme=theme,
            width=0,
            lp_weight=1,
        )
        for index, item in enumerate(items)
    ]
    return Row(
        *children,
        background_color=theme.colors.surface,
        border_width=0,
        **props,
    )


def Toolbar(
    *actions: Element,
    orientation: str = "horizontal",
    floating: bool = True,
    leading: Element | None = None,
    trailing: Element | None = None,
    theme: MaterialTheme = DEFAULT_THEME,
    **props: Any,
) -> Element:
    require_choice(orientation, name="orientation", choices=("horizontal", "vertical"))
    layout = spaced_row if orientation == "horizontal" else spaced_column
    props.setdefault("justify_content", "center")
    return layout(
        [leading, *actions, trailing],
        4,
        min_height=64 if orientation == "horizontal" else 0,
        min_width=64 if orientation == "vertical" else 0,
        padding=8,
        align_items="center",
        background_color=theme.colors.surface_container,
        corner_radius=32 if floating else 0,
        elevation=3 if floating else 0,
        **props,
    )


def FloatingToolbar(*actions: Element, **kwargs: Any) -> Element:
    kwargs["floating"] = True
    return Toolbar(*actions, **kwargs)
