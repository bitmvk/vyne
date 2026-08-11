"""Generated typing-stub tests (SCHEMA-STUBS-01).

Verifies that ``vyne/elements.pyi`` and ``vyne/py.typed`` are regenerated
from ``vyne.spec.schema_v2``, the value-domain -> Python type mapping
(including nullable), the schema-derived public surface, fail-loud
generation, and a real mypy positive/negative smoke.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from vyne.spec.model import ValueSpec
from vyne.spec.schema_v2 import ALL_PROPS, EVENT_SPECS, PRIMITIVE_KINDS, PROPS_BY_KIND

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "scripts" / "generate_schema_stubs.py"
STUB = REPO_ROOT / "packages" / "vyne" / "src" / "vyne" / "elements.pyi"
PYTYPED = REPO_ROOT / "packages" / "vyne" / "src" / "vyne" / "py.typed"

INTERNAL_EVENTS = frozenset(n for n, s in EVENT_SPECS.items() if not s.public_callback)
# Constructor-surface props that are not schema props: fixed Python-only props
# plus the shorthand/alias props resolved at lowering time.
SHARED_PYTHON_ONLY = frozenset(
    {"key", "style", "decoration", "ref", "alpha", "padding", "corner_radius",
     "accessibility_state_checked", "accessibility_state_selected"}
)
PYTHON_ONLY_TYPES = {
    "key": "ElementKey", "style": "Style | dict[str, Any]",
    "decoration": "Decoration | dict[str, Any]", "ref": "Ref",
    "alpha": "AnimatableNumber", "padding": "int | float",
    "corner_radius": "int | float", "accessibility_state_checked": "bool",
    "accessibility_state_selected": "bool",
}
CONTAINER_KINDS_SET = frozenset({"Box", "Layout", "Scroll", "HorizontalScroll"})

def _load_generator():
    spec = importlib.util.spec_from_file_location("vyne_generate_schema_stubs", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

gen = _load_generator()


class GeneratorDriftTests(unittest.TestCase):
    """The checked-in stub equals fresh generator output."""

    def test_stub_is_up_to_date(self):
        content = gen.generate()
        self.assertTrue(STUB.is_file(), "elements.pyi is missing")
        self.assertEqual(
            STUB.read_text(encoding="utf-8"), content,
            "drifted; run uv run python scripts/generate_schema_stubs.py",
        )
        import ast

        ast.parse(content)
        self.assertTrue(PYTYPED.is_file(), "vyne/py.typed is missing")

    def test_cli_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "elements.pyi"
            content = gen.generate()
            self._run("--output", str(output))
            self.assertEqual(output.read_text(encoding="utf-8"), content)
            self.assertTrue((output.parent / "py.typed").is_file())
            clean = self._run("--check", "--output", str(output))
            self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
            output.write_text(content + "\n# drift\n", encoding="utf-8")
            drift = self._run("--check", "--output", str(output))
            self.assertEqual(drift.returncode, 1, drift.stdout + drift.stderr)
            self.assertIn("DIFF", drift.stdout)
            self.assertEqual(STUB.read_text(encoding="utf-8"), content)

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(GENERATOR), *args], capture_output=True, text=True
        )


class ValueTypeMappingTests(unittest.TestCase):
    """The explicit schema-domain -> typing mapping, including nullable."""

    def test_domain_table(self):
        cases = [
            (ValueSpec(type_name="str", enum=frozenset({"horizontal", "vertical"})), "Literal['horizontal', 'vertical']"),
            (ValueSpec(type_name="str", enum=frozenset({"horizontal", "vertical"}), nullable=True), "Literal['horizontal', 'vertical'] | None"),
            (ValueSpec(exact_types=(str, int, float), dimension=True), "str | int | float"),
            (ValueSpec(exact_types=(str, int, float), dimension=True, nullable=True), "str | int | float | None"),
            (ValueSpec(dash_array=True), "tuple[int | float, ...] | str"),
            (ValueSpec(dash_array=True, nullable=True), "tuple[int | float, ...] | str | None"),
            (ValueSpec(string_map=True, nullable=True), "FrozenMap[str, Any] | None"),
            (ValueSpec(finite=True), "int | float"),
            (ValueSpec(finite=True, non_negative=True, min_value=0.0, max_value=1.0), "int | float"),
            (ValueSpec(finite=True, nullable=True), "int | float | None"),
            (ValueSpec(exact_types=(list, tuple), item_spec=ValueSpec(finite=True), min_items=4, max_items=4, nullable=True), "list[int | float] | tuple[int | float, ...] | None"),
            (ValueSpec(exact_types=(list, tuple)), "list[Any] | tuple[Any, ...]"),
            (ValueSpec(exact_types=(list,)), "list[Any]"),
            (ValueSpec(exact_types=(tuple,)), "tuple[Any, ...]"),
            (ValueSpec(type_name="bool"), "bool"),
            (ValueSpec(type_name="str", nullable=True), "str | None"),
        ]
        for index, (spec, expected) in enumerate(cases):
            with self.subTest(index=index):
                self.assertEqual(gen.python_type(spec), expected)
        with self.assertRaises(ValueError):  # unknown domain fails loudly
            gen.python_type(ValueSpec(children=True))

        def prop(value, animatable):
            return type("P", (), {"value": value, "animatable": animatable})()

        self.assertEqual(gen.prop_type(prop(ValueSpec(finite=True), True)), "AnimatableNumber")
        self.assertEqual(gen.prop_type(prop(ValueSpec(finite=True), False)), "int | float")
        self.assertEqual(
            gen.prop_type(prop(ValueSpec(exact_types=(str, int, float), dimension=True), True)),
            "str | int | float | AnimatedNode",
        )

def _fake_schema():
    return SimpleNamespace(
        PRIMITIVE_KINDS=dict(PRIMITIVE_KINDS),
        ALL_PROPS=dict(ALL_PROPS),
        EVENT_SPECS=dict(EVENT_SPECS),
        PROPS_BY_KIND={k: frozenset(v) for k, v in PROPS_BY_KIND.items()},
    )

def _prop(default=None):
    return SimpleNamespace(default=default, animatable=False, value=ValueSpec(finite=True))

def _kind(required=(), allowed_children=()):
    return SimpleNamespace(required=frozenset(required), allowed_children=frozenset(allowed_children))


class SchemaDerivedPolicyTests(unittest.TestCase):
    """Container/event policy derives from schema data, not local copies."""

    def test_future_container_and_internal_events(self):
        schema = _fake_schema()
        schema.PRIMITIVE_KINDS["Flow"] = _kind(allowed_children=("Text",))
        schema.ALL_PROPS["flow_only_prop"] = _prop(default=0)
        schema.PROPS_BY_KIND["Flow"] = frozenset(PROPS_BY_KIND["Box"]) | {"flow_only_prop"}
        self.assertEqual(gen.container_kinds(schema), CONTAINER_KINDS_SET | {"Flow"})
        events = gen.public_events(schema)
        self.assertNotIn("scroll_metrics", events)
        self.assertNotIn("scroll_seek", events)
        self.assertNotIn("layout_metrics", events)
        self.assertIn("click", events)
        self.assertEqual(
            INTERNAL_EVENTS,
            frozenset({"layout_metrics", "scroll_metrics", "scroll_seek"}),
        )
        self.assertIn("Flow", gen.build_model(schema)[5])
        original = dict(gen._CONSTRUCTORS)
        try:
            gen._CONSTRUCTORS["Flow"] = "Flow"
            rendered = gen.render(*gen.build_model(schema))
            self.assertIn("class FlowProps(ContainerProps, total=False):", rendered)
            self.assertIn("def Flow(*children: Any, **props: Unpack[FlowProps])", rendered)
        finally:
            gen._CONSTRUCTORS.clear()
            gen._CONSTRUCTORS.update(original)
        # A future required shared prop cannot express Required[] via
        # TypedDict inheritance, so generation must fail loudly.
        schema = _fake_schema()
        schema.PRIMITIVE_KINDS["Text"] = _kind(required=("required_label",))
        schema.ALL_PROPS["required_label"] = _prop(default=None)
        schema.PROPS_BY_KIND = {
            kind: frozenset(PROPS_BY_KIND[kind]) | {"required_label"}
            for kind in PROPS_BY_KIND
        }
        with self.assertRaisesRegex(ValueError, "Required"):
            gen.build_model(schema)


class StubStructureTests(unittest.TestCase):
    """The generated stub carries the schema-derived public surface."""

    @classmethod
    def setUpClass(cls):
        cls.text = STUB.read_text(encoding="utf-8")
        schema = __import__("vyne.spec.schema_v2", fromlist=["*"])
        cls.shared, cls.container_only, cls.widget, cls.required, cls.containers = (
            gen.build_model(schema)[1:]
        )

    def test_shared_surface_matches_schema(self):
        generic = {n for n, p in ALL_PROPS.items() if not n.startswith("_") and not p.applies_to}
        all_events = {f"on_{e}" for e, s in EVENT_SPECS.items()
                      if s.public_callback and (not s.applies_to or len(s.applies_to) == len(PRIMITIVE_KINDS))}
        self.assertEqual(set(self.shared), generic | all_events | SHARED_PYTHON_ONLY)
        for name, type_expr in PYTHON_ONLY_TYPES.items():
            self.assertEqual(self.shared[name], type_expr, name)
        self.assertEqual(self.widget["Path"]["d"], "str")
        self.assertNotIn("d", ALL_PROPS)
        self.assertNotIn("size", self.shared)
        for alias, canonical in gen._ALIAS_CANONICAL.items():
            self.assertIn(canonical, ALL_PROPS)
        for name in ALL_PROPS:
            if name.startswith("_"):
                self.assertNotIn(name, self.shared)
                for fields in self.widget.values():
                    self.assertNotIn(name, fields)
        expected = {n for n, p in ALL_PROPS.items() if p.applies_to == CONTAINER_KINDS_SET}
        self.assertEqual(set(self.container_only), expected)

    def test_widget_surfaces_and_events_match_schema(self):
        event_kinds = {e.name: e for e in EVENT_SPECS.values() if e.name not in INTERNAL_EVENTS}
        for constructor, kind in gen._PUBLIC_CONSTRUCTORS.items():
            schema_fields = {name for name in PROPS_BY_KIND[kind] if not name.startswith("_")}
            surface = set(self.shared) | set(self.widget[constructor])
            if kind in self.containers:
                surface |= set(self.container_only)
            excluded = gen._EXCLUDED_CONSTRUCTOR_PROPS.get(constructor, frozenset())
            for name in schema_fields - excluded:
                self.assertIn(name, surface, f"{constructor} misses schema prop {name!r}")
            allowed_events = {
                f"on_{e.name}" for e in event_kinds.values()
                if not e.applies_to or kind in e.applies_to
            }
            allowed = (schema_fields | allowed_events | SHARED_PYTHON_ONLY
                       | set(gen._EXTRA_CONSTRUCTOR_PROPS.get(constructor, {})))
            self.assertFalse(
                surface - allowed,
                f"{constructor} carries unexpected props {sorted(surface - allowed)}",
            )
        for spec in EVENT_SPECS.values():
            if not spec.public_callback:
                self.assertNotIn(f"on_{spec.name}", self.shared)
                for fields in self.widget.values():
                    self.assertNotIn(f"on_{spec.name}", fields)
                continue
            if not spec.applies_to or len(spec.applies_to) == len(PRIMITIVE_KINDS):
                self.assertIn(f"on_{spec.name}", self.shared)
                continue
            for constructor, kind in gen._PUBLIC_CONSTRUCTORS.items():
                present = (f"on_{spec.name}" in self.widget[constructor]
                           or f"on_{spec.name}" in self.shared)
                self.assertEqual(kind in spec.applies_to, present,
                                 f"on_{spec.name} on {constructor}")

    def test_element_surface_and_optional_none(self):
        self.assertIn("GENERATED FILE. DO NOT EDIT.", self.text)
        self.assertIn("scripts/generate_schema_stubs.py", self.text)
        self.assertIn("@dataclass(frozen=True)", self.text)
        self.assertIn("children: tuple[Element, ...] = ()", self.text)
        self.assertIn("props: Mapping[str, Any] | FrozenMap = ...", self.text)
        self.assertNotIn("Iterable[Element] | None", self.text)
        self.assertNotIn("| None = ...", self.text.split("children:")[0])
        for constructor in gen._PUBLIC_CONSTRUCTORS:
            self.assertIn(f"def {constructor}(", self.text)
        for name in ("def normalize_child(", "def normalize_children(",
                     "def event_name_for_prop(", "def _horizontal_scroll("):
            self.assertIn(name, self.text)
        required = {name for fields in self.required.values() for name in fields}
        for mapping in (self.shared, self.container_only, *self.widget.values()):
            for name, type_expr in mapping.items():
                if name in required:
                    continue
                self.assertIn(f"{name}: {gen._optional_type(type_expr)}", self.text)
        self.assertEqual(self.required["Layout"], frozenset())
        self.assertEqual(self.widget["Canvas"]["draw"], "list[Any]")
        self.assertIn("draw: list[Any] | None", self.text)
        self.assertNotIn("draw: list[Any] | tuple[Any, ...]", self.text)
        self.assertEqual(ALL_PROPS["draw"].value.exact_types, (list, tuple))

POSITIVE_SAMPLE = """\
from dataclasses import replace
from typing import cast
from vyne.animations import AnimatedNode
from vyne.elements import Box, Canvas, Column, Path, Row, Text, TextInput
from vyne.refs import Ref
from vyne.style import Decoration, Style

def handler(event: object) -> None: ...

animated = cast(AnimatedNode, None)
Box(key=("section", 3), ref=Ref(), style=Style(), decoration=Decoration(),
    padding=8, corner_radius=4, alpha=0.5, accessibility_state_checked=True,
    on_click=None, on_pointer_move=handler, width=animated, elevation=animated)
Text(text="hi", on_click=handler)
Row(Column(Text(text="x")), align_items="center")
TextInput(on_text_change=handler, focused=True)
Path(d="M 0 0", stroke_width=1)
Canvas(draw=[{"kind": "rect", "x": 0, "y": 0, "width": 1, "height": 1}])
replace(Box(key="x"), props={"lp_weight": 1})
"""

NEGATIVE_SAMPLE = """\
from vyne import Box, Row, Text, TextInput

Text(on_click="not callable")
Box(padding="10")
Box(size=10)
Row(orientation="vertical")
TextInput(on_text_change="nope")
Text(text=123)
"""


class StubTypeCheckerSmokeTests(unittest.TestCase):
    """mypy smoke: valid usage passes, wrong usage fails (skips without mypy)."""

    @classmethod
    def setUpClass(cls):
        exe = shutil.which("mypy")
        if exe is None:
            raise unittest.SkipTest("mypy not found in PATH")
        cls.command = [exe, "--python-executable", sys.executable]

    def _run(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "sample.py"
            sample.write_text(source, encoding="utf-8")
            return subprocess.run(
                [*self.command, str(sample)], capture_output=True, text=True
            )

    def test_valid_usage_passes(self):
        result = self._run(POSITIVE_SAMPLE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_wrong_usage_fails(self):
        result = self._run(NEGATIVE_SAMPLE)
        self.assertNotEqual(result.returncode, 0, result.stdout)

if __name__ == "__main__":
    unittest.main()
