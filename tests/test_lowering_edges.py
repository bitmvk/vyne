"""Caveat tests for the lowering pipeline (Style/Decoration → flat props).

Covers alias conflicts, shorthand rejection, the supported-tier contract
for Style/Decoration, dash-array normalization, view_box validation, and
child-shape limits — the places where user input must fail fast.
"""

from __future__ import annotations

import math
import unittest

from vyne import (
    Box,
    Canvas,
    Column,
    Path,
    Scroll,
    Text,
)
from vyne.lowering import lower_element
from vyne.style import (
    CornerRadius,
    Decoration,
    Fill,
    Ripple,
    Shadow,
    Shape,
    Stroke,
    Style,
)


def _lower(element):
    return lower_element(element)


class AliasConflictTests(unittest.TestCase):
    def test_alpha_overrides_default_opacity(self):
        canonical = _lower(Text(text="x", alpha=0.5))
        self.assertEqual(canonical.props["opacity"], 0.5)

    def test_alpha_matching_explicit_opacity_is_fine(self):
        canonical = _lower(Text(text="x", alpha=0.5, opacity=0.5))
        self.assertEqual(canonical.props["opacity"], 0.5)

    def test_conflicting_alpha_and_opacity_rejected(self):
        with self.assertRaisesRegex(ValueError, "Conflicting alpha"):
            _lower(Text(text="x", alpha=0.5, opacity=0.8))

    def test_accessibility_state_aliases_canonicalize(self):
        canonical = _lower(Text(text="x", accessibility_state_checked=True))
        self.assertIn("accessibility_checked", canonical.props)
        self.assertNotIn("accessibility_state_checked", canonical.props)

    def test_accessibility_canonical_wins_over_alias(self):
        canonical = _lower(Text(
            text="x",
            accessibility_state_checked=False,
            accessibility_checked=True,
        ))
        self.assertIs(canonical.props["accessibility_checked"], True)


class ShorthandTests(unittest.TestCase):
    def test_size_shorthand_rejected(self):
        with self.assertRaisesRegex(ValueError, "'size' shorthand"):
            _lower(Box(size=24))

    def test_padding_shorthand_expands_all_edges(self):
        canonical = _lower(Box(padding=8))
        for edge in ("padding_top", "padding_bottom",
                     "padding_start", "padding_end"):
            self.assertEqual(canonical.props[edge], 8)

    def test_explicit_padding_edge_beats_shorthand(self):
        canonical = _lower(Box(padding=8, padding_top=2))
        self.assertEqual(canonical.props["padding_top"], 2)
        self.assertEqual(canonical.props["padding_bottom"], 8)

    def test_negative_padding_rejected(self):
        with self.assertRaises(ValueError):
            _lower(Box(padding=-1))

    def test_corner_radius_shorthand_expands(self):
        canonical = _lower(Box(corner_radius=4))
        for corner in ("corner_radius_top_left", "corner_radius_top_right",
                       "corner_radius_bottom_right", "corner_radius_bottom_left"):
            self.assertEqual(canonical.props[corner], 4)

    def test_negative_corner_radius_rejected(self):
        with self.assertRaises(ValueError):
            _lower(Box(corner_radius=-2))


class StyleLoweringTests(unittest.TestCase):
    def test_explicit_prop_beats_style(self):
        canonical = _lower(Text(
            text="x",
            style=Style(text_color="#111111"),
            text_color="#222222",
        ))
        self.assertEqual(canonical.props["text_color"], "#222222")

    def test_style_color_alias_maps_to_text_color(self):
        canonical = _lower(Text(text="x", style=Style(color="#333333")))
        self.assertEqual(canonical.props["text_color"], "#333333")

    def test_unsupported_style_fields_rejected(self):
        for field in ("gap", "size", "flex", "flex_grow", "align_self"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "not yet supported"):
                    _lower(Box(style=Style(**{field: 1 if field != "align_self" else "center"})))

    def test_unknown_style_field_rejected_with_path(self):
        with self.assertRaisesRegex(ValueError, "Unknown Style field 'bogus'"):
            _lower(Box(style={"bogus": 1}))

    def test_style_merging_add_operator(self):
        base = Style(text_color="#111111", font_size=14)
        override = Style(font_size=18)
        merged = base + override
        self.assertEqual(merged.text_color, "#111111")
        self.assertEqual(merged.font_size, 18)
        # Non-Style operands are not merged (standard NotImplemented protocol).
        with self.assertRaises(TypeError):
            Style() + None  # type: ignore[operator]


class DecorationLoweringTests(unittest.TestCase):
    def test_unknown_decoration_field_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown Decoration field"):
            _lower(Box(decoration={"mystery": 1}))

    def test_clip_rejected(self):
        with self.assertRaisesRegex(ValueError, "clip"):
            _lower(Box(decoration=Decoration.rectangle(clip=True)))

    def test_gradient_fills_rejected(self):
        for fill in (
            Fill.linear_gradient(start_color="#000000", end_color="#ffffff"),
            Fill.radial_gradient(center_color="#000000", end_color="#ffffff", radius=4),
            Fill.sweep_gradient(start_color="#000000", end_color="#ffffff"),
        ):
            with self.subTest(kind=fill.kind):
                with self.assertRaisesRegex(ValueError, "not yet supported"):
                    _lower(Box(decoration=Decoration.rectangle(fill=fill)))

    def test_dashed_stroke_rejected(self):
        with self.assertRaisesRegex(ValueError, "Dashed"):
            _lower(Box(decoration=Decoration.rectangle(
                stroke=Stroke(color="#000000", width=1, dash_width=2, dash_gap=2),
            )))

    def test_non_rectangle_shape_rejected(self):
        with self.assertRaisesRegex(ValueError, "rectangle"):
            _lower(Box(decoration=Decoration(
                shape=Shape.oval(fill="#ff0000"),
            )))

    def test_shadow_translation_z_rejected(self):
        with self.assertRaisesRegex(ValueError, "translation_z"):
            _lower(Box(decoration=Decoration.rectangle(
                shadow=Shadow(elevation=2, translation_z=1),
            )))

    def test_unbounded_ripple_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unbounded ripple"):
            _lower(Box(decoration=Decoration.rectangle(
                ripple=Ripple(color="#ffffff", bounded=False),
            )))

    def test_supported_decoration_tier_lowers(self):
        canonical = _lower(Box(
            decoration=Decoration.rectangle(
                fill="#101010",
                stroke=Stroke(color="#202020", width=2),
                corners=CornerRadius.only(top_left=3),
                shadow=Shadow(elevation=4),
                ripple=Ripple(color="#eeeeee"),
            ),
        ))
        self.assertEqual(canonical.props["background_color"], "#101010")
        self.assertEqual(canonical.props["border_color"], "#202020")
        self.assertEqual(canonical.props["border_width"], 2)
        self.assertEqual(canonical.props["corner_radius_top_left"], 3)
        self.assertEqual(canonical.props["elevation"], 4)
        self.assertEqual(canonical.props["ripple_color"], "#eeeeee")
        # No opaque style/decoration blobs cross the wire.
        self.assertNotIn("style", canonical.props)
        self.assertNotIn("decoration", canonical.props)

    def test_explicit_prop_beats_decoration(self):
        canonical = _lower(Box(
            decoration=Decoration.rectangle(fill="#101010"),
            background_color="#999999",
        ))
        self.assertEqual(canonical.props["background_color"], "#999999")


class DashArrayTests(unittest.TestCase):
    def _path(self, dash):
        return Path(d="M 0 0 L 10 10", stroke_dash_array=dash)

    def test_string_form_parsed_to_tuple(self):
        canonical = _lower(self._path("4,8"))
        self.assertEqual(canonical.props["stroke_dash_array"], (4.0, 8.0))

    def test_full_marker_preserved(self):
        canonical = _lower(self._path("full"))
        self.assertEqual(canonical.props["stroke_dash_array"], "full")

    def test_empty_string_removed(self):
        canonical = _lower(self._path("  "))
        self.assertNotIn("stroke_dash_array", canonical.props)

    def test_list_converted_to_tuple(self):
        canonical = _lower(self._path([2, 4]))
        self.assertEqual(canonical.props["stroke_dash_array"], (2, 4))

    def test_odd_count_rejected(self):
        with self.assertRaisesRegex(ValueError, "even"):
            _lower(self._path("4,8,2"))

    def test_non_positive_rejected(self):
        with self.assertRaises(ValueError):
            _lower(self._path("4,0"))
        with self.assertRaises(ValueError):
            _lower(self._path([4, -2]))

    def test_non_numeric_rejected(self):
        with self.assertRaisesRegex(ValueError, "comma-separated"):
            _lower(self._path("fast,slow"))


class ViewBoxTests(unittest.TestCase):
    def test_valid_view_box(self):
        canonical = _lower(Canvas(draw=[], view_box=[0, 0, 100, 50]))
        self.assertEqual(tuple(canonical.props["view_box"]), (0, 0, 100, 50))

    def test_wrong_arity_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least 4"):
            _lower(Canvas(draw=[], view_box=[0, 0, 100]))
        with self.assertRaisesRegex(ValueError, "at most 4"):
            _lower(Canvas(draw=[], view_box=[0, 0, 100, 50, 25]))

    def test_non_finite_rejected(self):
        with self.assertRaisesRegex(TypeError, "native bridge"):
            Canvas(draw=[], view_box=[0, 0, math.inf, 50])

    def test_non_positive_size_rejected(self):
        with self.assertRaisesRegex(ValueError, "width must be positive"):
            _lower(Canvas(draw=[], view_box=[0, 0, 0, 50]))
        with self.assertRaisesRegex(ValueError, "height must be positive"):
            _lower(Canvas(draw=[], view_box=[0, 0, 100, -1]))


class ChildShapeTests(unittest.TestCase):
    def test_scroll_wraps_multiple_children_in_column(self):
        """The public Scroll auto-wraps; raw Scroll elements still enforce."""
        canonical = _lower(Scroll(Text(text="a"), Text(text="b")))
        self.assertEqual(canonical.kind, "Scroll")
        self.assertEqual(len(canonical.children), 1)
        self.assertEqual(canonical.children[0].kind, "Layout")

    def test_scroll_with_two_raw_children_rejected(self):
        from vyne.elements import Element
        raw = Element(
            kind="Scroll", props={},
            children=(
                Element(kind="Text", props={"text": "a"}, children=()),
                Element(kind="Text", props={"text": "b"}, children=()),
            ),
        )
        with self.assertRaisesRegex(ValueError, "at most 1"):
            _lower(raw)

    def test_leaf_kinds_reject_children(self):
        with self.assertRaisesRegex(ValueError, "at most 0"):
            _lower(Text(text="x", children=[Text(text="y")]) if False else
                   _widget_with_child())

    def test_unknown_kind_rejected(self):
        from vyne.elements import Element
        bogus = Element(kind="Window", props={}, children=())
        with self.assertRaisesRegex(ValueError, "Unknown primitive kind"):
            _lower(bogus)

    def test_removed_view_kind_rejected(self):
        """The legacy View kind is no longer a wire primitive."""
        from vyne.elements import Element
        legacy = Element(kind="View", props={}, children=())
        with self.assertRaisesRegex(ValueError, "Unknown primitive kind"):
            _lower(legacy)


def _widget_with_child():
    from vyne.elements import Element
    return Element(
        kind="Text", props={"text": "x"},
        children=(Element(kind="Text", props={"text": "y"}, children=()),),
    )


class ResolveNativePropsTests(unittest.TestCase):
    def test_defaults_materialized_and_aliases_resolved(self):
        canonical = _lower(Text(text="x", alpha=0.5))
        native = canonical.props
        self.assertEqual(native["opacity"], 0.5)
        self.assertIn("text", native)

    def test_no_compat_props_leak(self):
        canonical = _lower(Box(style=Style(background_color="#111111")))
        native = canonical.props
        for leaked in ("style", "decoration", "color", "gap", "size", "flex"):
            self.assertNotIn(leaked, native)


class CompositeLoweringTests(unittest.TestCase):
    def test_row_and_column_lower_to_layout(self):
        row = _lower(Column(Text(text="a")))
        self.assertEqual(row.kind, "Layout")
        self.assertEqual(row.props["orientation"], "vertical")

    def test_key_not_in_wire_props(self):
        canonical = _lower(Text(text="x", key="abc"))
        self.assertNotIn("key", canonical.props)
        self.assertEqual(canonical.key, "abc")

    def test_ref_passes_through_unvalidated(self):
        from vyne.refs import Ref
        ref = Ref()
        canonical = _lower(Box(ref=ref))
        self.assertIs(canonical.props["ref"], ref)


if __name__ == "__main__":
    unittest.main()
