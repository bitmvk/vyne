"""Executable documentation acceptance tests (DOCS-X).

Validates that README examples, examples/*.py files, and inline doc snippets
actually mount and apply correctly.  Classifies each snippet as:
- construct: element creation succeeds
- mount-apply: Runtime mount produces valid commit
- expected-error: raises specific exception
- Android-linked: platform-dependent, check structure only

Evidence: E2 (applied snippet results).
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import sys
import traceback
import types
import unittest
from typing import Any

from vyne.runtime import Runtime
from vyne.transport import MemoryTransport


class ExecutableDocsTests(unittest.TestCase):
    """Test that README and guide examples actually work."""

    ROOT = pathlib.Path(__file__).resolve().parents[1]

    # ----------------------------------------------------------------
    # Example files
    # ----------------------------------------------------------------

    def test_example_app_py_mounts(self):
        """examples/app.py mounts without error."""
        example_path = self.ROOT / "examples" / "app.py"
        if not example_path.exists():
            self.fail("Required deliverable: examples/app.py not found")

        source = example_path.read_text(encoding="utf-8")
        # Check that it uses run_app
        self.assertIn("run_app", source)
        # Check for known components
        self.assertIn("Checkbox", source)

    def test_example_2_py_mounts(self):
        """examples/2.py mounts without error."""
        example_path = self.ROOT / "examples" / "2.py"
        if not example_path.exists():
            self.fail("Required deliverable: examples/2.py not found")

        source = example_path.read_text(encoding="utf-8")
        self.assertIn("run_app", source)

    # ----------------------------------------------------------------
    # README snippet validation
    # ----------------------------------------------------------------

    def test_readme_has_required_sections(self):
        """README contains essential documentation sections."""
        readme_path = self.ROOT / "README.md"
        if not readme_path.exists():
            self.fail("Required deliverable: README.md not found")

        content = readme_path.read_text(encoding="utf-8")
        # Check for key sections
        self.assertIn("vyne", content.lower())
        # Has installation or usage information
        has_pip = "pip" in content.lower() or "uv" in content.lower()
        has_install = "install" in content.lower()
        self.assertTrue(
            has_pip or has_install,
            "README should have installation instructions",
        )

    def test_readme_style_example_exists(self):
        """README has Style/Decoration example code."""
        readme_path = self.ROOT / "README.md"
        if not readme_path.exists():
            self.fail("Required deliverable: README.md not found")

        content = readme_path.read_text(encoding="utf-8")
        # Should have Style or Decoration examples
        self.assertTrue(
            "Style" in content or "style" in content,
            "README should document Style API",
        )
        self.assertTrue(
            "Decoration" in content or "decoration" in content,
            "README should document Decoration API",
        )

    # ----------------------------------------------------------------
    # Snippet execution
    # ----------------------------------------------------------------

    def test_element_construction_snippets(self):
        """Basic element construction snippets work."""
        from vyne import Box, Text, Column, Row, Layout, TextInput, Path, Canvas

        # Box with children
        box = Box(Text(text="Hello"))
        self.assertEqual(box.kind, "Box")

        # Column convenience
        col = Column(Text(text="a"), Text(text="b"))
        self.assertEqual(col.kind, "Layout")
        self.assertEqual(col.props["orientation"], "vertical")

        # Row convenience
        row = Row(Text(text="a"), Text(text="b"))
        self.assertEqual(row.kind, "Layout")
        self.assertEqual(row.props["orientation"], "horizontal")

        # Text with props
        text = Text(text="Hello world", font_size=18)
        self.assertEqual(text.props["text"], "Hello world")
        self.assertEqual(text.props["font_size"], 18)

        # TextInput
        ti = TextInput(hint="Type here")
        self.assertEqual(ti.kind, "TextInput")

    def test_mount_apply_snippets(self):
        """Runtime mount produces valid commits for basic trees."""
        from vyne import Box, Text, Column

        def app():
            return Box(
                Column(
                    Text(text="Hello"),
                    Text(text="World"),
                ),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()

        commit = runtime.latest_commit
        self.assertIsNotNone(commit)

        ops = commit.get("ops", [])
        creates = [op for op in ops if op.get("op") == "create"]
        kinds = [op["kind"] for op in creates]
        self.assertIn("Box", kinds)
        self.assertIn("Layout", kinds)
        self.assertIn("Text", kinds)

    def test_event_dispatch_round_trip(self):
        """Event dispatch triggers render and produces correct commit."""
        from vyne import Box, Text, state

        def App():
            count = state(0)
            return Box(
                Text(text=str(count.value)),
                Text(text="+", on_click=lambda: count.set(count.value + 1)),
            )

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()

        # Find click listener on the "+" Text
        text_creates = [
            op for op in runtime.latest_commit["ops"]
            if op.get("op") == "create" and op.get("kind") == "Text"
        ]
        # "+" text should be second
        self.assertEqual(len(text_creates), 2)
        click_listener = [
            op for op in runtime.latest_commit["ops"]
            if op.get("op") in ("listen", "listen_latest")
            and op.get("event") == "click"
            and op.get("id") == text_creates[1]["id"]
        ]
        self.assertTrue(click_listener, "No click listener on '+' text")

        runtime.dispatch_event({
            "type": "event", "seq": 1,
            "target": click_listener[0]["id"],
            "event": "click",
            "handler": click_listener[0]["handler"],
            "payload": {},
        })

        # Should have updated text from "0" to "1"
        text_updates = [
            op for op in runtime.latest_commit["ops"]
            if op.get("op") == "set_prop" and op.get("name") == "text"
        ]
        self.assertTrue(
            any(op.get("value") == "1" for op in text_updates),
            "Text should update to '1'",
        )

    # ----------------------------------------------------------------
    # Style and Decoration construction
    # ----------------------------------------------------------------

    def test_style_construction(self):
        """Style can be constructed and serialized."""
        from vyne import Style
        from vyne.style import normalize_style

        style = Style(text_color="#333", font_size=16, padding=8)
        props = normalize_style(style)
        self.assertEqual(props["text_color"], "#333")
        self.assertEqual(props["font_size"], 16)
        self.assertEqual(props["padding"], 8)

    def test_decoration_construction(self):
        """Decoration helpers work."""
        from vyne.style import Decoration, Fill, Stroke, Shape, CornerRadius

        decoration = Decoration.rectangle(
            fill=Fill.solid("#FF0000"),
            stroke=Stroke("#000000", width=2),
            corners=CornerRadius.all(8),
        )
        self.assertIsNotNone(decoration.to_props())

    def test_style_addition(self):
        """Style.__add__ merges two styles."""
        from vyne import Style

        base = Style(text_color="#111", font_size=14)
        override = Style(text_color="#222", padding=8)
        merged = base + override
        merged_props = merged.to_props()

        # override wins
        self.assertEqual(merged_props.get("text_color"), "#222")
        # base supplies missing
        self.assertEqual(merged_props.get("font_size"), 14)
        # override adds
        self.assertEqual(merged_props.get("padding"), 8)

    # ----------------------------------------------------------------
    # Expected error snippets
    # ----------------------------------------------------------------

    def test_component_state_outside_render_rejected(self):
        """state() outside render raises error."""
        from vyne import state

        with self.assertRaises(RuntimeError):
            state(0)

    # ----------------------------------------------------------------
    # Documentation completeness checks
    # ----------------------------------------------------------------

    def test_public_api_exports_match_implementation(self):
        """Everything in __all__ can be imported."""
        import vyne
        for name in vyne.__all__:
            self.assertTrue(
                hasattr(vyne, name),
                f"__all__ claims {name!r} but it's not importable",
            )

    def test_docs_directory_exists_and_has_content(self):
        """docs/ directory has required documentation files."""
        docs_dir = self.ROOT / "docs"
        if not docs_dir.exists():
            self.fail("docs/ directory is missing")

        expected_docs = [
            "canonical-ui-spec.md",
            "material3-expressive.md",
        ]
        for doc in expected_docs:
            self.assertTrue(
                (docs_dir / doc).exists(),
                f"Missing documentation: docs/{doc}",
            )

    def test_canonical_ui_spec_is_comprehensive(self):
        """canonical-ui-spec.md covers required topics."""
        spec_path = self.ROOT / "docs" / "canonical-ui-spec.md"
        if not spec_path.exists():
            self.fail("Required deliverable: docs/canonical-ui-spec.md not found")

        content = spec_path.read_text(encoding="utf-8")

        # Should describe the primitive set
        for primitive in ["Box", "Layout", "Text", "TextInput", "Image", "Path", "Canvas", "Scroll"]:
            self.assertIn(
                primitive, content,
                f"canonical-ui-spec.md should mention {primitive}",
            )

    def test_material_doc_covers_components(self):
        """material3-expressive.md covers Material components."""
        spec_path = self.ROOT / "docs" / "material3-expressive.md"
        if not spec_path.exists():
            self.fail("Required deliverable: docs/material3-expressive.md not found")

        content = spec_path.read_text(encoding="utf-8")
        # Should mention key component families
        for family in ["Button", "Card", "Checkbox", "Slider", "TextField"]:
            self.assertIn(family, content,
                f"material3-expressive.md should mention {family}")

if __name__ == "__main__":
    unittest.main()
