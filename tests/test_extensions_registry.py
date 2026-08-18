"""Host-synced extension contract registry tests (EXT-01).

The Kotlin ElementRegistry is the single source of truth: Python syncs
kind -> (props, events) tables at startup and core schema_v2 stays
authoritative for core kinds. These tests cover table building, resolver
precedence, event-prop derivation, and retry cleanup.
"""

from __future__ import annotations

import unittest

from tests.support.extension_kinds import (
    KINDS,
    activate_extension_kinds,
    deactivate_extension_kinds,
)

from vyne.extensions_registry import (
    GENERIC_PROPS,
    ExtensionKindInfo,
    ExtensionNumericProp,
    event_name_for_prop,
    is_animatable_prop,
    is_event_prop,
    props_by_kind,
    resolve_event,
    resolve_kind,
    resolve_prop,
    resolve_prop_for_kind,
    snapshot,
    sync_from_host,
)


def setUpModule() -> None:
    activate_extension_kinds()


def tearDownModule() -> None:
    deactivate_extension_kinds()


class SyncFromHostTests(unittest.TestCase):
    def tearDown(self) -> None:
        sync_from_host(KINDS)

    def test_accepts_pair_and_info_forms(self):
        sync_from_host({
            "A": (["p1"], ["e1"], [False]),
            "B": ExtensionKindInfo(props=frozenset({"p2"}), events=frozenset({"e2"})),
            "C": (
                ["level"],
                [],
                [False],
                {"level": ExtensionNumericProp(default=0.0, minimum=0.0, maximum=10.0)},
            ),
        })
        self.assertIn("p1", props_by_kind("A"))
        self.assertIn("p2", props_by_kind("B"))
        self.assertTrue(is_event_prop("on_e2", "B"))
        self.assertTrue(is_animatable_prop("C", "level"))
        self.assertEqual(resolve_prop_for_kind("C", "level").default, 0.0)

    def test_sync_replaces_previous_tables(self):
        sync_from_host({"Old": (["p"], [], [False])})
        self.assertIsNotNone(resolve_kind("Old"))
        sync_from_host(KINDS)
        self.assertIsNone(resolve_kind("Old"))
        self.assertIsNotNone(resolve_kind("TimerRing"))

    def test_empty_sync_removes_everything(self):
        sync_from_host({})
        self.assertIsNone(resolve_kind("TimerRing"))
        sync_from_host(KINDS)
        self.assertIsNotNone(resolve_kind("TimerRing"))

    def test_core_kind_collision_rejected(self):
        with self.assertRaisesRegex(ValueError, "collides with a core primitive kind"):
            sync_from_host({"Text": (["p"], [], [False])})
        # The failed sync must not corrupt the active tables.
        self.assertIsNotNone(resolve_kind("TimerRing"))
        self.assertIsNone(resolve_prop("p"))


class ResolverPrecedenceTests(unittest.TestCase):
    def test_core_lookup_precedence(self):
        self.assertEqual(resolve_kind("Text").kind, "Text")
        self.assertIsNotNone(resolve_prop("width"))
        self.assertIsNone(resolve_prop("progress"))  # extension props: no specs
        self.assertIsNotNone(resolve_event("click"))
        self.assertIsNotNone(resolve_event("complete"))

    def test_extension_kind_props_include_generic_set(self):
        props = props_by_kind("TimerRing")
        self.assertLessEqual(GENERIC_PROPS, props)
        self.assertIn("progress", props)
        self.assertIn("ring_color", props)
        self.assertNotIn("text", props)  # widget-specific core props stay out

    def test_extension_numeric_prop_is_animatable_and_kind_scoped(self):
        self.assertTrue(is_animatable_prop("TimerRing", "progress"))
        self.assertTrue(is_animatable_prop("TimerRing", "opacity"))
        self.assertFalse(is_animatable_prop("TimerRing", "ring_color"))
        self.assertFalse(is_animatable_prop("Box", "progress"))
        spec = resolve_prop_for_kind("TimerRing", "progress")
        self.assertEqual(spec.value.min_value, 0.0)
        self.assertEqual(spec.value.max_value, 1.0)
        self.assertTrue(spec.animatable)

    def test_extension_event_prop_unknown_kind(self):
        self.assertFalse(is_event_prop("on_complete", "Unknown"))
        self.assertIsNone(event_name_for_prop("on_complete", "Unknown"))

    def test_generic_props_is_intersection_of_core_kinds(self):
        from vyne.spec.schema_v2 import PROPS_BY_KIND
        expected = frozenset.intersection(*PROPS_BY_KIND.values())
        self.assertEqual(GENERIC_PROPS, expected)

    def test_unknown_kind_and_event(self):
        self.assertIsNone(resolve_kind("NoSuchKind"))
        self.assertIsNone(resolve_event("no_such_event"))


class EventPropDerivationTests(unittest.TestCase):
    def test_core_event_props_unchanged(self):
        for prop in ("on_click", "on_text_change", "on_focus_change"):
            self.assertTrue(is_event_prop(prop))
        self.assertEqual(event_name_for_prop("on_click"), "click")

    def test_extension_event_props_derived_from_synced_names(self):
        self.assertTrue(is_event_prop("on_complete", "TimerRing"))
        self.assertEqual(event_name_for_prop("on_complete", "TimerRing"), "complete")

    def test_extension_event_prop_rejected_on_core_kind(self):
        # Extension events are per-kind; a core kind never accepts them.
        self.assertFalse(is_event_prop("on_complete", "Text"))
        self.assertIsNone(event_name_for_prop("on_complete", "Text"))

    def test_undeclared_on_prop_is_not_an_event(self):
        self.assertFalse(is_event_prop("on_mystery", "TimerRing"))
        self.assertIsNone(event_name_for_prop("on_mystery", "TimerRing"))
        self.assertFalse(is_event_prop("mystery", "TimerRing"))


if __name__ == "__main__":
    unittest.main()
