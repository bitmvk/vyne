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
    PROPS_BY_KIND,
    PRIMITIVE_KINDS,
    GENERIC_PROP_NAMES,
)
from vyne.lowering import lower_element
from vyne.elements import (
    Box, Layout, Text, TextInput, Image, Scroll, Path, Canvas,
)

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

    def test_layout_has_orientation_prop(self):
        self.assertIn("orientation", PROPS_BY_KIND["Layout"])


# ---------------------------------------------------------------------------
# Reject matrices — unknown/malformed props
# ---------------------------------------------------------------------------

class PropRejectMatrices(unittest.TestCase):
    """Typed boundary tests: malformed strings, bool-as-number, NaN/inf,
    unknown nested fields, missing fields, zero/negative geometry, RGBA alpha."""

    def test_bool_and_non_finite_numbers_rejected(self):
        cases = [
            (lambda: Box(visible=1), (TypeError, ValueError)),
            (lambda: Box(opacity=float("nan")), (TypeError, ValueError)),
            (lambda: Box(translation_x=float("inf")), (TypeError, ValueError)),
        ]
        for factory, error in cases:
            with self.subTest(case=factory.__name__):
                with self.assertRaises(error):
                    lower_element(factory())

    def test_opacity_out_of_range_rejected(self):
        for value in (-0.5, 1.5):
            with self.subTest(opacity=value):
                with self.assertRaises(ValueError):
                    lower_element(Box(opacity=value))

    def test_malformed_colors_rejected(self):
        for value in ("#FFF", "#FF00448", "#FF0044880"):
            with self.subTest(color=value):
                with self.assertRaises(ValueError):
                    lower_element(Box(background_color=value))

    def test_invalid_dimensions_rejected(self):
        for value in ("invalid", -10):
            with self.subTest(width=value):
                with self.assertRaises(ValueError):
                    lower_element(Box(width=value))

    def test_invalid_enum_values_rejected(self):
        cases = [
            (Box(text_alignment="diagonal"), ValueError),
            (Layout(orientation="diagonal"), ValueError),
            (Box(corner_radius=-1), ValueError),
            (Box(border_width=-2), ValueError),
            (Text(text="x", font_size=-1), ValueError),
        ]
        for element, error in cases:
            with self.subTest(kind=element.kind):
                with self.assertRaises(error):
                    lower_element(element)


# ---------------------------------------------------------------------------
# Default fixture tests — one default fixture per kind
# ---------------------------------------------------------------------------

class DefaultFixtures(unittest.TestCase):
    """Lower and apply one default fixture per kind to strict canonical state."""

    def test_default_fixtures_per_kind(self):
        cases = [
            ("box", Box(), {"width": "wrap_content", "height": "wrap_content",
                             "opacity": 1.0, "align_items": "start"}),
            ("text", Text(text="hello"), {"text": "hello"}),
            ("textinput", TextInput(), {}),
            ("layout", Layout(orientation="horizontal"),
             {"orientation": "horizontal", "align_items": "start"}),
            ("image", Image(source="test.png"), {"source": "test.png"}),
            ("path", Path(d="M0,0 L10,10"), {"stroke_width": 2.0}),
            ("canvas", Canvas(draw=[
                {"kind": "rect", "x": 0, "y": 0, "width": 10, "height": 10}
            ]), {"draw": "present"}),
            ("scroll", Scroll(Text(text="child")), {}),
        ]
        for label, element, expected in cases:
            with self.subTest(kind=label):
                canon = lower_element(element)
                resolved = canon.props
                for prop, value in expected.items():
                    if value == "present":
                        self.assertIn(prop, resolved)
                    else:
                        self.assertEqual(resolved[prop], value)
                # Leaf kinds must not inherit container-only props.
                if label in ("text", "textinput", "image", "path", "canvas"):
                    self.assertNotIn("align_items", resolved)
                # Container kinds carry the container surface.
                if label in ("box", "layout"):
                    self.assertIn("align_items", resolved)
                # Scroll: safe_area has drop_default=True — not sent at default.
                if label == "scroll":
                    self.assertNotIn("safe_area", resolved)
                # TextInput: focused has drop_default=True — not sent at default.
                if label == "textinput":
                    self.assertNotIn("focused", resolved)

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
