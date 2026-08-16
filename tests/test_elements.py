from __future__ import annotations

import unittest

from vyne import (
    Box,
    Canvas,
    CornerRadius,
    Decoration,
    Fill,
    Path,
    Scroll,
    Stroke,
    Text,
)
from vyne.elements import event_name_for_prop, normalize_child


class ElementTests(unittest.TestCase):
    def test_nested_children_and_scalars_are_normalized(self):
        element = Box("hello", [None, 2, (True, Text(text="nested"))])

        self.assertEqual([child.kind for child in element.children], [
            "Text",
            "Text",
            "Text",
            "Text",
        ])
        self.assertEqual(
            [child.props.get("text") for child in element.children],
            ["hello", "2", "True", "nested"],
        )

    def test_normalize_child_rejects_arbitrary_objects(self):
        with self.assertRaisesRegex(TypeError, "Cannot render child"):
            normalize_child(object())

    def test_scroll_only_wraps_multiple_children(self):
        single = Scroll(Text(text="one"))
        multiple = Scroll(Text(text="one"), Text(text="two"))

        self.assertEqual([child.kind for child in single.children], ["Text"])
        self.assertEqual([child.kind for child in multiple.children], ["Layout"])
        self.assertEqual(
            [child.props["text"] for child in multiple.children[0].children],
            ["one", "two"],
        )
        self.assertEqual(single.props["overflow"], "hidden")

    def test_scroll_allows_explicit_visible_overflow(self):
        element = Scroll(Text(text="one"), overflow="visible")

        self.assertEqual(element.props["overflow"], "visible")

    def test_path_and_canvas_lower_path_strings(self):
        path = Path(d="M0 0 L1 2")
        canvas = Canvas(draw=[{"kind": "path", "d": "M0 0 L3 4"}])

        self.assertNotIn("d", path.props)
        # After deep freeze (MODEL-03), path commands are FrozenMaps with tuple values.
        last_cmd = path.props["commands"][-1]
        self.assertEqual(dict(last_cmd), {"cmd": "L", "values": (1.0, 2.0)})
        self.assertNotIn("d", canvas.props["draw"][0])
        self.assertEqual(canvas.props["draw"][0]["commands"][0]["cmd"], "M")

    def test_canvas_validates_display_list_shape(self):
        with self.assertRaisesRegex(TypeError, "draw must be a list"):
            Canvas(draw={})
        with self.assertRaisesRegex(TypeError, "operations must be dictionaries"):
            Canvas(draw=["not an operation"])

    def test_event_props_map_to_protocol_event_names(self):
        self.assertEqual(event_name_for_prop("on_click"), "click")
        self.assertEqual(event_name_for_prop("on_pointer_down"), "pointer_down")
        self.assertEqual(event_name_for_prop("on_pointer_move"), "pointer_move")
        self.assertEqual(event_name_for_prop("on_pointer_up"), "pointer_up")
        self.assertEqual(event_name_for_prop("on_pointer_cancel"), "pointer_cancel")
        self.assertEqual(event_name_for_prop("on_text_change"), "text_change")
        self.assertIsNone(event_name_for_prop("text"))

    def test_decoration_helpers_build_expected_shapes(self):
        decoration = Decoration.rectangle(
            fill=Fill.solid("#abcdef"),
            stroke=Stroke("#123456", width=2),
            corners=CornerRadius.only(top_left=8, bottom_right=2),
        )

        props = decoration.to_props()
        self.assertEqual(props["shape"]["kind"], "rectangle")
        self.assertEqual(props["shape"]["fill"], {"kind": "solid", "color": "#abcdef"})
        self.assertEqual(props["shape"]["stroke"], {"color": "#123456", "width": 2})
        self.assertEqual(props["shape"]["corners"]["top_left"], 8)


if __name__ == "__main__":
    unittest.main()
