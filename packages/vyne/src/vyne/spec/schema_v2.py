"""Authoritative schema for all primitives, props, events, and Canvas ops.

This is the **only semantic source** for primitive/Canvas/property/event/
animation eligibility. Runtime validation, Kotlin contracts, and docs consume
or fixture-compare against this module's registries.

Wire primitives: ``Box``, ``Layout``, ``Scroll``, ``Text``, ``TextInput``,
``Image``, ``Path``, ``Canvas``.  ``Row`` and ``Column`` are Python
conveniences that lower to valid primitives.
"""

from __future__ import annotations

from typing import Any

from vyne.spec.model import (
    CanvasOpSpec,
    EventSpec,
    KindSpec,
    PropSpec,
    ValueSpec,
)

# ---------------------------------------------------------------------------
# Value domains
# ---------------------------------------------------------------------------

_finite_number = ValueSpec(finite=True)
_positive_number = ValueSpec(finite=True, positive=True)
_non_negative_number = ValueSpec(finite=True, non_negative=True)
_finite_0_1 = ValueSpec(finite=True, non_negative=True, min_value=0.0, max_value=1.0)
_color = ValueSpec(type_name="str", color=True)
_bool = ValueSpec(type_name="bool", exact_types=(bool,))
_string = ValueSpec(type_name="str", exact_types=(str,))
_string_or_number = ValueSpec(exact_types=(str, int, float))
_dimension = ValueSpec(exact_types=(str, int, float), dimension=True)
_nullable_string = ValueSpec(type_name="str", exact_types=(str,), nullable=True)

_orientation = ValueSpec(type_name="str", enum=frozenset({"horizontal", "vertical"}))
_overflow = ValueSpec(type_name="str", enum=frozenset({"visible", "hidden"}))
_alignment = ValueSpec(type_name="str", enum=frozenset({
    "start", "center", "end", "stretch",
}))
_layout_gravity = ValueSpec(type_name="str", enum=frozenset({
    "start", "center", "end", "top", "bottom",
    "center_horizontal", "center_vertical",
    "top|start", "top|end", "bottom|start", "bottom|end",
}))
_justify = ValueSpec(type_name="str", enum=frozenset({
    "start", "center", "end", "space_between", "space_around", "space_evenly",
}))
_text_direction = ValueSpec(type_name="str", enum=frozenset({
    "ltr", "rtl", "inherit",
}))
_image_scale = ValueSpec(type_name="str", enum=frozenset({
    "center_crop", "fit_center", "center_inside",
}))
_line_cap = ValueSpec(type_name="str", enum=frozenset({"butt", "round", "square"}))
_line_join = ValueSpec(type_name="str", enum=frozenset({"miter", "round", "bevel"}))

_dash_array = ValueSpec(dash_array=True)

_pointer_axis = ValueSpec(type_name="str", enum=frozenset({"horizontal", "vertical"}))

# Private virtual-list sticky edge: which viewport edge the cell sticks to.
# Absent (None) means the cell is not sticky.
_sticky_edge = ValueSpec(type_name="str", enum=frozenset({"start", "end"}),
                         nullable=True)

_accessibility_role = ValueSpec(type_name="str", enum=frozenset({
    "none", "button", "link", "search", "image", "keyboard_key",
    "text", "adjustable", "header", "tab", "checkbox", "radio_button",
    "switch", "dropdown_list", "toolbar", "progress_bar", "slider",
}))

# ---------------------------------------------------------------------------
# Property definitions
# ---------------------------------------------------------------------------

# -- Text-only alignment (no stretch; leaf text alignment) ------------------
_text_align = ValueSpec(type_name="str", enum=frozenset({"start", "center", "end"}))
# -- Container-only layout props --------------------------------------------
_CONTAINER_KINDS = frozenset({"Box", "Layout", "Scroll", "HorizontalScroll"})

# -- Generic (shared) properties --------------------------------------------

_generic_props: list[PropSpec] = [
    # Dimensions
    PropSpec("width", _dimension, default="wrap_content", animatable=True,
             wire_name="layout_width"),
    PropSpec("height", _dimension, default="wrap_content", animatable=True,
             wire_name="layout_height"),
    PropSpec("min_width", _non_negative_number, default=0,
             wire_name="minimumWidth", drop_default=True),
    PropSpec("min_height", _non_negative_number, default=0,
             wire_name="minimumHeight", drop_default=True),
    PropSpec("max_width", _non_negative_number, default=0,
             wire_name="maxWidth", drop_default=True,
             applies_to=_CONTAINER_KINDS),
    PropSpec("max_height", _non_negative_number, default=0,
             wire_name="maxHeight", drop_default=True,
             applies_to=_CONTAINER_KINDS),
    # Private list marker. Android applies the offset once when the scroll
    # content is first laid out; Python keeps publishing the current window
    # offset through reconciliation.
    PropSpec("_virtual_list_initial_offset", _non_negative_number, default=0,
             wire_name="_virtualListInitialOffset", drop_default=True,
             applies_to=frozenset({"Scroll", "HorizontalScroll"})),
    # Platform-neutral request for a host-native draggable scroll indicator.
    # Plain Scroll opts in; List and VirtualList publish True by default.
    PropSpec("interactive_scrollbar", _bool, default=False,
             wire_name="interactiveScrollbar", drop_default=True,
             applies_to=frozenset({"Scroll", "HorizontalScroll"})),
    # Padding (resolved to individual edges by lowering)
    PropSpec("padding_top", _non_negative_number, default=0,
             wire_name="paddingTop", drop_default=True),
    PropSpec("padding_bottom", _non_negative_number, default=0,
             wire_name="paddingBottom", drop_default=True),
    PropSpec("padding_start", _non_negative_number, default=0,
             wire_name="paddingStart", drop_default=True),
    PropSpec("padding_end", _non_negative_number, default=0,
             wire_name="paddingEnd", drop_default=True),
    # Margins
    PropSpec("margin_top", _non_negative_number, default=0,
             wire_name="marginTop", drop_default=True),
    PropSpec("margin_bottom", _non_negative_number, default=0,
             wire_name="marginBottom", drop_default=True),
    PropSpec("margin_start", _non_negative_number, default=0,
             wire_name="marginStart", drop_default=True),
    PropSpec("margin_end", _non_negative_number, default=0,
             wire_name="marginEnd", drop_default=True),
    # Background / border
    PropSpec("background_color", _color, default="#00000000",
             wire_name="backgroundColor", drop_default=True),
    PropSpec("border_width", _non_negative_number, default=0,
             wire_name="borderWidth", drop_default=True),
    PropSpec("border_color", _color, default="#00000000",
             wire_name="borderColor", drop_default=True),
    # Corner radii (resolved to individual corners by lowering)
    PropSpec("corner_radius_top_left", _non_negative_number, default=0,
             wire_name="cornerRadiusTopLeft", drop_default=True),
    PropSpec("corner_radius_top_right", _non_negative_number, default=0,
             wire_name="cornerRadiusTopRight", drop_default=True),
    PropSpec("corner_radius_bottom_right", _non_negative_number, default=0,
             wire_name="cornerRadiusBottomRight", drop_default=True),
    PropSpec("corner_radius_bottom_left", _non_negative_number, default=0,
             wire_name="cornerRadiusBottomLeft", drop_default=True),
    # Visibility / interaction
    PropSpec("enabled", _bool, default=True, wire_name="enabled"),
    PropSpec("visible", _bool, default=True, wire_name="visibility"),
    PropSpec("opacity", _finite_0_1, default=1.0, animatable=True,
             wire_name="alpha"),
    PropSpec("clickable", _bool, default=False, wire_name="clickable",
             drop_default=True),
    PropSpec("focusable", _bool, default=False, wire_name="focusable",
             drop_default=True),
    PropSpec("content_description", _string, default="",
             wire_name="contentDescription", drop_default=True),
    # Accessibility (nullable semantics: absence ≠ "none"/False/0/"")
    PropSpec("accessibility_role", _accessibility_role, default="none",
             wire_name="accessibilityRole"),
    PropSpec("accessibility_checked", _bool, default=False,
             wire_name="accessibilityChecked", drop_default=True),
    PropSpec("accessibility_selected", _bool, default=False,
             wire_name="accessibilitySelected", drop_default=True),
    PropSpec("accessibility_state_description", _string, default="",
             wire_name="accessibilityStateDescription", drop_default=True),
    PropSpec("accessibility_range_min", _non_negative_number, default=0,
             wire_name="accessibilityRangeMin", drop_default=True),
    PropSpec("accessibility_range_max", _non_negative_number, default=0,
             wire_name="accessibilityRangeMax", drop_default=True),
    PropSpec("accessibility_range_current", _non_negative_number, default=0,
             wire_name="accessibilityRangeCurrent", drop_default=True),
    # Elevation (shadow)
    PropSpec("elevation", _non_negative_number, default=0.0, animatable=True,
             wire_name="elevation", drop_default=True),
    # Transforms
    PropSpec("rotation", _finite_number, default=0.0, animatable=True,
             wire_name="rotation", drop_default=True),
    PropSpec("rotation_x", _finite_number, default=0.0, animatable=True,
             wire_name="rotationX", drop_default=True),
    PropSpec("rotation_y", _finite_number, default=0.0, animatable=True,
             wire_name="rotationY", drop_default=True),
    PropSpec("scale_x", _finite_number, default=1.0, animatable=True,
             wire_name="scaleX", drop_default=True),
    PropSpec("scale_y", _finite_number, default=1.0, animatable=True,
             wire_name="scaleY", drop_default=True),
    PropSpec("translation_x", _finite_number, default=0.0, animatable=True,
             wire_name="translationX", drop_default=True),
    PropSpec("translation_y", _finite_number, default=0.0, animatable=True,
             wire_name="translationY", drop_default=True),
    # Text alignment / direction (generic, applies everywhere)
    PropSpec("text_alignment", _text_align, default="start",
             wire_name="textAlignment"),
    PropSpec("text_direction", _text_direction, default="inherit",
             wire_name="textDirection"),
    # Layout helpers — container-only for align_items/justify_content
    # (these are set on the parent container).
    # lp_weight and lp_gravity are set on the *child* (all kinds).
    PropSpec("align_items", _alignment, default="start",
             applies_to=_CONTAINER_KINDS,
             wire_name="alignItems"),
    PropSpec("justify_content", _justify, default="start",
             applies_to=_CONTAINER_KINDS,
             wire_name="justifyContent"),
    PropSpec("lp_weight", _non_negative_number, default=0.0,
             wire_name="layoutWeight", drop_default=True),
    PropSpec("lp_gravity", _layout_gravity, default="start",
             wire_name="layoutGravity", drop_default=True),
    # Ripple color
    PropSpec("ripple_color", _color, default="#00000040",
             wire_name="rippleColor", drop_default=True),
    # Pointer
    PropSpec("pointer_capture_axis", _pointer_axis, default="vertical",
             wire_name="pointerCaptureAxis"),
    # Layout overflow — only on container kinds
    PropSpec("overflow", _overflow, default="visible",
             applies_to=_CONTAINER_KINDS,
             wire_name="overflow"),
    # System window insets — available on every native view. Insets are
    # composed with the view's explicit padding by the renderer.
    PropSpec("safe_area", _bool, default=False,
             wire_name="safeArea", drop_default=True),
]

# -- Widget-specific properties ----------------------------------------------

_widget_props: dict[str, list[PropSpec]] = {
    "Box": [
        # Private virtual-list markers, consumed only by the native host.
        # Underscore-prefixed props are excluded from generated public
        # constructor stubs.  The generic VirtualList marks its content Box
        # and carries sticky boundary/edge metadata on sticky cell wrappers;
        # the native scroll hosts apply the sticky movement per frame.
        PropSpec("_virtual_content", _bool, default=False,
                 wire_name="_virtualListContent", drop_default=True),
        # Semantic positioned-content extent. Hosts enforce these logical
        # sizes with their native measurement/content-size mechanism.
        PropSpec("_virtual_content_width", _non_negative_number, default=0,
                 wire_name="_virtualContentWidth", drop_default=True),
        PropSpec("_virtual_content_height", _non_negative_number, default=0,
                 wire_name="_virtualContentHeight", drop_default=True),
        PropSpec("_virtual_sticky_edge", _sticky_edge, default=None,
                 wire_name="_virtualStickyEdge", drop_default=True),
        PropSpec("_virtual_sticky_boundary_start", _non_negative_number,
                 default=0, wire_name="_virtualStickyBoundaryStart",
                 drop_default=True),
        PropSpec("_virtual_sticky_boundary_end", _non_negative_number,
                 default=0, wire_name="_virtualStickyBoundaryEnd",
                 drop_default=True),
    ],
    "Layout": [
        PropSpec("orientation", _orientation, default="vertical",
                 applies_to=frozenset({"Layout"}),
                 wire_name="orientation"),
    ],
    "Scroll": [],
    "HorizontalScroll": [],
    "Text": [
        PropSpec("text", _string, default="",
                 applies_to=frozenset({"Text"}),
                 wire_name="text"),
        PropSpec("text_color", _color, default="#000000",
                 applies_to=frozenset({"Text"}),
                 wire_name="textColor"),
        PropSpec("font_size", _positive_number, default=14,
                 applies_to=frozenset({"Text"}),
                 wire_name="textSize"),
        PropSpec("line_height", _non_negative_number, default=0,
                 applies_to=frozenset({"Text"}),
                 wire_name="lineHeight", drop_default=True),
        PropSpec("include_font_padding", _bool, default=True,
                 applies_to=frozenset({"Text"}),
                 wire_name="includeFontPadding"),
    ],
    "TextInput": [
        PropSpec("text", _string, default="",
                 applies_to=frozenset({"TextInput"}),
                 wire_name="text"),
        PropSpec("hint", _string, default="",
                 applies_to=frozenset({"TextInput"}),
                 wire_name="hint"),
        PropSpec("text_color", _color, default="#000000",
                 applies_to=frozenset({"TextInput"}),
                 wire_name="textColor"),
        PropSpec("font_size", _positive_number, default=14,
                 applies_to=frozenset({"TextInput"}),
                 wire_name="textSize"),
        PropSpec("focused", _bool, default=False,
                 applies_to=frozenset({"TextInput"}),
                 wire_name="focused", drop_default=True),
        PropSpec("blur_on_keyboard_hide", _bool, default=True,
                 applies_to=frozenset({"TextInput"}),
                 wire_name="blurOnKeyboardHide"),
        PropSpec("blur_on_tap_outside", _bool, default=True,
                 applies_to=frozenset({"TextInput"}),
                 wire_name="blurOnTapOutside"),
        PropSpec("blur_on_submit", _bool, default=True,
                 applies_to=frozenset({"TextInput"}),
                 wire_name="blurOnSubmit"),
    ],
    "Image": [
        PropSpec("source", _string, default="",
                 applies_to=frozenset({"Image"}),
                 wire_name="imageSource"),
        PropSpec("scale_type", _image_scale, default="fit_center",
                 applies_to=frozenset({"Image"}),
                 wire_name="scaleType"),
    ],
    "Path": [
        PropSpec("commands", ValueSpec(exact_types=(list, tuple,)), default=(),
                 applies_to=frozenset({"Path"}),
                 wire_name="pathCommands"),
        PropSpec("stroke_color", _color, default="#000000",
                 applies_to=frozenset({"Path"}),
                 wire_name="strokeColor"),
        PropSpec("stroke_width", _positive_number, default=2.0,
                 applies_to=frozenset({"Path"}),
                 wire_name="strokeWidth"),
        PropSpec("stroke_line_cap", _line_cap, default="butt",
                 applies_to=frozenset({"Path"}),
                 wire_name="strokeLineCap"),
        PropSpec("stroke_line_join", _line_join, default="miter",
                 applies_to=frozenset({"Path"}),
                 wire_name="strokeLineJoin"),
        PropSpec("fill_color", _color, default="#00000000",
                 applies_to=frozenset({"Path"}),
                 wire_name="fillColor"),
        PropSpec("stroke_dash_array", _dash_array, default=(),
                 applies_to=frozenset({"Path"}),
                 wire_name="strokeDashArray", drop_default=True),
        PropSpec("stroke_dash_offset", _finite_number, default=0.0,
                 animatable=True, applies_to=frozenset({"Path"}),
                 wire_name="strokeDashOffset", drop_default=True),
    ],
    "Canvas": [
        PropSpec("draw", ValueSpec(exact_types=(list, tuple,)), default=(),
                 applies_to=frozenset({"Canvas"}),
                 wire_name="drawOps"),
        PropSpec("view_box", ValueSpec(
                     exact_types=(list, tuple,), item_spec=_finite_number,
                     min_items=4, max_items=4, nullable=True,
                 ), default=None, applies_to=frozenset({"Canvas"}),
                 wire_name="viewBox"),
    ],
}

# ---------------------------------------------------------------------------
# Kind definitions
# ---------------------------------------------------------------------------

PRIMITIVE_KINDS: dict[str, KindSpec] = {
    "Box": KindSpec(
        kind="Box",
        allowed_children=frozenset(
            {"Box", "Layout", "Scroll", "HorizontalScroll", "Text", "TextInput", "Image", "Path", "Canvas"}
        ),
        max_children=None,
    ),
    "Layout": KindSpec(
        kind="Layout",
        allowed_children=frozenset(
            {"Box", "Layout", "Scroll", "HorizontalScroll", "Text", "TextInput", "Image", "Path", "Canvas"}
        ),
        max_children=None,
    ),
    "Scroll": KindSpec(
        kind="Scroll",
        allowed_children=frozenset(
            {"Box", "Layout", "Scroll", "HorizontalScroll", "Text", "TextInput", "Image", "Path", "Canvas"}
        ),
        max_children=1,
    ),
    "HorizontalScroll": KindSpec(
        kind="HorizontalScroll",
        allowed_children=frozenset(
            {"Box", "Layout", "Scroll", "HorizontalScroll", "Text", "TextInput", "Image", "Path", "Canvas"}
        ),
        max_children=1,
    ),
    "Text": KindSpec(
        kind="Text",
        max_children=0,
    ),
    "TextInput": KindSpec(
        kind="TextInput",
        max_children=0,
    ),
    "Image": KindSpec(
        kind="Image",
        max_children=0,
    ),
    "Path": KindSpec(
        kind="Path",
        max_children=0,
    ),
    "Canvas": KindSpec(
        kind="Canvas",
        max_children=0,
    ),
}

# ---------------------------------------------------------------------------
# Canvas display-list operation schema
# ---------------------------------------------------------------------------

CANVAS_OP_SPECS: dict[str, CanvasOpSpec] = {
    "rect": CanvasOpSpec(
        kind="rect",
        required=frozenset({"x", "y", "width", "height"}),
        field_specs={
            "x": _finite_number,
            "y": _finite_number,
            "width": _positive_number,
            "height": _positive_number,
        },
    ),
    "round_rect": CanvasOpSpec(
        kind="round_rect",
        required=frozenset({"x", "y", "width", "height"}),
        field_specs={
            "x": _finite_number,
            "y": _finite_number,
            "width": _positive_number,
            "height": _positive_number,
            "radius": _non_negative_number,
        },
    ),
    "circle": CanvasOpSpec(
        kind="circle",
        required=frozenset({"cx", "cy", "r"}),
        field_specs={
            "cx": _finite_number,
            "cy": _finite_number,
            "r": _positive_number,
        },
    ),
    "line": CanvasOpSpec(
        kind="line",
        required=frozenset({"x1", "y1", "x2", "y2"}),
        field_specs={
            "x1": _finite_number,
            "y1": _finite_number,
            "x2": _finite_number,
            "y2": _finite_number,
        },
    ),
    "path": CanvasOpSpec(
        kind="path",
        required=frozenset(),
        field_specs={
            "d": ValueSpec(type_name="str", exact_types=(str,)),
            "commands": ValueSpec(exact_types=(list, tuple,)),
            "trim_start": ValueSpec(finite=True, non_negative=True, min_value=0.0, max_value=1.0),
            "trim_end": ValueSpec(finite=True, non_negative=True, min_value=0.0, max_value=1.0),
        },
    ),
}

# Shared paint fields for Canvas ops
_SHARED_PAINT_SPECS: dict[str, ValueSpec] = {
    "fill": _color,
    "stroke": _color,
    "stroke_width": _positive_number,
    "stroke_cap": _line_cap,
    "stroke_join": _line_join,
    "dash": _dash_array,
    "dash_offset": _finite_number,
    "opacity": _finite_0_1,
}

# Build merged specs: required + shared paint, with merged field_specs
_CANVAS_OP_SPECS_BUILT: dict[str, CanvasOpSpec] = {}
for _kind, _spec in CANVAS_OP_SPECS.items():
    _all_fields = frozenset(list(_spec.required) + list(_SHARED_PAINT_SPECS.keys()))
    _merged_specs = dict(_SHARED_PAINT_SPECS)
    _merged_specs.update(_spec.field_specs)
    _CANVAS_OP_SPECS_BUILT[_kind] = CanvasOpSpec(
        kind=_kind,
        fields=_all_fields,
        required=_spec.required,
        field_specs=_merged_specs,
    )
CANVAS_OP_SPECS = _CANVAS_OP_SPECS_BUILT


# ---------------------------------------------------------------------------
# Path command schema
# ---------------------------------------------------------------------------

# Valid Path command letters and their arity (expected values count).
# Format: {"cmd": "M", "values": [x, y]}
_PATH_COMMAND_ARITY: dict[str, int] = {
    "M": 2, "m": 2,     # move to (absolute / relative)
    "L": 2, "l": 2,     # line to
    "C": 6, "c": 6,     # cubic bezier curve
    "Q": 4, "q": 4,     # quadratic bezier curve
    "Z": 0, "z": 0,     # close path
}

_ALL_PATH_COMMANDS: frozenset[str] = frozenset(_PATH_COMMAND_ARITY.keys())


def validate_path_commands(commands: Any, *, path: str = "commands") -> None:
    """Validate a sequence of Path command dicts against the schema.

    Each command must have a ``cmd`` field (single uppercase/lowercase letter)
    and a ``values`` tuple of finite numbers whose length matches the arity
    for that command.
    """
    if not isinstance(commands, (list, tuple)):
        raise TypeError(f"{path} must be a list or tuple, got {type(commands).__name__}")
    for i, cmd in enumerate(commands):
        if not isinstance(cmd, (dict, FrozenMap)):
            raise TypeError(f"{path}[{i}] must be a dict, got {type(cmd).__name__}")
        d = dict(cmd)
        cmd_letter = d.get("cmd")
        if cmd_letter not in _ALL_PATH_COMMANDS:
            raise ValueError(
                f"{path}[{i}].cmd must be one of {sorted(_ALL_PATH_COMMANDS)!r}, "
                f"got {cmd_letter!r}"
            )
        expected_len = _PATH_COMMAND_ARITY[cmd_letter]
        values = d.get("values", ())
        if not isinstance(values, (list, tuple)):
            raise TypeError(f"{path}[{i}].values must be a list or tuple, got {type(values).__name__}")
        if len(values) != expected_len:
            raise ValueError(
                f"{path}[{i}] cmd={cmd_letter!r} expects {expected_len} values, "
                f"got {len(values)}"
            )
        for j, v in enumerate(values):
            if not is_finite_number(v):
                raise ValueError(
                    f"{path}[{i}].values[{j}] must be a finite number, got {v!r}"
                )
        # Reject unknown fields
        allowed = {"cmd", "values"}
        for field in d:
            if field not in allowed:
                raise ValueError(
                    f"{path}[{i}] unknown field {field!r}"
                )


def validate_canvas_draw_ops(ops: Any, *, path: str = "draw") -> None:
    """Validate a sequence of Canvas draw operation dicts against CANVAS_OP_SPECS.

    Each operation must have a recognised ``kind`` and fields that conform
    to the corresponding CanvasOpSpec.  The canonical ``draw`` value domain
    accepts both a list (the public constructor input) and a tuple (the
    frozen canonical storage form); both are validated here.
    """
    if not isinstance(ops, (list, tuple)):
        raise TypeError(f"{path} must be a list or tuple, got {type(ops).__name__}")
    for i, op in enumerate(ops):
        if not isinstance(op, (dict, FrozenMap)):
            raise TypeError(f"{path}[{i}] must be a dict, got {type(op).__name__}")
        d = dict(op)
        kind = d.get("kind")
        if kind not in CANVAS_OP_SPECS:
            raise ValueError(
                f"{path}[{i}].kind must be one of {sorted(CANVAS_OP_SPECS.keys())!r}, "
                f"got {kind!r}"
            )
        spec = CANVAS_OP_SPECS[kind]
        # Validate required fields
        for field in spec.required:
            if field not in d:
                raise ValueError(f"{path}[{i}] missing required field {field!r}")
        # Validate all fields against their ValueSpecs
        for field, val in d.items():
            if field == "kind":
                continue
            vs = spec.field_specs.get(field)
            if vs is None:
                # Check shared paint specs
                vs = _SHARED_PAINT_SPECS.get(field)
            if vs is not None:
                vs.validate(val, path=f"{path}[{i}].{field}")
            elif field not in spec.fields:
                raise ValueError(f"{path}[{i}] unknown field {field!r}")


# Import needed at module level for validation helpers
from vyne.values import FrozenMap, is_finite_number  # noqa: E402

# ---------------------------------------------------------------------------
# Event definitions
# ---------------------------------------------------------------------------

_POINTER_PAYLOAD_SPECS: dict[str, ValueSpec] = {
    "x": _finite_number,
    "y": _finite_number,
    "pointer_id": ValueSpec(type_name="int", non_negative=True),
    "event_time": ValueSpec(type_name="int", non_negative=True),
    "pressure": _finite_0_1,
    "size": _non_negative_number,
    "tool_type": ValueSpec(type_name="int", non_negative=True),
    "source": ValueSpec(type_name="int", non_negative=True),
    "down_x": _finite_number,
    "down_y": _finite_number,
    "down_time": ValueSpec(type_name="int", non_negative=True),
    "gesture_id": ValueSpec(type_name="int", non_negative=True),
}
_POINTER_PAYLOAD_FIELDS = frozenset(_POINTER_PAYLOAD_SPECS)

_LAYOUT_METRICS_PAYLOAD_SPECS: dict[str, ValueSpec] = {
    "x": _finite_number,
    "y": _finite_number,
    "width": _non_negative_number,
    "height": _non_negative_number,
}

_SCROLL_SEEK_PAYLOAD_SPECS: dict[str, ValueSpec] = {
    "target_offset_x": _non_negative_number,
    "target_offset_y": _non_negative_number,
    "final": _bool,
    "event_time": ValueSpec(type_name="int", non_negative=True),
}

_SCROLL_METRICS_PAYLOAD_SPECS: dict[str, ValueSpec] = {
    "offset_x": _non_negative_number,
    "offset_y": _non_negative_number,
    "viewport_width": _non_negative_number,
    "viewport_height": _non_negative_number,
    "content_width": _non_negative_number,
    "content_height": _non_negative_number,
    "velocity_x": _finite_number,
    "velocity_y": _finite_number,
    "projected_offset_x": _non_negative_number,
    "projected_offset_y": _non_negative_number,
    "event_time": ValueSpec(type_name="int", non_negative=True),
}

EVENT_SPECS: dict[str, EventSpec] = {
    "click": EventSpec(
        name="click",
        payload_fields=frozenset(),
        applies_to=frozenset(
            {"Box", "Layout", "Scroll", "HorizontalScroll", "Text", "TextInput", "Image", "Path", "Canvas"}
        ),
    ),
    "long_click": EventSpec(
        name="long_click",
        payload_fields=frozenset(),
        applies_to=frozenset(
            {"Box", "Layout", "Scroll", "HorizontalScroll", "Text", "TextInput", "Image", "Path", "Canvas"}
        ),
    ),
    **{
        event_name: EventSpec(
            name=event_name,
            payload_fields=_POINTER_PAYLOAD_FIELDS,
            applies_to=frozenset(
                {"Box", "Layout", "Scroll", "HorizontalScroll", "Text", "TextInput", "Image", "Path", "Canvas"}
            ),
            payload_specs=_POINTER_PAYLOAD_SPECS,
        )
        for event_name in (
            "pointer_down", "pointer_move", "pointer_up", "pointer_cancel"
        )
    },
    "focus_change": EventSpec(
        name="focus_change",
        payload_fields=frozenset({"has_focus"}),
        applies_to=frozenset({"TextInput"}),
        payload_specs={
            "has_focus": _bool,
        },
        controlled_props={"has_focus": "focused"},
    ),
    "text_change": EventSpec(
        name="text_change",
        payload_fields=frozenset({"text"}),
        applies_to=frozenset({"TextInput"}),
        payload_specs={
            "text": _string,
        },
        controlled_props={"text": "text"},
    ),
    "editor_action": EventSpec(
        name="editor_action",
        payload_fields=frozenset({"action_id", "text"}),
        applies_to=frozenset({"TextInput"}),
        payload_specs={
            "action_id": ValueSpec(type_name="int", non_negative=True),
            "text": _string,
        },
    ),
    "accessibility_progress": EventSpec(
        name="accessibility_progress",
        payload_fields=frozenset({"value"}),
        applies_to=frozenset({"Box", "Layout", "Scroll", "HorizontalScroll",
                              "Text", "TextInput", "Image", "Path", "Canvas"}),
        payload_specs={
            "value": _non_negative_number,
        },
        controlled_props={"value": "accessibility_range_current"},
    ),
    # Internal renderer observations used by the Python-owned virtual-list
    # controller. These names are protocol contracts, not a finalized public
    # list API. Kotlin reports mechanics; Python owns all window policy.
    # ``public_callback=False`` keeps them off the generated constructor
    # typing surface while preserving wire behavior and per-kind
    # applicability.
    "layout_metrics": EventSpec(
        name="layout_metrics",
        payload_fields=frozenset(_LAYOUT_METRICS_PAYLOAD_SPECS),
        applies_to=frozenset(
            {"Box", "Layout", "Scroll", "HorizontalScroll", "Text", "TextInput", "Image", "Path", "Canvas"}
        ),
        payload_specs=_LAYOUT_METRICS_PAYLOAD_SPECS,
        public_callback=False,
    ),
    "scroll_metrics": EventSpec(
        name="scroll_metrics",
        payload_fields=frozenset(_SCROLL_METRICS_PAYLOAD_SPECS),
        applies_to=frozenset({"Scroll", "HorizontalScroll"}),
        payload_specs=_SCROLL_METRICS_PAYLOAD_SPECS,
        public_callback=False,
    ),
    "scroll_seek": EventSpec(
        name="scroll_seek",
        payload_fields=frozenset(_SCROLL_SEEK_PAYLOAD_SPECS),
        applies_to=frozenset({"Scroll", "HorizontalScroll"}),
        payload_specs=_SCROLL_SEEK_PAYLOAD_SPECS,
        public_callback=False,
    ),
}

# ---------------------------------------------------------------------------
# Built property/prop lookup structures (materialized once)
# ---------------------------------------------------------------------------

def _build_prop_map() -> dict[str, PropSpec]:
    """Build a dict of all PropSpecs keyed by canonical name."""
    result: dict[str, PropSpec] = {}
    for prop in _generic_props:
        result[prop.name] = prop
    for kind_props in _widget_props.values():
        for prop in kind_props:
            if prop.name not in result:
                result[prop.name] = prop
    return result


ALL_PROPS: dict[str, PropSpec] = _build_prop_map()

# Map kind -> set of canonical prop names
PROPS_BY_KIND: dict[str, frozenset[str]] = {}
for _kind_name, _kind_spec in PRIMITIVE_KINDS.items():
    _names: set[str] = set()
    for _prop in _generic_props:
        # If prop has applies_to, only add to matching kinds
        if not _prop.applies_to or _kind_name in _prop.applies_to:
            _names.add(_prop.name)
    for _prop in _widget_props.get(_kind_name, []):
        _names.add(_prop.name)
    PROPS_BY_KIND[_kind_name] = frozenset(_names)

# Generic props available on every kind (those without applies_to restriction)
GENERIC_PROP_NAMES: frozenset[str] = frozenset(
    p.name for p in _generic_props if not p.applies_to
)

# Animatable props
ANIMATABLE_PROPS: frozenset[str] = frozenset(
    p.name for p in ALL_PROPS.values() if p.animatable
)
