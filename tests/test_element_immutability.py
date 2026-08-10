"""Tests for deep Element immutability (MODEL-02 / MO-1).

Covers:
- Raw Element construction must produce frozen props
- Helper constructors produce deeply immutable values
- FrozenMap deep freeze prevents nested mutation
- CanonicalElement has coherent structural equality/hash
- Keys must be hashable at construction time
- No mutable escape hatches
"""

from __future__ import annotations

import unittest

from vyne.values import FrozenMap, freeze, thaw
from vyne.lowering import lower_element, CanonicalElement
from vyne.elements import (
    Element,
    Box, Text, Layout, Row, Column, Canvas,
)
from vyne.style import Style, Decoration, Fill


class ElementConstructionImmutabilityTests(unittest.TestCase):
    """MO-1: Raw and helper-created Elements cannot expose mutable nested
    props/children/keys, including pre-existing FrozenMaps."""

    def test_raw_element_with_dict_props_becomes_frozen(self):
        """Direct Element construction must not retain a mutable dict."""
        elem = Element(kind="Box", props={"background_color": "#FF0000"})
        # The props attribute should be frozen
        self.assertIsInstance(elem.props, FrozenMap)

    def test_raw_element_props_cannot_be_mutated(self):
        """Props dict passed to Element must be deep-frozen."""
        d = {"background_color": "#FF0000", "nested": [1, 2, 3]}
        elem = Element(kind="Box", props=d)
        # Mutating original dict should not affect element
        d["background_color"] = "#000000"
        self.assertEqual(elem.props["background_color"], "#FF0000")
        # Mutating nested list should not affect element
        d["nested"].append(4)
        self.assertEqual(len(elem.props["nested"]), 3)

    def test_tuple_mapping_list_and_existing_frozenmap_are_copied(self):
        leaf = [1, 2]
        nested = {"leaf": leaf}
        caller = {"key": "kept", "nested": (nested,)}
        elem = Element("Box", caller)
        before_hash = hash(elem)

        leaf.append(3)
        nested["other"] = 4
        caller["key"] = "changed"

        self.assertEqual(elem.props["key"], "kept")
        self.assertEqual(elem.props["nested"][0]["leaf"], (1, 2))
        self.assertEqual(hash(elem), before_hash)

        escaped = {"values": [5]}
        elem2 = Element("Box", FrozenMap((("nested", (escaped,)),)))
        escaped["values"].append(6)
        self.assertEqual(elem2.props["nested"][0]["values"], (5,))

    def test_direct_construction_never_removes_caller_key(self):
        caller = {"key": "stable", "background_color": "#FF0000"}
        Element("Box", caller)
        self.assertEqual(caller["key"], "stable")

    def test_helper_constructed_elements_are_deeply_immutable(self):
        """Box(), Text(), etc. must produce deeply frozen props."""
        elem = Box(background_color="#FF0000")
        self.assertIsInstance(elem.props, FrozenMap)
        # Element is frozen dataclass - reassignment fails
        with self.assertRaises(Exception):
            elem.kind = "Layout"

    def test_canvas_draw_list_is_deeply_frozen(self):
        """Canvas draw operations must be immutable tuples, not mutable lists."""
        draw = [{"kind": "rect", "x": 0, "y": 0, "width": 10, "height": 10}]
        elem = Canvas(draw=draw)
        # The draw list should be frozen to a tuple (via freeze)
        draw_val = elem.props["draw"]
        self.assertIsInstance(draw_val, tuple,
            f"Canvas draw should be frozen tuple, got {type(draw_val).__name__}")
        # Mutating original should not affect element
        draw.append({"kind": "circle", "cx": 5, "cy": 5, "radius": 3})
        self.assertEqual(len(elem.props["draw"]), 1,
            "Original list mutation should not propagate to frozen props")

    def test_keys_must_be_hashable_at_construction(self):
        """Mutable keys must reject at Element construction time."""
        # Covered in full by test_bool_float_and_mutable_keys_are_rejected;
        # this smoke keeps the construction-time message check local.
        with self.assertRaises((TypeError, ValueError)):
            Box(key=[1, 2, 3])

    def test_string_keys_are_preserved(self):
        """String keys pass through without issue."""
        elem = Box(key="my-key")
        self.assertEqual(elem.props["key"], "my-key")

    def test_none_key_is_fine(self):
        """None key is acceptable."""
        elem = Box(key=None)
        self.assertIsNone(elem.props.get("key"))

    def test_numeric_keys_work(self):
        """Numeric keys are hashable and pass through."""
        elem = Box(key=42)
        self.assertEqual(elem.props["key"], 42)

    def test_frozenmap_with_nested_dict_remains_immutable(self):
        """freeze(FrozenMap({...})) must recursively freeze nested values."""
        inner_dict = {"a": 1, "b": [2, 3]}
        fm = FrozenMap([("nested", inner_dict)])
        # Even though inner_dict is itself mutable, freeze should deep-copy
        frozen = freeze(fm)
        self.assertIsInstance(frozen, FrozenMap)
        # The nested value should also be frozen
        nested_val = frozen["nested"]
        self.assertIsInstance(nested_val, FrozenMap,
            f"Nested dict in FrozenMap should be deep-frozen, got {type(nested_val).__name__}")
        # The nested list should be a tuple
        self.assertIsInstance(nested_val["b"], tuple,
            f"Nested list should be tuple, got {type(nested_val['b']).__name__}")

    def test_frozenmap_from_dict_deep(self):
        """FrozenMap.from_dict(deep=True) must deep-freeze."""
        d = {"colors": ["#FF0000", "#00FF00"], "nested": {"a": [1, 2]}}
        fm = FrozenMap.from_dict(d, deep=True)
        # Top level is FrozenMap
        self.assertIsInstance(fm, FrozenMap)
        # colors list should be tuple
        self.assertIsInstance(fm["colors"], tuple)
        # nested dict should be FrozenMap
        self.assertIsInstance(fm["nested"], FrozenMap)
        # deep within nested
        self.assertIsInstance(fm["nested"]["a"], tuple)

    def test_no_internal_ids_on_element(self):
        """Element must have no _view_id, _validated, or other runtime IDs."""
        elem = Box(key="x")
        for forbidden in ("_view_id", "_validated", "_output_id"):
            with self.assertRaises(AttributeError, msg=f"Should not have {forbidden}"):
                getattr(elem, forbidden)

    def test_element_children_are_immutable_tuple(self):
        """Children are a tuple, preserving immutability."""
        elem = Box(Text(text="a"), Text(text="b"))
        self.assertIsInstance(elem.children, tuple)
        self.assertEqual(len(elem.children), 2)

    def test_element_equality_is_structural(self):
        """Two Elements with same kind/props/children should be equal."""
        e1 = Box(key="a", background_color="#FF0000")
        e2 = Box(key="a", background_color="#FF0000")
        self.assertEqual(e1, e2)

    def test_element_hash_is_stable(self):
        """Same Element content should produce same hash."""
        e1 = Box(key="a", background_color="#FF0000")
        e2 = Box(key="a", background_color="#FF0000")
        self.assertEqual(hash(e1), hash(e2))


class CanonicalElementIdentityTests(unittest.TestCase):
    """CanonicalElement must have coherent structural equality/hash."""

    def test_canonical_equality_is_structural(self):
        """Two CanonicalElements with same kind/props/children/keys must be equal."""
        e1 = Box(key="a", background_color="#FF0000")
        e2 = Box(key="a", background_color="#FF0000")
        c1 = lower_element(e1)
        c2 = lower_element(e2)
        self.assertEqual(c1, c2,
            "CanonicalElements with identical structure must be equal")
        self.assertEqual(c1.kind, c2.kind)
        self.assertEqual(c1.key, c2.key)
        self.assertEqual(c1.props, c2.props)

    def test_canonical_hash_is_structural(self):
        """Two equal CanonicalElements must have the same hash."""
        e1 = Box(key="a", background_color="#FF0000")
        e2 = Box(key="a", background_color="#FF0000")
        c1 = lower_element(e1)
        c2 = lower_element(e2)
        self.assertEqual(hash(c1), hash(c2),
            "Equal CanonicalElements must have the same hash")

    def test_canonical_different_keys_are_not_equal(self):
        """Different keys produce different CanonicalElements."""
        c1 = lower_element(Box(key="a"))
        c2 = lower_element(Box(key="b"))
        self.assertNotEqual(c1, c2)

    def test_canonical_different_props_are_not_equal(self):
        """Different props produce different CanonicalElements."""
        c1 = lower_element(Box(background_color="#FF0000"))
        c2 = lower_element(Box(background_color="#000000"))
        self.assertNotEqual(c1, c2)

    def test_no_output_id_on_canonical(self):
        """CanonicalElement must not carry output_id cache field."""
        elem = Box()
        canon = lower_element(elem)
        with self.assertRaises(AttributeError):
            _ = canon.output_id

    def test_canonical_key_hashable_required(self):
        """Non-hashable keys must reject in CanonicalElement."""
        with self.assertRaises(TypeError):
            lower_element(Element(kind="Box", props=FrozenMap([("key", [1, 2])])))

    def test_mutable_opaque_hashable_key_is_rejected(self):
        class MutableHashable:
            def __init__(self) -> None:
                self.value = 1

            def __hash__(self) -> int:
                return self.value

        with self.assertRaisesRegex(TypeError, "Element key"):
            Box(key=MutableHashable())

    def test_canonical_tuple_key_is_stable(self):
        key = ("row", 3, ("cell", 1))
        element = Box(key=key)
        canonical = lower_element(element)
        self.assertEqual(canonical.key, key)
        self.assertEqual(hash(canonical.key), hash(key))

    def test_bool_float_and_mutable_keys_are_rejected(self):
        for key in (True, 1.5, ["x"], {"x": 1}):
            with self.subTest(key=key):
                with self.assertRaises(TypeError):
                    Box(key=key)


if __name__ == "__main__":
    unittest.main()
