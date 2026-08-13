"""Tests for Decoration behavior and unsupported field rejection (MODEL-02 / MO-4).

Covers:
- Unsupported/no-op fields reject with field paths
- Decoration.clip rejects (not yet implemented)
- Unknown decoration fields reject
- Literal supported README constructions lower to observable flat props
- No opaque decoration dicts in commits
- Gradient fills, dashed strokes, oval shapes reject
"""

from __future__ import annotations

import unittest

from vyne.lowering import lower_element
from vyne.elements import Box, Text
from vyne.style import (
    Decoration, Stroke, CornerRadius, Shadow, Ripple,
)


class UnsupportedFieldRejectionTests(unittest.TestCase):
    """MO-4: Unsupported/no-op fields reject with field paths."""

    def test_decoration_clip_rejects(self):
        """Decoration.clip must reject since clipping is not yet implemented
        as a canonical slot."""
        with self.assertRaises(ValueError) as ctx:
            lower_element(Box(decoration={"clip": True}))
        self.assertIn("clip", str(ctx.exception).lower(),
            "Error must mention 'clip'")

    def test_decoration_clip_false_also_rejects(self):
        """Decoration.clip=False also rejects — the field is not supported."""
        with self.assertRaises(ValueError):
            lower_element(Box(decoration={"clip": False}))

    def test_unknown_decoration_dict_field_rejects(self):
        """Unknown fields in a raw decoration dict must reject."""
        with self.assertRaises(ValueError):
            lower_element(Box(decoration={"bogus": True}))

    def test_gradient_fill_rejects(self):
        """Gradient fills are not yet supported."""
        with self.assertRaises(ValueError) as ctx:
            lower_element(Box(decoration=Decoration.rectangle(
                fill={"kind": "linear_gradient", "start_color": "#000", "end_color": "#fff"})))
        self.assertIn("gradient", str(ctx.exception).lower())

    def test_dashed_stroke_rejects(self):
        """Dashed strokes in Decoration are not yet supported."""
        with self.assertRaises(ValueError) as ctx:
            lower_element(Box(decoration=Decoration.rectangle(
                stroke={"color": "#000", "dash_width": 4, "dash_gap": 2})))
        self.assertIn("dash", str(ctx.exception).lower())

    def test_oval_shape_rejects(self):
        """Non-rectangle shapes are not yet supported."""
        with self.assertRaises(ValueError) as ctx:
            lower_element(Box(decoration=Decoration(
                shape={"kind": "oval", "fill": "#FF0000"})))
        self.assertIn("oval", str(ctx.exception).lower())

    def test_unbounded_ripple_rejects(self):
        """Unbounded ripple is not yet supported."""
        with self.assertRaises(ValueError):
            lower_element(Box(decoration=Decoration.rectangle(
                ripple={"color": "#40000000", "bounded": False})))

    def test_translation_z_rejects(self):
        """Shadow.translation_z is not yet supported."""
        with self.assertRaises(ValueError) as ctx:
            lower_element(Box(decoration=Decoration.rectangle(
                shadow={"elevation": 4, "translation_z": 10})))
        self.assertIn("translation_z", str(ctx.exception).lower())

    def test_size_shorthand_rejects(self):
        """size shorthand is not yet supported."""
        with self.assertRaises(ValueError):
            lower_element(Box(size=100))


class SupportedConstructionTests(unittest.TestCase):
    """MO-4: Literal supported README constructions lower to observable flat props."""

    def test_readme_direct_props_example_lowers(self):
        elem = Text(text="Todo List", text_color="#172554", font_size=24)
        canon = lower_element(elem)
        self.assertEqual(canon.props["text"], "Todo List")
        self.assertEqual(canon.props["text_color"], "#172554")
        self.assertEqual(canon.props["font_size"], 24)

    def test_readme_decoration_example_structure(self):
        """The documented Decoration.rectangle usage lowers correctly."""
        # From README: Decoration.rectangle(fill="#FAFAFA", corners=CornerRadius.all(16))
        elem = Text(
            text="Card",
            padding=12,
            decoration=Decoration.rectangle(
                fill="#FAFAFA",
                corners=CornerRadius.all(16),
                shadow=Shadow(elevation=2),
            ),
        )
        canon = lower_element(elem)
        # Should lower background_color, padding edges, corner radii, elevation
        self.assertIn("background_color", canon.props)
        self.assertIn("elevation", canon.props)
        self.assertIn("padding_top", canon.props)
        # No opaque decoration
        self.assertNotIn("decoration", canon.props)

    def test_solid_fill_string_lowers(self):
        """Fill as a plain color string works."""
        canon = lower_element(Box(decoration=Decoration.rectangle(fill="#ABCDEF")))
        self.assertEqual(canon.props["background_color"], "#ABCDEF")

    def test_stroke_without_dash_lowers(self):
        """Solid stroke (no dash) lowers to border_color/border_width."""
        canon = lower_element(Box(decoration=Decoration.rectangle(
            stroke=Stroke(color="#000000", width=2))))
        self.assertEqual(canon.props["border_color"], "#000000")
        self.assertEqual(canon.props["border_width"], 2)

    def test_corners_all_lowers(self):
        """CornerRadius.all() lowers to four corner props."""
        canon = lower_element(Box(decoration=Decoration.rectangle(
            corners=CornerRadius.all(12))))
        self.assertEqual(canon.props["corner_radius_top_left"], 12)
        self.assertEqual(canon.props["corner_radius_bottom_right"], 12)

    def test_corners_only_lowers(self):
        """CornerRadius.only() lowers individual corners."""
        canon = lower_element(Box(decoration=Decoration.rectangle(
            corners=CornerRadius.only(top_left=4, bottom_right=8))))
        self.assertEqual(canon.props["corner_radius_top_left"], 4)
        self.assertEqual(canon.props["corner_radius_bottom_right"], 8)
        # Unspecified corners are not materialized (drop_default=True).
        self.assertNotIn("corner_radius_top_right", canon.props)
        self.assertNotIn("corner_radius_bottom_left", canon.props)

    def test_shadow_elevation_lowers(self):
        """Shadow elevation lowers to elevation prop."""
        canon = lower_element(Box(decoration=Decoration.rectangle(
            shadow=Shadow(elevation=4))))
        self.assertEqual(canon.props["elevation"], 4)

    def test_ripple_color_lowers(self):
        """Ripple color lowers to ripple_color prop."""
        canon = lower_element(Box(decoration=Decoration.rectangle(
            ripple=Ripple(color="#40000000"))))
        self.assertEqual(canon.props["ripple_color"], "#40000000")

    def test_no_opaque_decoration_in_props(self):
        """After lowering, no decoration dict remains."""
        elem = Text(
            text="Test",
            text_color="#111111",
            font_size=16,
            decoration=Decoration.rectangle(
                fill="#FFFFFF",
                corners=CornerRadius.all(8),
                shadow=Shadow(elevation=1),
            ),
        )
        canon = lower_element(elem)
        self.assertNotIn("decoration", canon.props)


class DecorationDictInputTests(unittest.TestCase):
    def test_decoration_dict_known_fields_work(self):
        """A raw dict for decoration lowers correctly."""
        canon = lower_element(Box(decoration={
            "shape": {"kind": "rectangle", "fill": "#FF0000"},
            "shadow": {"elevation": 4},
        }))
        self.assertEqual(canon.props["background_color"], "#FF0000")
        self.assertEqual(canon.props["elevation"], 4)

    def test_decoration_dict_unknown_fields_reject(self):
        """A raw decoration dict with unknown fields rejects."""
        with self.assertRaises(ValueError):
            lower_element(Box(decoration={"shape": {"kind": "rectangle"}, "unknown": True}))


if __name__ == "__main__":
    unittest.main()
