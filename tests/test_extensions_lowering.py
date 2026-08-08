"""Extension kind lowering tests (EXT-02).

Extension kinds flow through the exact same lowering pipeline as core
kinds: kind gate, prop validation, event-handler splitting, generic
defaults, and animated-value rejection.
"""

from __future__ import annotations

import unittest

from vyne.animations import AnimatedValue
from vyne.elements import Element
from vyne.extensions_registry import sync_from_host
from vyne.lowering import lower_element

KINDS = {
    "TimerRing": (["progress", "ring_color"], ["complete"], [False]),
}


def setUpModule() -> None:
    sync_from_host(KINDS)


def tearDownModule() -> None:
    sync_from_host({})


def _ring(**props) -> Element:
    return Element("TimerRing", props=props)


class ExtensionLoweringTests(unittest.TestCase):
    def test_extension_kind_lowers(self):
        node = lower_element(_ring(progress=0.5))
        self.assertEqual(node.kind, "TimerRing")
        self.assertEqual(node.props["progress"], 0.5)

    def test_generic_props_accepted_on_extension_kind(self):
        node = lower_element(_ring(width=100, background_color="#FF0000", opacity=0.5))
        self.assertEqual(node.props["width"], 100)
        self.assertEqual(node.props["background_color"], "#FF0000")

    def test_unknown_prop_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported prop 'nope' for TimerRing"):
            lower_element(_ring(nope=1))

    def test_unknown_kind_rejected_with_hint(self):
        with self.assertRaisesRegex(ValueError, "Unknown primitive kind: 'Gadget'"):
            lower_element(Element("Gadget", props={}))

    def test_extension_event_handler_prop_accepted_and_split(self):
        handler = lambda event: None  # noqa: E731
        node = lower_element(_ring(progress=0.5, on_complete=handler))
        # Event handler props stay in props (for intent binding) but are
        # excluded from the native projection.
        self.assertIn("on_complete", node.props)
        self.assertNotIn("on_complete", node.native_props)
        self.assertIn("progress", node.native_props)

    def test_extension_event_handler_prop_rejected_on_core_kind(self):
        handler = lambda event: None  # noqa: E731
        with self.assertRaisesRegex(ValueError, "Unsupported prop 'on_complete' for Text"):
            lower_element(Element("Text", props={"text": "x", "on_complete": handler}))

    def test_extension_event_handler_requires_callable(self):
        with self.assertRaisesRegex(TypeError, "must be callable"):
            lower_element(_ring(on_complete="not-a-callable"))

    def test_animated_value_rejected_on_extension_prop(self):
        with self.assertRaisesRegex(ValueError, "animatable"):
            lower_element(_ring(progress=AnimatedValue(0.5)))

    def test_animated_value_accepted_on_generic_prop_of_extension_kind(self):
        # Generic core props (width, opacity, ...) are animatable on every
        # kind — the animation machinery is name-driven. Only extension-
        # specific props are non-animatable in v1.
        node = lower_element(_ring(width=AnimatedValue(100.0)))
        self.assertEqual(node.kind, "TimerRing")
        self.assertIn("width", node.props)

    def test_defaults_materialized_for_generic_props(self):
        node = lower_element(_ring(progress=0.5))
        self.assertIn("opacity", node.props)  # core generic default exists

    def test_leaf_extension_kind_rejects_children(self):
        # TimerRing is a leaf (container=False in the synced contract): its
        # native view is not a ViewGroup, so children must be rejected.
        with self.assertRaisesRegex(ValueError, "allows at most 0 children"):
            lower_element(Element(
                "TimerRing",
                props={},
                children=(Element("Text", props={"text": "hi"}),),
            ))

    def test_container_extension_kind_accepts_children(self):
        sync_from_host({
            "Panel": (["title"], [], [True]),
            "Leaf": (["v"], [], [False]),
        })
        try:
            node = lower_element(Element(
                "Panel",
                props={},
                children=(Element("Text", props={"text": "x"}),),
            ))
            self.assertEqual(1, len(node.children))
        finally:
            sync_from_host(KINDS)

    def test_extension_kind_is_allowed_inside_core_containers(self):
        # Core containers list exactly the core kinds they accept; extension
        # kinds are always accepted as children (the native ViewGroup accepts
        # any View child).
        node = lower_element(Element(
            "Layout",
            props={"orientation": "vertical"},
            children=(_ring(progress=0.5),),
        ))
        self.assertEqual("TimerRing", node.children[0].kind)
        box = lower_element(Element(
            "Box",
            props={},
            children=(_ring(progress=1.0),),
        ))
        self.assertEqual("TimerRing", box.children[0].kind)


if __name__ == "__main__":
    unittest.main()
