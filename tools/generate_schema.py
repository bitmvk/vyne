#!/usr/bin/env python3
"""Generate the Kotlin renderer contracts from Python's canonical schema."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PYTHON_ROOT = ROOT / "packages" / "vyne" / "src"
OUTPUT = (
    ROOT
    / "android"
    / "host"
    / "src"
    / "main"
    / "java"
    / "dev"
    / "vyne"
    / "generated"
    / "ElementContracts.kt"
)


def _schema_hash() -> str:
    import vyne.spec.schema_v2 as schema

    source = Path(schema.__file__).read_bytes()
    return hashlib.sha256(source).hexdigest()[:16]


def _numeric(value: object) -> float | None:
    """Return a finite Kotlin Double for numeric scalar metadata, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def _generate(schema_hash: str) -> str:
    from vyne.spec.schema_v2 import (
        ALL_PROPS,
        ANIMATABLE_PROPS,
        EVENT_SPECS,
        PRIMITIVE_KINDS,
        PROPS_BY_KIND,
    )

    kinds = tuple(PRIMITIVE_KINDS)
    lines = [
        "/** Generated Vyne element property contracts.",
        f" * DO NOT EDIT. Generated from vyne.spec.schema_v2 (hash={schema_hash}).",
        " */",
        "package dev.vyne.generated",
        "",
        "object ElementContracts {",
        f'    const val SCHEMA_HASH = "{schema_hash}"',
        "",
        "    val KINDS: Set<String> = setOf(",
        *(f'        "{kind}",' for kind in kinds),
        "    )",
        "",
        "    val ALL_PROPS_BY_KIND: Map<String, Set<String>> = mapOf(",
    ]
    for kind in kinds:
        props = ", ".join(f'"{name}"' for name in sorted(PROPS_BY_KIND[kind]))
        lines.append(f'        "{kind}" to setOf({props}),')
    lines.extend(
        [
            "    )",
            "",
            "    val GENERIC_PROPS: Set<String> = setOf(",
        ]
    )
    generic = frozenset.intersection(
        *(frozenset(v) for v in PROPS_BY_KIND.values())
    )
    lines.extend(f'        "{name}",' for name in sorted(generic))
    lines.extend(
        [
            "    )",
            "",
            "    val ANIMATABLE_PROPS: Set<String> = setOf(",
            *(f'        "{name}",' for name in sorted(ANIMATABLE_PROPS)),
            "    )",
            "",
        ]
    )
    animatable_props = sorted(ANIMATABLE_PROPS)
    defaults = {
        name: value
        for name in animatable_props
        if (value := _numeric(ALL_PROPS[name].default)) is not None
    }
    lines.append("    val ANIMATABLE_PROP_DEFAULTS: Map<String, Double> = mapOf(")
    for name in sorted(defaults):
        lines.append(f'        "{name}" to {defaults[name]!r},')
    lines.append("    )")
    lines.append("")
    minima = {}
    maxima = {}
    positive = []
    for name in animatable_props:
        spec = ALL_PROPS[name].value
        minimum = _numeric(spec.min_value)
        if minimum is None and (spec.non_negative or spec.dimension):
            minimum = 0.0
        maximum = _numeric(spec.max_value)
        if minimum is not None:
            minima[name] = minimum
        if maximum is not None:
            maxima[name] = maximum
        if spec.positive:
            positive.append(name)
    lines.append("    val ANIMATABLE_PROP_MIN: Map<String, Double> = mapOf(")
    for name in sorted(minima):
        lines.append(f'        "{name}" to {minima[name]!r},')
    lines.append("    )")
    lines.append("")
    lines.append("    val ANIMATABLE_PROP_MAX: Map<String, Double> = mapOf(")
    for name in sorted(maxima):
        lines.append(f'        "{name}" to {maxima[name]!r},')
    lines.append("    )")
    lines.append("")
    lines.append("    val POSITIVE_ANIMATABLE_PROPS: Set<String> = setOf(")
    for name in sorted(positive):
        lines.append(f'        "{name}",')
    lines.append("    )")
    lines.append("")
    events_by_kind: dict[str, list[str]] = {}
    for kind in kinds:
        events = sorted(
            event.name
            for event in EVENT_SPECS.values()
            if not event.applies_to or kind in event.applies_to
        )
        events_by_kind[kind] = events
        encoded = ", ".join(f'"{event}"' for event in events)
        lines.append(
            f"    val {kind.upper()}_EVENTS: Set<String> = setOf({encoded})"
        )
    all_names = sorted({e for events in events_by_kind.values() for e in events})
    lines.append("")
    lines.append("    val ALL_EVENT_NAMES: Set<String> = setOf(")
    lines.extend(f'        "{name}",' for name in all_names)
    lines.append("    )")
    lines.append("")
    lines.append("    val ALL_EVENTS_BY_KIND: Map<String, Set<String>> = mapOf(")
    for kind in kinds:
        lines.append(f'        "{kind}" to {kind.upper()}_EVENTS,')
    lines.append("    )")
    lines.extend(["", "}", ""])
    return "\n".join(lines)


def main() -> int:
    if str(PYTHON_ROOT) not in sys.path:
        sys.path.insert(0, str(PYTHON_ROOT))

    content = _generate(_schema_hash())
    if "--check" in sys.argv:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != content:
            print(f"DIFF: {OUTPUT.relative_to(ROOT)}")
            return 1
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
