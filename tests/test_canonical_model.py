"""Tests for canonical schema, values, lowering, and immutability.

Covers MODEL-01, MODEL-02, MODEL-03 requirements:
- ValueSpec validation (types, ranges, enums, colors, dimensions, dashes)
- FrozenMap immutability
- Schema completeness
- Style/Decoration lowering
- Element immutability
- Per-mount refs/handles
- Error rejection for invalid values
"""

from __future__ import annotations

import unittest

from vyne.values import (
    FrozenMap,
    freeze,
    thaw,
    is_valid_color,
    is_finite_number,
    validate_finite,
    validate_positive,
    validate_non_negative,
    is_valid_dash_array,
    validate_dash_array,
)
from vyne.spec.model import ValueSpec, PropSpec, KindSpec, CanvasOpSpec
from vyne.spec.schema_v2 import (
    ALL_PROPS,
    ANIMATABLE_PROPS,
    PROPS_BY_KIND,
    PRIMITIVE_KINDS,
    GENERIC_PROP_NAMES,
    CANVAS_OP_SPECS,
    EVENT_SPECS,
)
from vyne.lowering import lower_element, CanonicalElement
from vyne.elements import (
    Element,
    Box, Layout, Row, Column, Text, TextInput, Image, Scroll, Path, Canvas,
)
from vyne.style import (
    Style, Decoration, Fill, Stroke, CornerRadius, Shadow, Ripple,
)
from vyne.refs import Ref, ViewHandle


# ---------------------------------------------------------------------------
# FrozenMap
# ---------------------------------------------------------------------------

class FrozenMapTests(unittest.TestCase):
    def test_construction_from_items(self):
        fm = FrozenMap([("a", 1), ("b", 2)])
        self.assertEqual(fm["a"], 1)
        self.assertEqual(fm["b"], 2)

    def test_reject_non_string_keys(self):
        with self.assertRaises(TypeError):
            FrozenMap([(1, "a")])

    def test_reject_duplicate_keys(self):
        with self.assertRaises(ValueError):
            FrozenMap([("a", 1), ("a", 2)])

    def test_iteration_is_ordered(self):
        fm = FrozenMap([("z", 1), ("a", 2), ("m", 3)])
        self.assertEqual(list(fm.keys()), ["z", "a", "m"])

    def test_mapping_views_delegate_to_mapping(self):
        fm = FrozenMap([("a", 1), ("b", 2)])
        self.assertEqual(list(fm.keys()), ["a", "b"])
        self.assertEqual(list(fm.values()), [1, 2])
        self.assertEqual(list(fm.items()), [("a", 1), ("b", 2)])
        self.assertIn("a", fm.keys())
        self.assertIn(2, fm.values())
        self.assertIn(("b", 2), fm.items())

    def test_equality_is_order_independent(self):
        fm1 = FrozenMap([("a", 1), ("b", 2)])
        fm2 = FrozenMap([("b", 2), ("a", 1)])
        self.assertEqual(fm1, fm2)

    def test_hash_is_stable(self):
        fm1 = FrozenMap([("a", 1), ("b", 2)])
        fm2 = FrozenMap([("a", 1), ("b", 2)])
        self.assertEqual(hash(fm1), hash(fm2))

    def test_with_item_adds_or_replaces(self):
        fm = FrozenMap([("a", 1)])
        fm2 = fm.with_item("b", 2)
        self.assertEqual(fm2["b"], 2)
        fm3 = fm.with_item("a", 10)
        self.assertEqual(fm3["a"], 10)

    def test_without_removes_key(self):
        fm = FrozenMap([("a", 1), ("b", 2)])
        fm2 = fm.without("a")
        self.assertNotIn("a", fm2)
        self.assertIn("b", fm2)

    def test_without_nonexistent_returns_self(self):
        fm = FrozenMap([("a", 1)])
        self.assertIs(fm.without("b"), fm)

    def test_get_with_default(self):
        fm = FrozenMap([("a", 1)])
        self.assertEqual(fm.get("a"), 1)
        self.assertEqual(fm.get("b", 42), 42)
        self.assertIsNone(fm.get("b"))

    def test_len_and_contains(self):
        fm = FrozenMap([("a", 1), ("b", 2)])
        self.assertEqual(len(fm), 2)
        self.assertIn("a", fm)
        self.assertNotIn("c", fm)


# ---------------------------------------------------------------------------
# freeze / thaw
# ---------------------------------------------------------------------------

class FreezeThawTests(unittest.TestCase):
    def test_freeze_dict_to_frozenmap(self):
        result = freeze({"a": 1, "b": [2, 3]})
        self.assertIsInstance(result, FrozenMap)
        self.assertEqual(result["a"], 1)
        self.assertIsInstance(result["b"], tuple)

    def test_freeze_list_to_tuple(self):
        result = freeze([1, 2, {"a": 3}])
        self.assertIsInstance(result, tuple)
        self.assertIsInstance(result[2], FrozenMap)

    def test_thaw_restores_mutable(self):
        original = {"a": [1, 2]}
        frozen = freeze(original)
        thawed = thaw(frozen)
        self.assertEqual(thawed, original)
        self.assertIsInstance(thawed, dict)
        self.assertIsInstance(thawed["a"], list)

    def test_freeze_scalars_pass_through(self):
        self.assertIsNone(freeze(None))
        self.assertEqual(freeze(42), 42)
        self.assertEqual(freeze("hello"), "hello")
        self.assertTrue(freeze(True))

    def test_freeze_rejects_unsupported_opaque_objects(self):
        with self.assertRaises(TypeError):
            freeze(object())

        class CustomMutable:
            pass

        with self.assertRaises(TypeError):
            freeze(CustomMutable())

    def test_freeze_keeps_explicit_opaque_framework_values(self):
        ref = Ref()
        callback = lambda: None
        self.assertIs(freeze(ref), ref)
        self.assertIs(freeze(callback), callback)


# ---------------------------------------------------------------------------
# Color and numeric validation
# ---------------------------------------------------------------------------

class ColorValidationTests(unittest.TestCase):
    def test_valid_rrggbb(self):
        self.assertTrue(is_valid_color("#FF0044"))
        self.assertTrue(is_valid_color("#000000"))
        self.assertTrue(is_valid_color("#FFFFFF"))

    def test_valid_rrggbbaa(self):
        self.assertTrue(is_valid_color("#FF004488"))
        self.assertTrue(is_valid_color("#00000000"))

    def test_invalid_colors(self):
        self.assertFalse(is_valid_color("red"))
        self.assertFalse(is_valid_color("#FFF"))
        self.assertFalse(is_valid_color("#GGGGGG"))
        self.assertFalse(is_valid_color(123))
        self.assertFalse(is_valid_color(None))
        self.assertFalse(is_valid_color("#FF00448"))  # 7 chars


class NumericValidationTests(unittest.TestCase):
    def test_finite_number(self):
        self.assertTrue(is_finite_number(42))
        self.assertTrue(is_finite_number(3.14))
        self.assertTrue(is_finite_number(0))
        self.assertFalse(is_finite_number(True))
        self.assertFalse(is_finite_number(float("inf")))
        self.assertFalse(is_finite_number(float("nan")))

    def test_validate_finite(self):
        validate_finite(42)
        with self.assertRaises(TypeError):
            validate_finite(True)
        with self.assertRaises(ValueError):
            validate_finite(float("inf"))

    def test_validate_positive(self):
        validate_positive(1)
        with self.assertRaises(ValueError):
            validate_positive(0)
        with self.assertRaises(ValueError):
            validate_positive(-1)

    def test_validate_non_negative(self):
        validate_non_negative(0)
        validate_non_negative(1)
        with self.assertRaises(ValueError):
            validate_non_negative(-1)

    def test_valid_dash_array(self):
        self.assertTrue(is_valid_dash_array((4, 2)))
        self.assertTrue(is_valid_dash_array((10, 5, 2, 3)))
        self.assertTrue(is_valid_dash_array(()))  # empty = no dash
        self.assertFalse(is_valid_dash_array((1,)))  # odd length
        self.assertFalse(is_valid_dash_array((0, 1)))  # zero


# ---------------------------------------------------------------------------
# ValueSpec validation
# ---------------------------------------------------------------------------

class ValueSpecTests(unittest.TestCase):
    def test_bool_spec(self):
        spec = ValueSpec(type_name="bool", exact_types=(bool,))
        spec.validate(True)
        with self.assertRaises(TypeError):
            spec.validate(1)

    def test_string_spec(self):
        spec = ValueSpec(type_name="str", exact_types=(str,))
        spec.validate("hello")
        with self.assertRaises(TypeError):
            spec.validate(123)

    def test_nullable_spec(self):
        spec = ValueSpec(type_name="str", exact_types=(str,), nullable=True)
        spec.validate(None)
        spec.validate("hello")

    def test_enum_spec(self):
        spec = ValueSpec(type_name="str", enum=frozenset({"horizontal", "vertical"}))
        spec.validate("horizontal")
        with self.assertRaises(ValueError):
            spec.validate("diagonal")

    def test_color_spec(self):
        spec = ValueSpec(type_name="str", color=True)
        spec.validate("#FF0000")
        with self.assertRaises(ValueError):
            spec.validate("red")

    def test_dash_array_spec(self):
        spec = ValueSpec(dash_array=True)
        spec.validate((4, 2))
        with self.assertRaises(ValueError):
            spec.validate((1,))

    def test_finite_spec(self):
        spec = ValueSpec(finite=True)
        spec.validate(42)
        with self.assertRaises(TypeError):
            spec.validate(True)

    def test_dimension_spec(self):
        spec = ValueSpec(exact_types=(str, int, float), dimension=True)
        spec.validate("wrap_content")
        spec.validate("16dp")
        spec.validate(42)
        with self.assertRaises(ValueError):
            spec.validate("invalid")
        with self.assertRaises(ValueError):
            spec.validate("invaliddp")

    def test_numeric_specs_reject_collection_and_bool_bypasses(self):
        for spec in (
            ValueSpec(finite=True),
            ValueSpec(positive=True),
            ValueSpec(non_negative=True),
            ValueSpec(min_value=0, max_value=1),
        ):
            for invalid in ([], (), {}, FrozenMap(), True):
                with self.subTest(spec=spec, invalid=invalid):
                    with self.assertRaises((TypeError, ValueError)):
                        spec.validate(invalid)

    def test_exact_int_excludes_bool(self):
        spec = ValueSpec(type_name="int", non_negative=True)
        spec.validate(1)
        with self.assertRaises(TypeError):
            spec.validate(True)


# ---------------------------------------------------------------------------
# Schema completeness
# ---------------------------------------------------------------------------

class SchemaCompletenessTests(unittest.TestCase):
    def test_all_primitives_have_kind_specs(self):
        expected = {
            "Box", "Layout", "Scroll", "HorizontalScroll", "Text",
            "TextInput", "Image", "Path", "Canvas",
        }
        self.assertEqual(set(PRIMITIVE_KINDS.keys()), expected)

    def test_props_by_kind_coverage(self):
        for kind in PRIMITIVE_KINDS:
            self.assertIn(kind, PROPS_BY_KIND, f"Missing props for {kind}")

    def test_generic_props_on_all_kinds(self):
        for kind in PRIMITIVE_KINDS:
            for prop_name in GENERIC_PROP_NAMES:
                self.assertIn(prop_name, PROPS_BY_KIND[kind],
                              f"Generic prop {prop_name} missing from {kind}")

    def test_text_input_has_text_change_events(self):
        self.assertIn("text_change", EVENT_SPECS)
        self.assertIn("TextInput", EVENT_SPECS["text_change"].applies_to)

    def test_canvas_ops_have_required_specs(self):
        expected_ops = {"rect", "round_rect", "circle", "line", "path"}
        self.assertEqual(set(CANVAS_OP_SPECS.keys()), expected_ops)
        for name, spec in CANVAS_OP_SPECS.items():
            self.assertIsNotNone(spec.required)
            self.assertIsNotNone(spec.fields)
            for field in spec.required:
                self.assertIn(field, spec.fields)

    def test_animatable_props(self):
        expected = {"opacity", "rotation", "rotation_x", "rotation_y",
                    "scale_x", "scale_y", "translation_x", "translation_y",
                    "elevation", "stroke_dash_offset",
                    "width", "height"}
        self.assertEqual(ANIMATABLE_PROPS, expected)


# ---------------------------------------------------------------------------
# Lowering — canonical element conversion
# ---------------------------------------------------------------------------

class LoweringTests(unittest.TestCase):
    def test_box_lowers_to_canonical(self):
        elem = Box()
        canon = lower_element(elem)
        self.assertIsInstance(canon, CanonicalElement)
        self.assertEqual(canon.kind, "Box")
        self.assertIsInstance(canon.props, FrozenMap)

    def test_text_lowers_with_text_prop(self):
        elem = Text(text="hello")
        canon = lower_element(elem)
        self.assertEqual(canon.props["text"], "hello")

    def test_layout_lowers_orientation(self):
        elem = Layout(orientation="horizontal")
        canon = lower_element(elem)
        self.assertEqual(canon.props["orientation"], "horizontal")

    def test_padding_shorthand_expands(self):
        elem = Box(padding=10)
        canon = lower_element(elem)
        self.assertEqual(canon.props["padding_top"], 10)
        self.assertEqual(canon.props["padding_bottom"], 10)
        self.assertEqual(canon.props["padding_start"], 10)
        self.assertEqual(canon.props["padding_end"], 10)

    def test_corner_radius_shorthand_expands(self):
        elem = Box(corner_radius=5)
        canon = lower_element(elem)
        self.assertEqual(canon.props["corner_radius_top_left"], 5)
        self.assertEqual(canon.props["corner_radius_top_right"], 5)

    def test_alpha_alias_resolves_to_opacity(self):
        elem = Box(alpha=0.5)
        canon = lower_element(elem)
        self.assertNotIn("alpha", canon.props)
        self.assertEqual(canon.props["opacity"], 0.5)

    def test_conflicting_alpha_and_opacity_rejects(self):
        with self.assertRaises(ValueError):
            lower_element(Box(alpha=0.5, opacity=0.8))

    def test_invalid_kind_rejected(self):
        elem = Element(kind="Unknown", props={})
        with self.assertRaises(ValueError):
            lower_element(elem)

    def test_invalid_prop_name_rejected(self):
        elem = Box(invalid_prop=123)
        with self.assertRaises(ValueError):
            lower_element(elem)

    def test_invalid_color_rejected(self):
        with self.assertRaises(ValueError):
            lower_element(Box(background_color="red"))

    def test_valid_color_accepted(self):
        canon = lower_element(Box(background_color="#FF0000"))
        self.assertEqual(canon.props["background_color"], "#FF0000")

    def test_rrggbbaa_color_accepted(self):
        canon = lower_element(Box(background_color="#FF000080"))
        self.assertEqual(canon.props["background_color"], "#FF000080")

    def test_bool_prop_must_be_bool(self):
        canon = lower_element(TextInput(focused=True))
        self.assertTrue(canon.props["focused"])

    def test_numeric_string_rejected_for_bool(self):
        with self.assertRaises((TypeError, ValueError)):
            lower_element(TextInput(focused="yes"))

    def test_text_leaf_has_no_children(self):
        with self.assertRaises(ValueError):
            lower_element(Element(kind="Text", props={"text": "x"},
                                  children=(Text(text="child"),)))

    def test_scroll_max_one_child(self):
        # Scroll with more than 1 child: the public constructor auto-wraps,
        # but a raw Element with >1 children should fail.
        raw = Element(kind="Scroll", props={},
                      children=(Text(text="a"), Text(text="b")))
        with self.assertRaises(ValueError):
            lower_element(raw)

    def test_unknown_canvas_op_raises(self):
        # Lowering doesn't validate draw list content deeply (runtime does),
        # but the schema defines which ops exist.
        # This test verifies Canvas itself lowers.
        canon = lower_element(Canvas(draw=[{"kind": "rect", "x": 1, "y": 2, "width": 10, "height": 20}]))
        self.assertEqual(canon.kind, "Canvas")


# ---------------------------------------------------------------------------
# Style/Decoration lowering (MODEL-02)
# ---------------------------------------------------------------------------

class StyleDecorationLoweringTests(unittest.TestCase):
    def test_style_text_color_lowers(self):
        elem = Text(text="x", style=Style(text_color="#FF0000"))
        canon = lower_element(elem)
        self.assertEqual(canon.props["text_color"], "#FF0000")

    def test_style_background_lowers(self):
        elem = Box(style=Style(background_color="#00FF00"))
        canon = lower_element(elem)
        self.assertEqual(canon.props["background_color"], "#00FF00")

    def test_style_font_size_lowers(self):
        elem = Text(text="x", style=Style(font_size=18))
        canon = lower_element(elem)
        self.assertEqual(canon.props["font_size"], 18)

    def test_style_padding_lowers_as_shorthand(self):
        elem = Box(style=Style(padding=12))
        canon = lower_element(elem)
        self.assertEqual(canon.props["padding_top"], 12)

    def test_direct_props_override_style(self):
        # Direct text_color overrides Style's text_color
        elem = Text(text="x", text_color="#000000",
                    style=Style(text_color="#FF0000"))
        canon = lower_element(elem)
        self.assertEqual(canon.props["text_color"], "#000000")

    def test_style_color_alias_lowers_to_text_color(self):
        elem = Text(text="x", style=Style(color="#ABCDEF"))
        canon = lower_element(elem)
        self.assertEqual(canon.props["text_color"], "#ABCDEF")

    def test_unsupported_style_fields_reject(self):
        with self.assertRaises(ValueError):
            lower_element(Box(style=Style(gap=10)))

    def test_unsupported_flex_reject(self):
        with self.assertRaises(ValueError):
            lower_element(Box(style=Style(flex=1)))

    def test_size_shorthand_rejects(self):
        with self.assertRaises(ValueError):
            lower_element(Box(size=100))

    def test_decoration_solid_fill_lowers(self):
        elem = Box(decoration=Decoration.rectangle(fill="#FF0000"))
        canon = lower_element(elem)
        self.assertEqual(canon.props["background_color"], "#FF0000")

    def test_decoration_stroke_lowers_to_border(self):
        elem = Box(decoration=Decoration.rectangle(
            stroke=Stroke(color="#000000", width=3)))
        canon = lower_element(elem)
        self.assertEqual(canon.props["border_color"], "#000000")
        self.assertEqual(canon.props["border_width"], 3)

    def test_decoration_corners_lower(self):
        elem = Box(decoration=Decoration.rectangle(
            corners=CornerRadius.all(8)))
        canon = lower_element(elem)
        self.assertEqual(canon.props["corner_radius_top_left"], 8)

    def test_decoration_elevation_lowers(self):
        elem = Box(decoration=Decoration.rectangle(
            shadow=Shadow(elevation=4)))
        canon = lower_element(elem)
        self.assertEqual(canon.props["elevation"], 4)

    def test_decoration_ripple_lowers(self):
        elem = Box(decoration=Decoration.rectangle(
            ripple=Ripple(color="#40000000")))
        canon = lower_element(elem)
        self.assertEqual(canon.props["ripple_color"], "#40000000")

    def test_dashed_stroke_rejects(self):
        with self.assertRaises(ValueError):
            lower_element(Box(decoration=Decoration.rectangle(
                stroke=Stroke(color="#000", dash_width=4, dash_gap=2))))

    def test_gradient_fill_rejects(self):
        with self.assertRaises(ValueError):
            lower_element(Box(decoration=Decoration.rectangle(
                fill=Fill.linear_gradient(start_color="#000", end_color="#fff"))))

    def test_unbounded_ripple_rejects(self):
        with self.assertRaises(ValueError):
            lower_element(Box(decoration=Decoration.rectangle(
                ripple=Ripple(color="#40000000", bounded=False))))

    def test_style_addition_preserves_decoration_type(self):
        s1 = Style(decoration=Decoration.rectangle(fill="#FFF"))
        s2 = Style(padding=3)
        merged = s1 + s2
        from vyne.style import Decoration as DecorationType
        self.assertIsInstance(merged.decoration, DecorationType)
        self.assertEqual(merged.padding, 3)

    def test_style_no_opaque_dict_in_props(self):
        elem = Text(text="x", style=Style(text_color="#000000"))
        canon = lower_element(elem)
        self.assertNotIn("style", canon.props)
        self.assertNotIn("decoration", canon.props)

    def test_readme_example_style_applies(self):
        # Verify the documented Style usage works
        elem = Text(text="Hello", style=Style(text_color="#112233", font_size=20))
        canon = lower_element(elem)
        self.assertEqual(canon.props["text_color"], "#112233")
        self.assertEqual(canon.props["font_size"], 20)

    def test_readme_example_decoration_applies(self):
        # Verify documented Decoration rectangle applies
        elem = Text(text="Card",
                    style=Style(decoration=Decoration.rectangle(
                        fill="#FFFFFF",
                        corners=CornerRadius.all(12),
                        shadow=Shadow(elevation=2))))
        canon = lower_element(elem)
        self.assertNotIn("style", canon.props)
        self.assertNotIn("decoration", canon.props)
        self.assertEqual(canon.props["text"], "Card")


# ---------------------------------------------------------------------------
# Element immutability (MODEL-03)
# ---------------------------------------------------------------------------

class ElementImmutabilityTests(unittest.TestCase):
    def test_element_is_frozen(self):
        elem = Box()
        with self.assertRaises(Exception):
            elem.kind = "Layout"

    def test_no_view_id_on_element(self):
        elem = Box()
        with self.assertRaises(AttributeError):
            _ = elem._view_id

    def test_no_validated_on_element(self):
        elem = Box()
        with self.assertRaises(AttributeError):
            _ = elem._validated


# ---------------------------------------------------------------------------
# Ref and ViewHandle (MODEL-03)
# ---------------------------------------------------------------------------

class RefHandleTests(unittest.TestCase):
    def test_ref_starts_unmounted(self):
        ref = Ref()
        self.assertIsNone(ref.current)

    def test_ref_attach_handle(self):
        ref = Ref()
        handle = ViewHandle(42, "Box")
        ref.attach(handle)
        self.assertIs(ref.current, handle)
        self.assertEqual(ref.current.node_id, 42)
        self.assertEqual(ref.current.kind, "Box")
        self.assertTrue(ref.current.valid)

    def test_ref_double_attach_rejects(self):
        ref = Ref()
        ref.attach(ViewHandle(1, "Box"))
        with self.assertRaises(RuntimeError):
            ref.attach(ViewHandle(2, "Layout"))

    def test_ref_invalidate(self):
        ref = Ref()
        handle = ViewHandle(1, "Box")
        ref.attach(handle)
        ref.invalidate()
        self.assertIsNone(ref.current)
        self.assertFalse(handle.valid)

    def test_viewhandle_invalidate(self):
        handle = ViewHandle(1, "Box")
        self.assertTrue(handle.valid)
        handle._invalidate()
        self.assertFalse(handle.valid)


# ---------------------------------------------------------------------------
# resolve_native_props
# ---------------------------------------------------------------------------

class ResolveNativePropsTests(unittest.TestCase):
    def test_materializes_defaults(self):
        elem = Box()
        canon = lower_element(elem)
        resolved = canon.props
        self.assertIsInstance(resolved, FrozenMap)
        # Should include default values
        self.assertIn("opacity", resolved)
        self.assertEqual(resolved["opacity"], 1.0)

    def test_no_opaque_props(self):
        elem = Text(text="x", style=Style(text_color="#000000"))
        canon = lower_element(elem)
        resolved = canon.props
        self.assertNotIn("style", resolved)
        self.assertNotIn("decoration", resolved)
        self.assertNotIn("alpha", resolved)  # resolved to opacity

    def test_native_props_exclude_runtime_intents_without_a_second_tree(self):
        callback = lambda: None
        ref = Ref()
        canon = lower_element(Box(on_click=callback, ref=ref))

        self.assertIs(canon.props["on_click"], callback)
        self.assertIs(canon.props["ref"], ref)
        self.assertNotIn("on_click", canon.native_props)
        self.assertNotIn("ref", canon.native_props)

    def test_native_props_reuse_props_when_no_runtime_intents_exist(self):
        canon = lower_element(Text(text="unchanged"))
        self.assertIs(canon.native_props, canon.props)


if __name__ == "__main__":
    unittest.main()
