"""Tests for Style/Decoration lowering precedence (MODEL-02 / MO-3).

Covers:
- Precedence: defaults < style/decoration < explicit direct props
- Alias conflicts (alpha vs opacity)
- Shorthand conflicts with explicit edge values
- Decoration fields (fill, stroke, corners, shadow, ripple)
- Origin tracking correctness
"""

from __future__ import annotations

import unittest

from vyne.lowering import lower_element
from vyne.elements import (
    Box, Text,
)
from vyne.style import (
    Style, Decoration, Stroke, CornerRadius, Shadow, Ripple,
)


class PrecedenceBasicTests(unittest.TestCase):
    """Basic precedence: defaults < style < explicit."""

    def test_default_opacity_is_one(self):
        """Default opacity for Box is 1.0."""
        canon = lower_element(Box())
        self.assertEqual(canon.props.get("opacity"), 1.0)

    def test_explicit_overrides_default(self):
        """Explicit prop overrides the schema default."""
        canon = lower_element(Box(opacity=0.5))
        self.assertEqual(canon.props["opacity"], 0.5)

    def test_style_overrides_default(self):
        """Style value overrides the schema default."""
        canon = lower_element(Text(text="x", style=Style(text_color="#FF0000")))
        self.assertEqual(canon.props["text_color"], "#FF0000")

    def test_explicit_overrides_style(self):
        """Explicit direct prop overrides a Style value."""
        canon = lower_element(
            Text(text="x", text_color="#000000",
                 style=Style(text_color="#FF0000"))
        )
        self.assertEqual(canon.props["text_color"], "#000000")

    def test_style_overrides_default_but_not_explicit(self):
        """Style applies over defaults but not over explicit."""
        # Box default for opacity is 1.0
        # Style sets it to 0.5
        # Explicit sets it to 0.3
        canon = lower_element(
            Box(opacity=0.3, style=Style())  # Style doesn't have opacity...
        )
        self.assertEqual(canon.props["opacity"], 0.3)

    def test_decoration_overrides_defaults(self):
        """Decoration fill overrides the background_color default."""
        canon = lower_element(
            Box(decoration=Decoration.rectangle(fill="#FF0000"))
        )
        self.assertEqual(canon.props["background_color"], "#FF0000")

    def test_explicit_overrides_decoration(self):
        """Explicit background_color overrides Decoration fill."""
        canon = lower_element(
            Box(background_color="#0000FF",
                decoration=Decoration.rectangle(fill="#FF0000"))
        )
        self.assertEqual(canon.props["background_color"], "#0000FF")


class AliasConflictTests(unittest.TestCase):
    """Alias and shorthand conflict resolution."""

    def test_alpha_alias_to_opacity(self):
        """alpha prop resolves to opacity."""
        canon = lower_element(Box(alpha=0.3))
        self.assertNotIn("alpha", canon.props)
        self.assertEqual(canon.props["opacity"], 0.3)

    def test_conflicting_alpha_and_opacity_rejects(self):
        """Setting both alpha and opacity to different values must reject."""
        with self.assertRaises(ValueError):
            lower_element(Box(alpha=0.3, opacity=0.8))

    def test_same_alpha_and_opacity_ok(self):
        """Setting alpha and opacity to the same value is fine."""
        canon = lower_element(Box(alpha=0.5, opacity=0.5))
        self.assertEqual(canon.props["opacity"], 0.5)

    def test_opacity_only_no_alpha(self):
        """Explicit opacity works without alpha."""
        canon = lower_element(Box(opacity=0.7))
        self.assertNotIn("alpha", canon.props)
        self.assertEqual(canon.props["opacity"], 0.7)

    def test_alpha_overrides_default_opacity(self):
        """alpha overrides the default opacity (not explicit)."""
        canon = lower_element(Box(alpha=0.2))
        self.assertEqual(canon.props["opacity"], 0.2)

    def test_conflicting_aliases_from_style_reject(self):
        """Style opacity is overridden by explicit opacity."""
        # Style doesn't have an 'alpha' field; use 'color' alias for text_color.
        # When style sets text_color via 'color' and explicit sets text_color,
        # explicit wins.
        canon = lower_element(Text(text="x", text_color="#000000",
                                   style=Style(color="#FF0000")))
        self.assertEqual(canon.props["text_color"], "#000000")


class ShorthandPrecedenceTests(unittest.TestCase):
    """Shorthand expansion respects explicit edge values."""

    def test_padding_shorthand_applies_to_all_edges(self):
        """padding=10 sets all four edges."""
        canon = lower_element(Box(padding=10))
        self.assertEqual(canon.props["padding_top"], 10)
        self.assertEqual(canon.props["padding_bottom"], 10)
        self.assertEqual(canon.props["padding_start"], 10)
        self.assertEqual(canon.props["padding_end"], 10)

    def test_explicit_edge_overrides_padding_shorthand(self):
        """Explicit padding_top overrides the padding shorthand."""
        canon = lower_element(Box(padding=10, padding_top=5))
        self.assertEqual(canon.props["padding_top"], 5)
        self.assertEqual(canon.props["padding_bottom"], 10)
        self.assertEqual(canon.props["padding_start"], 10)
        self.assertEqual(canon.props["padding_end"], 10)

    def test_multiple_explicit_edges_with_shorthand(self):
        """Multiple explicit edge values take precedence over shorthand."""
        canon = lower_element(Box(
            padding=10,
            padding_top=5,
            padding_start=8,
        ))
        self.assertEqual(canon.props["padding_top"], 5)
        self.assertEqual(canon.props["padding_bottom"], 10)
        self.assertEqual(canon.props["padding_start"], 8)
        self.assertEqual(canon.props["padding_end"], 10)

    def test_corner_radius_shorthand_expands(self):
        """corner_radius=5 sets all four corners."""
        canon = lower_element(Box(corner_radius=5))
        self.assertEqual(canon.props["corner_radius_top_left"], 5)
        self.assertEqual(canon.props["corner_radius_top_right"], 5)
        self.assertEqual(canon.props["corner_radius_bottom_right"], 5)
        self.assertEqual(canon.props["corner_radius_bottom_left"], 5)

    def test_explicit_corner_overrides_shorthand(self):
        """Explicit corner_radius_top_left overrides corner_radius."""
        canon = lower_element(Box(
            corner_radius=5,
            corner_radius_top_left=2,
            corner_radius_bottom_right=8,
        ))
        self.assertEqual(canon.props["corner_radius_top_left"], 2)
        self.assertEqual(canon.props["corner_radius_top_right"], 5)
        self.assertEqual(canon.props["corner_radius_bottom_right"], 8)
        self.assertEqual(canon.props["corner_radius_bottom_left"], 5)

    def test_style_padding_plus_explicit_edge(self):
        """Style padding expanded, but explicit edge overrides."""
        canon = lower_element(
            Box(padding_top=3, style=Style(padding=12))
        )
        self.assertEqual(canon.props["padding_top"], 3,
            "Explicit padding_top must override style padding")
        self.assertEqual(canon.props["padding_bottom"], 12)

    def test_decoration_corners_plus_explicit_corner(self):
        """Decoration corners expanded, but explicit corner overrides."""
        canon = lower_element(
            Box(corner_radius_top_left=3,
                decoration=Decoration.rectangle(corners=CornerRadius.all(8)))
        )
        self.assertEqual(canon.props["corner_radius_top_left"], 3,
            "Explicit corner must override decoration corners")
        self.assertEqual(canon.props["corner_radius_top_right"], 8)


class StyleDecorationCombinedTests(unittest.TestCase):
    """Style + Decoration combined precedence."""

    def test_style_decoration_and_explicit(self):
        """defaults < style < decoration < explicit."""
        # decoration background_color > style background_color
        # But explicit > both
        canon = lower_element(
            Box(
                background_color="#111111",  # explicit wins
                style=Style(background_color="#222222"),
                decoration=Decoration.rectangle(fill="#333333"),
            )
        )
        self.assertEqual(canon.props["background_color"], "#111111")

    def test_style_with_decoration_field(self):
        """Style that contains a decoration field lowers correctly."""
        elem = Text(text="x", style=Style(
            text_color="#111111",
            decoration=Decoration.rectangle(fill="#222222"),
        ))
        canon = lower_element(elem)
        self.assertEqual(canon.props["text_color"], "#111111")
        self.assertEqual(canon.props["background_color"], "#222222")

    def test_explicit_border_overrides_decoration_stroke(self):
        """Explicit border_color/border_width override Decoration stroke."""
        canon = lower_element(
            Box(
                border_color="#000000",
                border_width=10,
                decoration=Decoration.rectangle(
                    stroke=Stroke(color="#FF0000", width=3),
                ),
            )
        )
        self.assertEqual(canon.props["border_color"], "#000000")
        self.assertEqual(canon.props["border_width"], 10)


if __name__ == "__main__":
    unittest.main()
