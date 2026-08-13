#!/usr/bin/env python3
"""Generate PEP 561 typing stubs for ``vyne.elements`` from the schema.

``vyne.spec.schema_v2`` is the single maintained source for primitive
properties, events, and animation eligibility.  Type checkers read the
generated ``elements.pyi``; the runtime stays free of generated metadata.

Run: ``uv run python scripts/generate_schema_stubs.py [--check] [--output PATH]``
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON_ROOT = ROOT / "packages" / "vyne" / "src"
OUTPUT = PYTHON_ROOT / "vyne" / "elements.pyi"
PYTYPED = PYTHON_ROOT / "vyne" / "py.typed"

# Constructor -> canonical kind: the single ordered source for both the props
# classes and the emitted signatures.  ``_horizontal_scroll`` is private but
# schema-backed like every other entry.
_CONSTRUCTORS = {
    "Box": "Box", "Layout": "Layout", "Row": "Layout", "Column": "Layout",
    "Scroll": "Scroll", "Text": "Text", "TextInput": "TextInput",
    "Image": "Image", "Path": "Path", "Canvas": "Canvas",
    "_horizontal_scroll": "HorizontalScroll",
}
_PUBLIC_CONSTRUCTORS = {
    name: kind for name, kind in _CONSTRUCTORS.items() if not name.startswith("_")
}

# Constructor-only props that never reach the wire: fixed Python-only props
# shared by every constructor, plus shorthand/alias props whose types derive
# from their canonical schema targets at generation time.
_SHARED_PYTHON_ONLY_PROPS = {
    "key": "ElementKey",
    "decoration": "Decoration | dict[str, Any]",
    "ref": "Ref",
}
_ALIAS_CANONICAL = {
    "alpha": "opacity",
    "accessibility_state_checked": "accessibility_checked",
    "accessibility_state_selected": "accessibility_selected",
    "padding": "padding_top",
    "corner_radius": "corner_radius_top_left",
}

# Per-constructor prop typing adjustments.  ``Path.d`` is compiled away before
# lowering; ``Canvas.draw`` overrides the canonical list-or-tuple domain with
# the public constructor's list-only surface.
_EXTRA_CONSTRUCTOR_PROPS = {
    "Path": {"d": "str"},
    "Canvas": {"draw": "list[Any]"},
}
_EXCLUDED_CONSTRUCTOR_PROPS = {
    "Row": frozenset({"orientation"}),
    "Column": frozenset({"orientation"}),
}
_PROPS_CLASS_OVERRIDES = {"_horizontal_scroll": "HorizontalScrollProps"}
_NAMED_TYPES = {
    "bool": "bool", "str": "str", "int": "int", "float": "float",
    "number": "int | float", "tuple": "tuple[Any, ...]", "list": "list[Any]",
    "dict": "dict[str, Any]", "FrozenMap": "FrozenMap[str, Any]",
}

def _load_schema():
    """Import the authoritative schema, adding the package root if needed."""
    if str(PYTHON_ROOT) not in sys.path:
        sys.path.insert(0, str(PYTHON_ROOT))
    import vyne.spec.schema_v2 as schema
    return schema

def _schema_hash(schema) -> str:
    """Short content hash of the schema module, surfaced in the stub header."""
    import vyne.spec.schema_v2 as real_schema
    return hashlib.sha256(Path(real_schema.__file__).read_bytes()).hexdigest()[:16]

def python_type(spec) -> str:
    """Map a ValueSpec domain to a Python type expression; nullable -> ``| None``."""
    if spec.enum is not None:
        literals = ", ".join(repr(value) for value in sorted(spec.enum))
        result = f"Literal[{literals}]"
    elif spec.dimension:
        result = "str | int | float"
    elif spec.dash_array:
        result = "tuple[int | float, ...] | str"
    elif spec.string_map:
        result = "FrozenMap[str, Any]"
    elif spec.item_spec is not None or spec.min_items is not None or spec.max_items is not None:
        item = python_type(spec.item_spec) if spec.item_spec is not None else "Any"
        result = f"list[{item}] | tuple[{item}, ...]"
    elif spec.type_name is not None:
        if spec.type_name not in _NAMED_TYPES:
            raise ValueError(f"Unknown schema type_name {spec.type_name!r}")
        result = _NAMED_TYPES[spec.type_name]
    elif spec.exact_types:
        result = _exact_types(spec.exact_types)
    elif spec.finite or spec.positive or spec.non_negative or spec.min_value is not None or spec.max_value is not None:
        result = "int | float"
    else:
        raise ValueError(f"Unmapped ValueSpec domain: {spec!r}")
    return result + (" | None" if spec.nullable else "")

def _exact_types(types) -> str:
    """Map the explicit-types value domain to a Python type expression."""
    if frozenset(types) == frozenset({list, tuple}):
        return "list[Any] | tuple[Any, ...]"
    if frozenset(types) == frozenset({str, int, float}):
        return "str | int | float"
    if tuple(types) == (list,):
        return "list[Any]"
    if tuple(types) == (tuple,):
        return "tuple[Any, ...]"
    return " | ".join(t.__name__ for t in types)

def prop_type(prop) -> str:
    """Type expression for one PropSpec, widening animatable props."""
    base = python_type(prop.value)
    if not prop.animatable:
        return base
    return "AnimatableNumber" if base == "int | float" else f"{base} | AnimatedNode"

def container_kinds(schema) -> frozenset[str]:
    """Kinds that may host children, derived from ``KindSpec.allowed_children``."""
    return frozenset(kind for kind, spec in schema.PRIMITIVE_KINDS.items() if spec.allowed_children)

def public_events(schema) -> frozenset[str]:
    """Public ``on_<name>`` callbacks; internal renderer observations stay off."""
    return frozenset(name for name, spec in schema.EVENT_SPECS.items() if spec.public_callback)

def build_model(schema):
    """Derive (hash, shared, container_only, widget_fields, widget_required,
    containers) typing surfaces from the schema."""
    kind_props: dict[str, dict[str, str]] = {}
    for kind in schema.PRIMITIVE_KINDS:
        fields = {
            name: prop_type(schema.ALL_PROPS[name])
            for name in sorted(schema.PROPS_BY_KIND[kind])
            if not name.startswith("_")
        }
        for event_name, spec in sorted(schema.EVENT_SPECS.items()):
            if spec.public_callback and (not spec.applies_to or kind in spec.applies_to):
                fields[f"on_{event_name}"] = "EventCallback"
        kind_props[kind] = fields

    all_kinds = list(schema.PRIMITIVE_KINDS)
    shared = set(kind_props[all_kinds[0]]).intersection(
        *(kind_props[kind] for kind in all_kinds[1:])
    )
    python_only_types = dict(_SHARED_PYTHON_ONLY_PROPS)
    for alias, canonical in sorted(_ALIAS_CANONICAL.items()):
        prop = schema.ALL_PROPS.get(canonical)
        if prop is None:
            raise ValueError(f"Alias {alias!r} targets unknown canonical prop {canonical!r}")
        python_only_types[alias] = prop_type(prop)
    shared |= set(python_only_types)

    containers = container_kinds(schema)
    container_list = [kind for kind in all_kinds if kind in containers]
    container_common = set(kind_props[container_list[0]]).intersection(
        *(kind_props[kind] for kind in container_list[1:])
    )
    container_only = container_common - shared

    widget_fields: dict[str, dict[str, str]] = {}
    widget_required: dict[str, frozenset[str]] = {}
    for constructor, kind in _CONSTRUCTORS.items():
        excluded = _EXCLUDED_CONSTRUCTOR_PROPS.get(constructor, frozenset())
        fields = {
            name: value
            for name, value in kind_props[kind].items()
            if name not in shared and name not in container_only and name not in excluded
        }
        fields.update(_EXTRA_CONSTRUCTOR_PROPS.get(constructor, {}))
        widget_fields[constructor] = fields
        # Every kind-required prop carries a schema default, so no constructor
        # prop is truly mandatory: ``Required[...]`` is never emitted.
        widget_required[constructor] = frozenset()

    shared_values = {
        name: python_only_types.get(name) or kind_props[all_kinds[0]][name]
        for name in sorted(shared)
    }
    container_values = {
        name: kind_props[all_kinds[0]][name] for name in sorted(container_only)
    }
    return (_schema_hash(schema), shared_values, container_values, widget_fields, widget_required, containers)

_HEADER = """\
\"\"\"Type stubs for ``vyne.elements``.

GENERATED FILE. DO NOT EDIT.

Regenerate with:
    uv run python scripts/generate_schema_stubs.py

Source of truth: ``vyne.spec.schema_v2``.
\"\"\"
"""

def _optional_type(expr: str) -> str:
    """Every optional prop accepts explicit None (lowering drops None values)."""
    return expr if expr.endswith(" | None") else f"{expr} | None"

def _render_typed_dict(name, base, fields, required) -> list[str]:
    lines = [f"class {name}({base}, total=False):"]
    if not fields:
        lines.append("    ...")
        return lines
    for prop in sorted(fields):
        value = fields[prop]
        lines.append(
            f"    {prop}: {f'Required[{value}]' if prop in required else _optional_type(value)}"
        )
    return lines

def render(schema_hash, shared, container_only, widget_fields, widget_required, containers) -> str:
    """Render the complete deterministic stub text."""
    lines: list[str] = [_HEADER, f"# schema-v2 source hash: {schema_hash}", ""]
    if any(widget_required.values()):
        lines.append("from typing import Any, Literal, Required, TypeAlias, TypedDict, Unpack")
    else:
        lines.append("from typing import Any, Literal, TypeAlias, TypedDict, Unpack")
    lines.extend(
        [
            "",
            "from collections.abc import Callable, Mapping",
            "from dataclasses import dataclass",
            "",
            "from vyne.animations import AnimatedNode",
            "from vyne.refs import Ref",
            "from vyne.style import Decoration",
            "from vyne.values import FrozenMap",
            "",
            "EventCallback = Callable[..., Any]",
            "AnimatableNumber = int | float | AnimatedNode",
            "ElementKey: TypeAlias = str | int | tuple[ElementKey, ...]",
            "",
        ]
    )
    lines.extend(_render_typed_dict("BaseProps", "TypedDict", shared, frozenset()))
    lines.append("")
    lines.extend(_render_typed_dict("ContainerProps", "BaseProps", container_only, frozenset()))
    for constructor, kind in _CONSTRUCTORS.items():
        lines.append("")
        base = "ContainerProps" if kind in containers else "BaseProps"
        props_class = _PROPS_CLASS_OVERRIDES.get(constructor, f"{constructor}Props")
        lines.extend(
            _render_typed_dict(
                props_class, base, widget_fields[constructor], widget_required[constructor]
            )
        )
    lines.extend(
        [
            "",
            "",
            "@dataclass(frozen=True)",
            "class Element:",
            "    kind: str",
            "    # Runtime keeps the frozen FrozenMap; the constructor accepts any",
            "    # mapping (converted and frozen in ``__post_init__``).",
            "    props: Mapping[str, Any] | FrozenMap = ...",
            "    children: tuple[Element, ...] = ()",
            "",
        ]
    )
    for constructor, kind in _CONSTRUCTORS.items():
        props_class = _PROPS_CLASS_OVERRIDES.get(constructor, f"{constructor}Props")
        if kind in containers:
            lines.append(
                f"def {constructor}(*children: Any, **props: Unpack[{props_class}]) -> Element: ..."
            )
        else:
            lines.append(f"def {constructor}(**props: Unpack[{props_class}]) -> Element: ...")
    lines.extend(
        [
            "def normalize_child(child: Any) -> Element: ...",
            "def normalize_children(children: tuple[Any, ...]) -> tuple[Element, ...]: ...",
            "def event_name_for_prop(prop_name: str) -> str | None: ...",
            "",
        ]
    )
    return "\n".join(lines)

def generate() -> str:
    return render(*build_model(_load_schema()))

def _display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)

def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    check = "--check" in args
    output = OUTPUT
    if "--output" in args:
        index = args.index("--output")
        if index + 1 >= len(args):
            print("--output requires a path")
            return 2
        output = Path(args[index + 1])
    py_typed = output.parent / "py.typed" if "--output" in args else PYTYPED
    content = generate()
    drift = not output.is_file() or output.read_text(encoding="utf-8") != content
    if not check:
        output.write_text(content, encoding="utf-8")
        py_typed.write_text("", encoding="utf-8")
        print(f"Wrote {_display(output)}")
        print(f"Wrote {_display(py_typed)}")
        return 0
    if drift:
        print(f"DIFF: {_display(output)}")
        return 1
    if not py_typed.is_file():
        print(f"MISSING: {_display(py_typed)}")
        return 1
    print(f"{_display(output)} is up to date.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
