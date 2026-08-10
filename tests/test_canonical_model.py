"""Tests for canonical schema, values, lowering, and immutability.

Covers MODEL-01, MODEL-02, MODEL-03 requirements:
- FrozenMap immutability
- freeze/thaw and opaque-value rules
- Color and numeric validation helpers
- Schema completeness
- Canonical lowering and native-prop projection
- Per-mount refs/handles

ValueSpec validation lives in ``test_value_spec_validation``; style and
Decoration lowering behavior lives in ``test_style_decoration_behavior``,
``test_lowering_precedence``, and ``test_lowering_edges``.
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
from vyne.spec.schema_v2 import (
    ANIMATABLE_PROPS,
    PROPS_BY_KIND,
    PRIMITIVE_KINDS,
    GENERIC_PROP_NAMES,
    EVENT_SPECS,
)
from vyne.lowering import lower_element, CanonicalElement
from vyne.elements import (
    Element,
    Box, Layout, Row, Column, Text, TextInput, Image, Scroll, Path, Canvas,
)
from vyne.style import (
    Style, Decoration, Stroke, CornerRadius, Shadow, Ripple,
)
from vyne.refs import Ref


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
