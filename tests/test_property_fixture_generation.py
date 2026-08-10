"""Generated property fixture tests (NATIVE-06: NA-1, NA-2).

Generates a default commit for every primitive kind and verifies:
- Every generated fixture contains only contracted props
- No Text has Layout-only props (align_items, justify_content)
- TextInput preserves its editable/focus baseline
- Dimensions are wire-compatible
- Colors are in canonical wire format

Evidence level: E1 (Python generation, verified against contracts).
"""

from __future__ import annotations

import unittest
from typing import Any

from vyne import (
    Box, Canvas, Column, Image, Layout, Path, Row, Scroll,
    Text, TextInput,
)
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport
from vyne.spec.schema_v2 import PROPS_BY_KIND


def _collect_props(ops: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Collect all props per node from commit ops."""
    node_props: dict[int, dict[str, Any]] = {}
    for op in ops:
        if op.get("op") == "set_props":
            node_props.setdefault(op["id"], {}).update(op.get("props", {}))
        elif op.get("op") == "set_prop":
            node_props.setdefault(op["id"], {})[op["name"]] = op.get("value")
        elif op.get("op") == "remove_prop":
            node_props.setdefault(op["id"], {}).pop(op.get("name"), None)
    return node_props


def _create_ids(ops: list[dict[str, Any]]) -> dict[int, str]:
    """Map node id → kind from create ops."""
    return {
        op["id"]: op["kind"]
        for op in ops
        if op.get("op") == "create"
    }


class GeneratedKindFixtureTests(unittest.TestCase):
    """Generated default fixture for every primitive kind."""

    def _assert_fixture_for(self, element, expected_kind: str):
        """Mount an element and verify its generated commit."""
        def App():
            return element

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        commit = runtime.latest_commit
        ops = commit.get("ops", [])

        # Verify revision
        self.assertIn("revision", commit)
        self.assertGreater(commit["revision"], 0)

        # Find created nodes and their props
        ids_to_kinds = _create_ids(ops)
        node_props = _collect_props(ops)

        # Verify at least one node of expected kind was created
        created_kinds = set(ids_to_kinds.values())
        self.assertIn(expected_kind, created_kinds,
                      f"No {expected_kind} node created; got: {created_kinds}")

        # Check each node's props against the contract
        for node_id, props in node_props.items():
            kind = ids_to_kinds.get(node_id, "Box")
            allowed = PROPS_BY_KIND.get(kind, set())

            for prop_name in props:
                self.assertIn(prop_name, allowed,
                              f"Prop '{prop_name}' on {kind} node {node_id} "
                              f"is not in PROPS_BY_KIND[{kind}]")

            # Verify dimensions are wire-compatible (string or number, not None)
            for dim in ("width", "height"):
                if dim in props:
                    val = props[dim]
                    self.assertIsNotNone(val,
                                         f"{dim} on {kind} node {node_id} is None")
                    self.assertTrue(
                        isinstance(val, (str, int, float)),
                        f"{dim} on {kind} is {type(val).__name__}, "
                        f"expected str/int/float: {val!r}"
                    )

    def test_default_fixture_per_kind(self):
        cases = [
            ("box", Box(), "Box"),
            ("layout", Layout(), "Layout"),
            ("scroll", Scroll(), "Scroll"),
            ("text", Text(text="hello"), "Text"),
            ("textinput", TextInput(text="edit me"), "TextInput"),
            ("image", Image(source="icon.png"), "Image"),
            ("path", Path(d="M10 10 L100 100"), "Path"),
            ("canvas", Canvas(draw=[
                {"kind": "rect", "x": 0, "y": 0, "width": 50, "height": 50}
            ]), "Canvas"),
        ]
        for label, element, expected_kind in cases:
            with self.subTest(kind=label):
                self._assert_fixture_for(element, expected_kind)


class TextNoContainerPropsTests(unittest.TestCase):
    """Text must not receive Layout-only container props."""

    CONTAINER_ONLY = {"align_items", "justify_content", "overflow"}

    def test_text_has_no_container_props(self):
        """Text default fixture must not include align_items or justify_content."""
        def App():
            return Column(Text(text="hello"))

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        ops = runtime.latest_commit.get("ops", [])
        node_props = _collect_props(ops)
        ids_to_kinds = _create_ids(ops)

        for node_id, props in node_props.items():
            kind = ids_to_kinds.get(node_id, "Box")
            if kind == "Text":
                for container_prop in self.CONTAINER_ONLY:
                    self.assertNotIn(
                        container_prop, props,
                        f"Text node {node_id} has container prop '{container_prop}' "
                        f"but Text is a leaf kind"
                    )

    def test_text_no_max_dimensions(self):
        """Text should not have max_width/max_height (container only)."""
        def App():
            return Text(text="hello")

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        ops = runtime.latest_commit.get("ops", [])
        node_props = _collect_props(ops)
        ids_to_kinds = _create_ids(ops)

        for node_id, props in node_props.items():
            kind = ids_to_kinds.get(node_id, "Box")
            if kind == "Text":
                self.assertNotIn("max_width", props)
                self.assertNotIn("max_height", props)


class TextInputEditableBaselineTests(unittest.TestCase):
    """TextInput must preserve its editable, focusable baseline."""

    def _textinput_props(self, **kwargs) -> dict:
        def App():
            return TextInput(text="input", **kwargs)

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()
        ops = runtime.latest_commit.get("ops", [])
        ids_to_kinds = _create_ids(ops)
        node_props = _collect_props(ops)
        for node_id, props in node_props.items():
            if ids_to_kinds.get(node_id) == "TextInput":
                return props
        return {}

    def test_textinput_focusable_baseline(self):
        """The default fixture omits focusable (drop_default=True); an explicit
        focusable=True is sent."""
        default_props = self._textinput_props()
        self.assertNotIn(
            "focusable", default_props,
            "TextInput default fixture must not send focusable=False "
            "(drop_default=True should suppress it)",
        )

        explicit_props = self._textinput_props(focusable=True)
        self.assertIn(
            "focusable", explicit_props,
            "explicit focusable=True must be sent (drop_default must not suppress it)",
        )
        self.assertTrue(
            explicit_props["focusable"],
            f"TextInput with focusable=True sent {explicit_props['focusable']!r}",
        )


class DimensionWireCompatibilityTests(unittest.TestCase):
    """Dimensions must be wire-compatible strings or numbers."""

    def test_explicit_dimensions_over_defaults(self):
        """Explicit width=100 should override default wrap_content."""
        def App():
            return Box(width=100, height=200)

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        ops = runtime.latest_commit.get("ops", [])
        node_props = _collect_props(ops)

        for node_id, props in node_props.items():
            if props.get("width") == 100:
                # Found the Box with explicit dimensions; height should also be explicit
                self.assertEqual(props.get("height"), 200)
                return

        self.fail("No node with width=100 found")


class ColorWireFormatTests(unittest.TestCase):
    """Colors must be canonical wire format strings (not bare ints, not ARGB)."""

    def test_colors_are_hash_strings(self):
        """background_color etc. must be #RRGGBB or #RRGGBBAA strings."""
        def App():
            return Box(background_color="#ff0000",
                       border_color="#00ff00ff",
                       ripple_color="#40000000")

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        ops = runtime.latest_commit.get("ops", [])
        node_props = _collect_props(ops)

        for node_id, props in node_props.items():
            for color_prop in ("background_color", "border_color", "ripple_color"):
                if color_prop in props:
                    val = props[color_prop]
                    self.assertIsInstance(val, str,
                                          f"{color_prop} should be str, got {type(val).__name__}")
                    self.assertTrue(val.startswith("#"),
                                    f"{color_prop} should start with #, got {val!r}")


if __name__ == "__main__":
    unittest.main()
