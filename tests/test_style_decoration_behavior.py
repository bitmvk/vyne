"""Tests for Style/Decoration behavior and unsupported field rejection (MODEL-02 / MO-4).

Covers:
- Unsupported/no-op fields reject with field paths
- Decoration.clip rejects (not yet implemented)
- Unknown style dict fields reject
- Unknown decoration fields reject
- Literal supported README constructions lower to observable flat props
- No opaque style/decoration dicts in commits
- Gradient fills, dashed strokes, oval shapes reject
"""

from __future__ import annotations

import unittest

from vyne.values import FrozenMap
from vyne.lowering import lower_element, CanonicalElement
from vyne.elements import Box, Text, Layout
from vyne.style import (
    Style, Decoration, Fill, Stroke, CornerRadius, Shadow, Ripple, Shape,
)


class UnsupportedFieldRejectionTests(unittest.TestCase):
    """MO-4: Unsupported/no-op fields reject with field paths."""

    def test_decoration_clip_rejects(self):
        """Decoration.clip must reject since clipping is not yet implemented
        as a canonical slot."""
        with self.assertRaises(ValueError) as ctx:
            lower_element(Box(decoration=Decoration.rectangle(clip=True)))
        self.assertIn("clip", str(ctx.exception).lower(),
            "Error must mention 'clip'")

    def test_decoration_clip_false_also_rejects(self):
        """Decoration.clip=False also rejects — the field is not supported."""
        with self.assertRaises(ValueError):
            lower_element(Box(decoration=Decoration.rectangle(clip=False)))

    def test_unknown_style_dict_field_rejects(self):
        """Unknown fields in a raw style dict must reject."""
        with self.assertRaises(ValueError) as ctx:
            lower_element(Box(style={"mystery_effect": 123}))
        self.assertIn("mystery_effect", str(ctx.exception),
            "Error must name the unknown field")

    def test_unknown_style_dict_multiple_fields_reject(self):
        """Multiple unknown fields — first one rejects."""
        with self.assertRaises(ValueError):
            lower_element(Box(style={"unknown_a": 1, "unknown_b": 2}))

    def test_unknown_decoration_dict_field_rejects(self):
        """Unknown fields in a raw decoration dict must reject."""
        with self.assertRaises(ValueError):
            lower_element(Box(decoration={"bogus": True}))

    def test_gradient_fill_rejects(self):
        """Gradient fills are not yet supported."""
        with self.assertRaises(ValueError) as ctx:
            lower_element(Box(decoration=Decoration.rectangle(
                fill=Fill.linear_gradient(start_color="#000", end_color="#fff"))))
        self.assertIn("gradient", str(ctx.exception).lower())

    def test_dashed_stroke_rejects(self):
        """Dashed strokes in Decoration are not yet supported."""
        with self.assertRaises(ValueError) as ctx:
            lower_element(Box(decoration=Decoration.rectangle(
                stroke=Stroke(color="#000", dash_width=4, dash_gap=2))))
        self.assertIn("dash", str(ctx.exception).lower())

    def test_oval_shape_rejects(self):
        """Non-rectangle shapes are not yet supported."""
        with self.assertRaises(ValueError) as ctx:
            lower_element(Box(decoration=Decoration(
                shape=Shape.oval(fill="#FF0000"))))
        self.assertIn("oval", str(ctx.exception).lower())

    def test_unbounded_ripple_rejects(self):
        """Unbounded ripple is not yet supported."""
        with self.assertRaises(ValueError):
            lower_element(Box(decoration=Decoration.rectangle(
                ripple=Ripple(color="#40000000", bounded=False))))

    def test_translation_z_rejects(self):
        """Shadow.translation_z is not yet supported."""
        with self.assertRaises(ValueError) as ctx:
            lower_element(Box(decoration=Decoration.rectangle(
                shadow=Shadow(elevation=4, translation_z=10))))
        self.assertIn("translation_z", str(ctx.exception).lower())

    def test_unsupported_style_fields_reject(self):
        """Unsupported Style fields (gap, size, flex, etc.) reject."""
        for bad_field, bad_val in [
            ("gap", 10),
            ("flex", 1),
            ("flex_grow", 1),
            ("flex_shrink", 1),
            ("align_self", "center"),
        ]:
            with self.subTest(field=bad_field):
                with self.assertRaises(ValueError):
                    lower_element(Box(style=Style(**{bad_field: bad_val})))

    def test_size_shorthand_rejects(self):
        """size shorthand is not yet supported."""
        with self.assertRaises(ValueError):
            lower_element(Box(size=100))


class SupportedConstructionTests(unittest.TestCase):
    """MO-4: Literal supported README constructions lower to observable flat props."""

    def test_readme_style_example_lowers(self):
        """The documented Style usage must lower to flat props."""
        # From README: style=Style(text_color="#172554", font_size=24)
        elem = Text(text="Todo List",
                     style=Style(text_color="#172554", font_size=24))
        canon = lower_element(elem)
        self.assertEqual(canon.props["text"], "Todo List")
        self.assertEqual(canon.props["text_color"], "#172554")
        self.assertEqual(canon.props["font_size"], 24)
        # No opaque props
        self.assertNotIn("style", canon.props)

    def test_readme_decoration_example_structure(self):
        """The documented Decoration.rectangle usage lowers correctly."""
        # From README: Decoration.rectangle(fill="#FAFAFA", corners=CornerRadius.all(16))
        elem = Text(
            text="Card",
            style=Style(
                padding=12,
                decoration=Decoration.rectangle(
                    fill="#FAFAFA",
                    corners=CornerRadius.all(16),
                    shadow=Shadow(elevation=2),
                ),
            ),
        )
        canon = lower_element(elem)
        # Should lower background_color, padding edges, corner radii, elevation
        self.assertIn("background_color", canon.props)
        self.assertIn("elevation", canon.props)
        self.assertIn("padding_top", canon.props)
        # No opaque style/decoration
        self.assertNotIn("style", canon.props)
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

    def test_no_opaque_style_or_decoration_in_props(self):
        """After lowering, no style or decoration dicts remain."""
        elem = Text(
            text="Test",
            style=Style(
                text_color="#111111",
                font_size=16,
                decoration=Decoration.rectangle(
                    fill="#FFFFFF",
                    corners=CornerRadius.all(8),
                    shadow=Shadow(elevation=1),
                ),
            ),
        )
        canon = lower_element(elem)
        for name in canon.props:
            self.assertNotIn(name, ("style", "decoration"),
                f"Opaque prop {name!r} found in lowered props")

    def test_style_addition_preserves_types(self):
        """Style.__add__ preserves Decoration type."""
        s1 = Style(decoration=Decoration.rectangle(fill="#FFF"))
        s2 = Style(padding=3)
        merged = s1 + s2
        from vyne.style import Decoration as DecorationType
        self.assertIsInstance(merged.decoration, DecorationType)
        self.assertEqual(merged.padding, 3)

    def test_empty_style_is_ok(self):
        """Empty Style() does nothing."""
        canon = lower_element(Box(style=Style()))
        self.assertIsInstance(canon, CanonicalElement)

    def test_none_style_is_ok(self):
        """None style is silently ignored."""
        canon = lower_element(Box(style=None))
        self.assertIsInstance(canon, CanonicalElement)


class StyleDictInputTests(unittest.TestCase):
    """Style as raw dict input support."""

    def test_style_dict_known_fields_work(self):
        """A raw dict with known style fields lowers correctly."""
        canon = lower_element(Text(text="x", style={"text_color": "#FF0000", "font_size": 20}))
        self.assertEqual(canon.props["text_color"], "#FF0000")
        self.assertEqual(canon.props["font_size"], 20)

    def test_style_dict_unknown_fields_reject(self):
        """A raw dict with unknown fields rejects."""
        with self.assertRaises(ValueError):
            lower_element(Box(style={"text_color": "#000", "bogus": 1}))

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
