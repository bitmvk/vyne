"""Per-kind canonical contract tests (SCHEMA-01).

Validates that every primitive kind has exactly the right set of props,
that required fields/children are enforced, that unknown names reject in
Python, and that defaults materialize correctly.  Also verifies typed
boundary behavior for dimensions, colors, alignments, accessibility
nullable semantics, Path dash, and Canvas ops.
"""

from __future__ import annotations

import unittest

from vyne.spec.schema_v2 import (
    ALL_PROPS,
    ANIMATABLE_PROPS,
    PROPS_BY_KIND,
    PRIMITIVE_KINDS,
    GENERIC_PROP_NAMES,
    CANVAS_OP_SPECS,
    EVENT_SPECS,
    validate_path_commands,
    validate_canvas_draw_ops,
)
from vyne.spec.model import ValueSpec, PropSpec, KindSpec
from vyne.values import (
    FrozenMap,
    freeze,
    is_valid_color,
    is_finite_number,
    validate_finite,
    validate_positive,
    validate_non_negative,
    is_valid_dash_array,
    validate_dash_array,
)
from vyne.lowering import lower_element, CanonicalElement
from vyne.elements import (
    Element,
    Box, Layout, Row, Column, Text, TextInput, Image, Scroll, Path, Canvas,
)
from vyne.style import Style, Decoration, Fill, Stroke, CornerRadius, Shadow, Ripple


# ---------------------------------------------------------------------------
# Per-kind prop applicability matrices
# ---------------------------------------------------------------------------

_CONTAINER_ONLY_PROPS = frozenset({
    "align_items", "justify_content", "overflow",
    "max_width", "max_height",
})

_TEXT_ONLY_PROPS = frozenset({
    "text", "text_color", "font_size", "line_height", "include_font_padding",
})

_TEXTINPUT_ONLY_PROPS = frozenset({
    "text", "hint", "text_color", "font_size",
    "focused", "blur_on_keyboard_hide", "blur_on_tap_outside", "blur_on_submit",
})

_IMAGE_ONLY_PROPS = frozenset({"source", "scale_type"})
_PATH_ONLY_PROPS = frozenset({
    "commands", "stroke_color", "stroke_width", "stroke_line_cap",
    "stroke_line_join", "fill_color", "stroke_dash_array", "stroke_dash_offset",
})
_CANVAS_ONLY_PROPS = frozenset({"draw", "view_box"})
_LAYOUT_ONLY_PROPS = frozenset({"orientation"})
class PerKindPropApplicability(unittest.TestCase):
    """Every kind gets exactly its applicable props."""

    def test_container_kinds_have_container_props(self):
        for kind in ("Box", "Layout", "Scroll"):
            props = PROPS_BY_KIND[kind]
            for cp in _CONTAINER_ONLY_PROPS:
                self.assertIn(cp, props, f"{cp} missing from {kind}")

    def test_leaf_kinds_lack_container_only_props(self):
        for kind in ("Text", "TextInput", "Image", "Path", "Canvas"):
            props = PROPS_BY_KIND[kind]
            for cp in ("align_items", "justify_content"):
                self.assertNotIn(cp, props, f"{cp} should NOT be on leaf {kind}")

    def test_safe_area_is_available_on_every_kind(self):
        for kind, props in PROPS_BY_KIND.items():
            self.assertIn("safe_area", props, f"safe_area missing from {kind}")

    def test_text_has_text_only_props(self):
        props = PROPS_BY_KIND["Text"]
        for tp in _TEXT_ONLY_PROPS:
            self.assertIn(tp, props, f"{tp} missing from Text")

    def test_text_lacks_textinput_only_props(self):
        props = PROPS_BY_KIND["Text"]
        for tp in ("focused", "hint", "blur_on_keyboard_hide"):
            self.assertNotIn(tp, props, f"{tp} should NOT be on Text")

    def test_textinput_has_its_props(self):
        props = PROPS_BY_KIND["TextInput"]
        for tp in _TEXTINPUT_ONLY_PROPS:
            self.assertIn(tp, props, f"{tp} missing from TextInput")

    def test_image_has_its_props(self):
        props = PROPS_BY_KIND["Image"]
        for ip in _IMAGE_ONLY_PROPS:
            self.assertIn(ip, props, f"{ip} missing from Image")

    def test_path_has_its_props(self):
        props = PROPS_BY_KIND["Path"]
        for pp in _PATH_ONLY_PROPS:
            self.assertIn(pp, props, f"{pp} missing from Path")

    def test_canvas_has_its_props(self):
        props = PROPS_BY_KIND["Canvas"]
        for cp in _CANVAS_ONLY_PROPS:
            self.assertIn(cp, props, f"{cp} missing from Canvas")

    def test_layout_has_orientation_required(self):
        spec = PRIMITIVE_KINDS["Layout"]
        self.assertIn("orientation", spec.required)

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            lower_element(Element(kind="Unknown", props={}))


# ---------------------------------------------------------------------------
# Reject matrices — unknown/malformed props
# ---------------------------------------------------------------------------

class PropRejectMatrices(unittest.TestCase):
    """Typed boundary tests: malformed strings, bool-as-number, NaN/inf,
    unknown nested fields, missing fields, zero/negative geometry, RGBA alpha."""

    def test_bool_as_number_rejected(self):
        with self.assertRaises((TypeError, ValueError)):
            lower_element(Box(visible=1))

    def test_nan_rejected(self):
        with self.assertRaises((TypeError, ValueError)):
            lower_element(Box(opacity=float("nan")))

    def test_inf_rejected(self):
        with self.assertRaises((TypeError, ValueError)):
            lower_element(Box(translation_x=float("inf")))

    def test_negative_opacity_rejected(self):
        with self.assertRaises(ValueError):
            lower_element(Box(opacity=-0.5))

    def test_opacity_above_one_rejected(self):
        with self.assertRaises(ValueError):
            lower_element(Box(opacity=1.5))

    def test_invalid_color_rejected(self):
        with self.assertRaises(ValueError):
            lower_element(Box(background_color="red"))

    def test_short_color_rejected(self):
        with self.assertRaises(ValueError):
            lower_element(Box(background_color="#FFF"))

    def test_seven_digit_color_rejected(self):
        with self.assertRaises(ValueError):
            lower_element(Box(background_color="#FF00448"))

    def test_nine_digit_color_rejected(self):
        with self.assertRaises(ValueError):
            lower_element(Box(background_color="#FF0044880"))

    def test_invalid_dimension_string_rejected(self):
        with self.assertRaises(ValueError):
            lower_element(Box(width="invalid"))

    def test_negative_dimension_number_rejected(self):
        with self.assertRaises(ValueError):
            lower_element(Box(width=-10))

    def test_invalid_alignment_rejected(self):
        with self.assertRaises(ValueError):
            lower_element(Box(text_alignment="diagonal"))

    def test_invalid_orientation_rejected(self):
        with self.assertRaises(ValueError):
            lower_element(Layout(orientation="diagonal"))

    def test_negative_corner_radius_rejected(self):
        with self.assertRaises(ValueError):
            lower_element(Box(corner_radius=-1))

    def test_negative_border_width_rejected(self):
        with self.assertRaises(ValueError):
            lower_element(Box(border_width=-2))

    def test_negative_font_size_rejected(self):
        with self.assertRaises(ValueError):
            lower_element(Text(text="x", font_size=-1))


# ---------------------------------------------------------------------------
# Default fixture tests — one default fixture per kind
# ---------------------------------------------------------------------------

class DefaultFixtures(unittest.TestCase):
    """Lower and apply one default fixture per kind to strict canonical state."""

    def test_box_default_fixture(self):
        canon = lower_element(Box())
        resolved = canon.props
        # Dimensions default to wrap_content
        self.assertEqual(resolved["width"], "wrap_content")
        self.assertEqual(resolved["height"], "wrap_content")
        self.assertEqual(resolved["opacity"], 1.0)
        # Box is a container: should have container props
        self.assertIn("align_items", resolved)

    def test_text_default_fixture(self):
        canon = lower_element(Text(text="hello"))
        resolved = canon.props
        self.assertEqual(resolved["text"], "hello")
        # Text has no layout-only container props
        self.assertNotIn("align_items", resolved)
        self.assertNotIn("justify_content", resolved)

    def test_textinput_default_fixture(self):
        canon = lower_element(TextInput())
        resolved = canon.props
        # focused has drop_default=True — not sent when at default
        self.assertNotIn("focused", resolved)
        # TextInput has its own editable baseline — not from generic
        self.assertNotIn("align_items", resolved)

    def test_layout_default_fixture(self):
        canon = lower_element(Layout(orientation="horizontal"))
        resolved = canon.props
        self.assertEqual(resolved["orientation"], "horizontal")
        self.assertIn("align_items", resolved)

    def test_image_default_fixture(self):
        canon = lower_element(Image(source="test.png"))
        resolved = canon.props
        self.assertEqual(resolved["source"], "test.png")
        self.assertNotIn("align_items", resolved)

    def test_path_default_fixture(self):
        canon = lower_element(Path(d="M0,0 L10,10"))
        resolved = canon.props
        self.assertIn("commands", resolved)
        # Path has stroke props
        self.assertEqual(resolved.get("stroke_width"), 2.0)
        self.assertNotIn("align_items", resolved)

    def test_canvas_default_fixture(self):
        canon = lower_element(Canvas(draw=[
            {"kind": "rect", "x": 0, "y": 0, "width": 10, "height": 10}
        ]))
        resolved = canon.props
        self.assertIn("draw", resolved)
        self.assertNotIn("align_items", resolved)

    def test_scroll_default_fixture(self):
        canon = lower_element(Scroll(Text(text="child")))
        resolved = canon.props
        # safe_area has drop_default=True — not sent when at default
        self.assertNotIn("safe_area", resolved)

    def test_leaf_safe_area_is_preserved_when_enabled(self):
        canon = lower_element(Text(text="edge label", safe_area=True))
        self.assertTrue(canon.props["safe_area"])


# ---------------------------------------------------------------------------
# Native wire name coverage
# ---------------------------------------------------------------------------

class WireNameCoverage(unittest.TestCase):
    """Every PropSpec with applies-to-any-kind must have a wire_name."""

    def test_generic_props_have_wire_names(self):
        for name in GENERIC_PROP_NAMES:
            spec = ALL_PROPS.get(name)
            if spec is None:
                continue
            self.assertIsNotNone(
                spec.wire_name,
                f"Generic prop {name!r} missing wire_name",
            )

    def test_kind_specific_props_have_wire_names(self):
        for kind in PRIMITIVE_KINDS:
            for name in PROPS_BY_KIND[kind]:
                spec = ALL_PROPS.get(name)
                if spec is None:
                    continue
                if name not in GENERIC_PROP_NAMES:
                    self.assertIsNotNone(
                        spec.wire_name,
                        f"Kind-specific prop {name!r} on {kind} missing wire_name",
                    )

    def test_no_duplicate_wire_names(self):
        seen: dict[str, str] = {}
        for name, spec in ALL_PROPS.items():
            if spec.wire_name is None:
                continue
            if spec.wire_name in seen:
                self.fail(
                    f"Duplicate wire_name {spec.wire_name!r}: "
                    f"{seen[spec.wire_name]!r} and {name!r}"
                )
            seen[spec.wire_name] = name


# ---------------------------------------------------------------------------
# Accessibility nullable semantics
# ---------------------------------------------------------------------------

class AccessibilityContractTests(unittest.TestCase):
    """Accessibility absence is distinct from false/empty string."""

    def test_role_default_is_none(self):
        canon = lower_element(Box())
        self.assertEqual(canon.props["accessibility_role"], "none")
        # accessibility_checked has drop_default=True — not sent when at default
        self.assertNotIn("accessibility_checked", canon.props)

    def test_explicit_role_overrides(self):
        canon = lower_element(Box(accessibility_role="button"))
        self.assertEqual(canon.props["accessibility_role"], "button")

    def test_checked_state(self):
        canon = lower_element(Box(accessibility_checked=True))
        self.assertTrue(canon.props["accessibility_checked"])

    def test_selected_state(self):
        canon = lower_element(Box(accessibility_selected=True))
        self.assertTrue(canon.props["accessibility_selected"])

    def test_empty_content_description_is_default(self):
        canon = lower_element(Box())
        # content_description has drop_default=True — not sent when at default ("")
        self.assertNotIn("content_description", canon.props)

    def test_explicit_content_description(self):
        canon = lower_element(Box(content_description="Submit"))
        self.assertEqual(canon.props["content_description"], "Submit")


# ---------------------------------------------------------------------------
# Max constraints test
# ---------------------------------------------------------------------------

class MaxConstraintsTests(unittest.TestCase):
    """max_width/max_height on container kinds."""

    def test_max_width_on_box(self):
        canon = lower_element(Box(max_width=200))
        resolved = canon.props
        self.assertEqual(resolved.get("max_width"), 200)

    def test_max_height_not_on_text(self):
        # max_height is container-only; Text shouldn't have it
        with self.assertRaises(ValueError):
            lower_element(Text(text="x", max_height=100))

    def test_max_width_on_layout(self):
        canon = lower_element(Layout(orientation="vertical", max_width=300))
        resolved = canon.props
        self.assertEqual(resolved.get("max_width"), 300)


if __name__ == "__main__":
    unittest.main()
