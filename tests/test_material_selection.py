"""MATERIAL-02: Selection normalizer for ButtonGroup/SegmentedButtonGroup.

Tests for:
- Unique and hashable item values
- Scalar vs multi-select modes
- No string splitting
- Falsy value handling
- Ordered callback tuples
- Duplicate/unhashable value rejection
"""

from __future__ import annotations

import unittest

from vyne.material._callbacks import normalize_selection


class SelectionNormalizerScalarTests(unittest.TestCase):
    """Single-selection (scalar) mode."""

    def test_selected_value_matches_item(self):
        result = normalize_selection("a", ["a", "b", "c"], multi=False)
        self.assertEqual(result, "a")

    def test_none_selection_returns_none(self):
        result = normalize_selection(None, ["a", "b", "c"], multi=False)
        self.assertIsNone(result)

    def test_int_zero_is_valid_selection(self):
        """0 is a valid item value, not treated as falsy-empty."""
        result = normalize_selection(0, [0, 1, 2], multi=False)
        self.assertEqual(result, 0)

    def test_false_is_valid_selection(self):
        result = normalize_selection(False, [True, False], multi=False)
        self.assertEqual(result, False)

    def test_true_is_valid_selection(self):
        result = normalize_selection(True, [True, False], multi=False)
        self.assertEqual(result, True)

    def test_empty_string_valid_as_value(self):
        result = normalize_selection("", ["", "a", "b"], multi=False)
        self.assertEqual(result, "")

    def test_unknown_scalar_value_raises(self):
        with self.assertRaises(ValueError):
            normalize_selection("x", ["a", "b"], multi=False)


class SelectionNormalizerMultiTests(unittest.TestCase):
    """Multi-selection mode."""

    def test_multi_selected_set(self):
        result = normalize_selection(["a", "b"], ["a", "b", "c"], multi=True)
        self.assertIsInstance(result, frozenset)
        self.assertEqual(result, frozenset(["a", "b"]))

    def test_multi_none_returns_empty(self):
        result = normalize_selection(None, ["a", "b"], multi=True)
        self.assertEqual(result, frozenset())

    def test_multi_tuple_input(self):
        result = normalize_selection(("a",), ["a", "b"], multi=True)
        self.assertEqual(result, frozenset(["a"]))

    def test_multi_empty_list(self):
        result = normalize_selection([], ["a", "b"], multi=True)
        self.assertEqual(result, frozenset())

    def test_multi_rejects_string(self):
        """Strings must not be split into characters."""
        with self.assertRaises(TypeError):
            normalize_selection("ab", ["a", "b", "ab"], multi=True)

    def test_multi_rejects_bytes(self):
        with self.assertRaises(TypeError):
            normalize_selection(b"ab", [b"a", b"b", b"ab"], multi=True)

    def test_multi_rejects_bool(self):
        with self.assertRaises(TypeError):
            normalize_selection(False, [True, False], multi=True)

    def test_multi_unknown_value_raises(self):
        with self.assertRaises(ValueError):
            normalize_selection(["a", "x"], ["a", "b"], multi=True)

    def test_multi_int_zero_included(self):
        result = normalize_selection([0], [0, 1, 2], multi=True)
        self.assertEqual(result, frozenset([0]))


class SelectionNormalizerValidationTests(unittest.TestCase):
    """Item value validation: unique, hashable."""

    def test_duplicate_item_values_rejected(self):
        with self.assertRaises(ValueError):
            normalize_selection("a", ["a", "a"], multi=False)

    def test_unhashable_item_value_rejected(self):
        with self.assertRaises(TypeError):
            normalize_selection(None, [[], {}], multi=False)

    def test_unhashable_selected_value_rejected(self):
        with self.assertRaises(TypeError):
            normalize_selection([], [[], "a"], multi=False)

    def test_unhashable_multi_value_rejected(self):
        with self.assertRaises(TypeError):
            normalize_selection([[]], [[], "a"], multi=True)

    def test_non_iterable_multi_raises(self):
        with self.assertRaises(TypeError):
            normalize_selection(42, ["a", "b"], multi=True)


if __name__ == "__main__":
    unittest.main()
