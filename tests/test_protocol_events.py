from __future__ import annotations

import unittest

from vyne.events import Event, EventRegistry
from vyne.protocol import ensure_bridge_value, error_commit
from vyne.style import Style


class ProtocolTests(unittest.TestCase):
    def test_error_commit_contains_revision_and_prefix(self):
        commit = error_commit("failed", revision=7, prefix="Error: ")

        self.assertEqual(commit["revision"], 7)
        self.assertEqual(commit["ops"][-2]["props"], {"text": "Error: failed"})

    def test_style_values_can_cross_bridge(self):
        ensure_bridge_value(Style(text_color="#123456"), prop_name="style")

        with self.assertRaisesRegex(TypeError, "native bridge"):
            ensure_bridge_value(object(), prop_name="value")

        with self.assertRaisesRegex(TypeError, "native bridge"):
            ensure_bridge_value({"value": float("nan")}, prop_name="value")


class EventTests(unittest.TestCase):
    def test_event_from_message_defaults_payload_and_reads_values(self):
        event = Event.from_message(
            {"event": "click", "target": "4", "handler": "8", "seq": 12}
        )

        self.assertEqual(event.target, 4)
        self.assertEqual(event.handler, 8)
        self.assertEqual(event.sequence, 12)
        self.assertEqual(event.get("missing", "fallback"), "fallback")

    def test_event_rejects_non_object_payload(self):
        with self.assertRaisesRegex(TypeError, "payload"):
            Event.from_message(
                {"event": "click", "target": 1, "handler": 2, "payload": []}
            )

    def test_registry_wraps_zero_argument_handlers(self):
        calls: list[str] = []
        registry = EventRegistry()
        registry.begin_render()
        handler_id = registry.register(lambda: calls.append("called"))
        registry.end_render()

        registry.dispatch(Event("click", 1, handler_id, {}))
        self.assertEqual(calls, ["called"])

    def test_registry_removes_handlers_not_seen_in_next_render(self):
        registry = EventRegistry()
        registry.begin_render()
        handler_id = registry.register(lambda event: None)
        registry.end_render()

        registry.begin_render()
        registry.end_render()

        with self.assertRaisesRegex(KeyError, "No active handler"):
            registry.dispatch(Event("click", 1, handler_id, {}))

    def test_registry_rejects_non_callable_handlers(self):
        registry = EventRegistry()
        with self.assertRaisesRegex(TypeError, "must be callable"):
            registry.register("not callable")


if __name__ == "__main__":
    unittest.main()
