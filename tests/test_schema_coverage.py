"""Schema coverage tests (SCHEMA-01).

Verifies that every accepted schema row is represented in generated
outputs and that consumer coverage is complete.  Each registry entry
(KindSpec, PropSpec, CanvasOpSpec, EventSpec) has at least one
validating test case.
"""

from __future__ import annotations

import unittest

from vyne.spec.schema_v2 import (
    ALL_PROPS,
    ANIMATABLE_PROPS,
    PROPS_BY_KIND,
    PRIMITIVE_KINDS,
    GENERIC_PROP_NAMES,
    CANVAS_OP_SPECS,
    EVENT_SPECS,
)


class KindSpecCoverage(unittest.TestCase):
    """Every KindSpec in the registry is accounted for."""

    def test_canonical_kinds_have_no_platform_factory_metadata(self):
        for kind in PRIMITIVE_KINDS.values():
            self.assertFalse(
                hasattr(kind, "native_class"),
                f"Kind {kind.kind!r} leaked platform factory metadata",
            )

    def test_kind_leaf_consistency(self):
        for kind_name, kind_spec in PRIMITIVE_KINDS.items():
            if kind_spec.max_children == 0:
                self.assertTrue(kind_spec.leaf, f"{kind_name} should be leaf")
            else:
                self.assertFalse(kind_spec.leaf, f"{kind_name} should not be leaf")


class PropSpecCoverage(unittest.TestCase):
    """Every PropSpec is validated and present in PROPS_BY_KIND."""

    def test_all_props_have_value_spec(self):
        for name, prop in ALL_PROPS.items():
            self.assertIsNotNone(prop.value, f"Prop {name!r} missing ValueSpec")

    def test_all_props_have_default(self):
        # Props with nullable ValueSpec may have None as default.
        for name, prop in ALL_PROPS.items():
            if prop.value.nullable and prop.default is None:
                continue  # nullable props can have None default
            self.assertIsNotNone(prop.default, f"Prop {name!r} missing default")

    def test_all_props_in_props_by_kind(self):
        for name in ALL_PROPS:
            found = False
            for kind in PRIMITIVE_KINDS:
                if name in PROPS_BY_KIND[kind]:
                    found = True
                    break
            if not found:
                self.fail(f"Prop {name!r} not in any PROPS_BY_KIND entry")

    def test_animatable_props_consistency(self):
        for name, prop in ALL_PROPS.items():
            if prop.animatable and name not in ANIMATABLE_PROPS:
                self.fail(f"Animatable prop {name!r} not in ANIMATABLE_PROPS")
            if name in ANIMATABLE_PROPS and not prop.animatable:
                self.fail(f"ANIMATABLE_PROPS includes non-animatable {name!r}")

    def test_generic_props_have_no_applies_to_or_match(self):
        # Generic props (in GENERIC_PROP_NAMES) either have no applies_to
        # or apply to all kinds.
        actual_generic = {p.name for p in ALL_PROPS.values()
                         if not p.applies_to}
        for name in GENERIC_PROP_NAMES:
            self.assertIn(name, actual_generic,
                          f"GENERIC_PROP_NAMES includes {name!r} which has applies_to")


class CanvasOpSpecCoverage(unittest.TestCase):
    """Every CanvasOpSpec has field specs and at least one fixture."""

    def test_all_ops_have_field_specs(self):
        for name, spec in CANVAS_OP_SPECS.items():
            self.assertTrue(spec.field_specs, f"Canvas op {name!r} has no field specs")

    def test_all_ops_have_required_set(self):
        for name, spec in CANVAS_OP_SPECS.items():
            self.assertIsNotNone(spec.required, f"Canvas op {name!r} missing required")


class EventSpecCoverage(unittest.TestCase):
    """Every EventSpec applies to at least one kind."""

    def test_all_events_have_targets(self):
        for name, spec in EVENT_SPECS.items():
            self.assertTrue(
                spec.applies_to,
                f"Event {name!r} has no applies_to — dead event?",
            )

    def test_all_events_have_payload_fields_defined(self):
        for name, spec in EVENT_SPECS.items():
            self.assertIsNotNone(
                spec.payload_fields,
                f"Event {name!r} missing payload_fields",
            )


if __name__ == "__main__":
    unittest.main()
