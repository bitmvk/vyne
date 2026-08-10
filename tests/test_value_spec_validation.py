"""Caveat tests for the schema ValueSpec domain validator.

The ValueSpec contract guards every prop crossing the wire: types,
ranges, enums, colors, dimensions, dash arrays, collection shapes,
and the animated-node marker pass-through.
"""

from __future__ import annotations

import math
import unittest

from vyne.spec.model import ValueSpec
from vyne.values import FrozenMap


class TypeContractTests(unittest.TestCase):
    def test_null_rejected_unless_nullable(self):
        with self.assertRaisesRegex(TypeError, "null"):
            ValueSpec().validate(None)
        ValueSpec(nullable=True).validate(None)

    def test_exact_types_are_exact_not_isinstance(self):
        spec = ValueSpec(exact_types=(int,))
        spec.validate(5)
        # bool is a subclass of int but must not pass an exact check
        with self.assertRaises(TypeError):
            spec.validate(True)
        with self.assertRaises(TypeError):
            spec.validate(5.0)

    def test_type_name_matching(self):
        ValueSpec(type_name="str").validate("x")
        with self.assertRaises(TypeError):
            ValueSpec(type_name="str").validate(1)
        ValueSpec(type_name="number").validate(1.5)
        with self.assertRaises(TypeError):
            ValueSpec(type_name="bool").validate(1)

    def test_unknown_type_name_is_a_schema_bug(self):
        with self.assertRaises(RuntimeError):
            ValueSpec(type_name="wat").validate("x")


class NumericConstraintTests(unittest.TestCase):
    def test_finite(self):
        ValueSpec(finite=True).validate(1.5)
        with self.assertRaises((TypeError, ValueError)):
            ValueSpec(finite=True).validate(math.inf)

    def test_positive_and_non_negative(self):
        ValueSpec(positive=True).validate(0.5)
        with self.assertRaises((TypeError, ValueError)):
            ValueSpec(positive=True).validate(0)
        ValueSpec(non_negative=True).validate(0)
        with self.assertRaises((TypeError, ValueError)):
            ValueSpec(non_negative=True).validate(-1)

    def test_min_max_bounds(self):
        spec = ValueSpec(min_value=0, max_value=1)
        spec.validate(0.5)
        with self.assertRaisesRegex(ValueError, ">= 0"):
            spec.validate(-0.1)
        with self.assertRaisesRegex(ValueError, "<= 1"):
            spec.validate(1.1)
        with self.assertRaises(TypeError):
            spec.validate("0.5")

    def test_collections_cannot_bypass_scalar_domain(self):
        """A numeric spec applied to a list is a type error, not a pass."""
        with self.assertRaisesRegex(TypeError, "finite number"):
            ValueSpec(finite=True).validate([1, 2, 3])


class EnumColorDimensionTests(unittest.TestCase):
    def test_enum(self):
        spec = ValueSpec(enum=frozenset({"horizontal", "vertical"}))
        spec.validate("horizontal")
        with self.assertRaisesRegex(ValueError, "one of"):
            spec.validate("diagonal")
        with self.assertRaises(TypeError):
            spec.validate(1)

    def test_color_formats(self):
        spec = ValueSpec(color=True)
        spec.validate("#RRGGBB".replace("RRGGBB", "a1b2c3"))
        spec.validate("#a1b2c3d4")
        for bad in ("a1b2c3", "#12345", "#1234567", "#gg0000", "red"):
            with self.subTest(color=bad):
                with self.assertRaisesRegex(ValueError, "#RRGGBB"):
                    spec.validate(bad)

    def test_dimension_forms(self):
        spec = ValueSpec(dimension=True)
        for good in (0, 16, 2.5, "wrap_content", "match_parent", "16dp", "0.5dp"):
            with self.subTest(value=good):
                spec.validate(good)

    def test_dimension_rejections(self):
        spec = ValueSpec(dimension=True)
        for bad in (True, -1, math.inf, "16", "16px", "dp", "-4dp", "wrap-content"):
            with self.subTest(value=bad):
                with self.assertRaises((TypeError, ValueError)):
                    spec.validate(bad)

    def test_dash_array(self):
        spec = ValueSpec(dash_array=True)
        spec.validate((4.0, 8.0))
        spec.validate("full")  # PathView-resolved marker
        with self.assertRaises(ValueError):
            spec.validate((4, 8, 2))      # odd length
        with self.assertRaises(ValueError):
            spec.validate((4, 0))          # non-positive
        with self.assertRaises((TypeError, ValueError)):
            spec.validate("4,8")           # string form is lowered earlier

    def test_string_map_requires_frozen_map(self):
        spec = ValueSpec(string_map=True)
        spec.validate(FrozenMap([("a", 1)]))
        with self.assertRaises(TypeError):
            spec.validate({"a": 1})


class CollectionShapeTests(unittest.TestCase):
    def test_item_spec_applies_elementwise(self):
        spec = ValueSpec(item_spec=ValueSpec(finite=True))
        spec.validate([1, 2.5, 3])
        with self.assertRaises((TypeError, ValueError)):
            spec.validate([1, "x"])

    def test_min_max_items(self):
        spec = ValueSpec(min_items=2, max_items=4)
        spec.validate([1, 2, 3])
        with self.assertRaisesRegex(ValueError, "at least 2"):
            spec.validate([1])
        with self.assertRaisesRegex(ValueError, "at most 4"):
            spec.validate([1, 2, 3, 4, 5])

    def test_collection_constraints_require_list_or_tuple(self):
        with self.assertRaisesRegex(TypeError, "list or tuple"):
            ValueSpec(min_items=1).validate("abc")
        with self.assertRaisesRegex(TypeError, "list or tuple"):
            ValueSpec(min_items=1).validate({"a": 1})


class AnimatedMarkerTests(unittest.TestCase):
    MARKER = "__vyne_animated_node__"

    def test_marker_validates_inner_value(self):
        spec = ValueSpec(min_value=0, max_value=1)
        spec.validate({self.MARKER: True, "value": 0.5})
        with self.assertRaises(ValueError):
            spec.validate({self.MARKER: True, "value": 9.5})

    def test_marker_requires_value_key(self):
        with self.assertRaisesRegex(TypeError, "requires value"):
            ValueSpec().validate({self.MARKER: True})

    def test_marker_works_in_frozen_map(self):
        spec = ValueSpec(type_name="number")
        spec.validate(FrozenMap([(self.MARKER, True), ("value", 0.5)]))

    def test_plain_dicts_still_validate_normally(self):
        """A dict without the marker is not treated as animated."""
        spec = ValueSpec(type_name="number")
        with self.assertRaises(TypeError):
            spec.validate({"value": 0.5})


if __name__ == "__main__":
    unittest.main()
