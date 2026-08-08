"""Extension protocol validation tests (EXT-03).

Logical commit/event validation consults the merged registry: extension
kinds and props pass op validation; extension events pass event validation
with open payloads (no payload specs declared).
"""

from __future__ import annotations

import unittest

from vyne.extensions_registry import sync_from_host
from vyne.protocol import validate_message

KINDS = {
    "TimerRing": (["progress", "ring_color"], ["complete"], [False]),
}


def setUpModule() -> None:
    sync_from_host(KINDS)


def tearDownModule() -> None:
    sync_from_host({})


def _commit(ops: list[dict], **fields) -> dict:
    message = {"type": "commit", "revision": 1, "ops": ops}
    message.update(fields)
    return message


class ExtensionOperationValidationTests(unittest.TestCase):
    def test_create_extension_kind_valid(self):
        validate_message(_commit([{"op": "create", "id": 1, "kind": "TimerRing"}]))

    def test_create_unknown_kind_rejected(self):
        with self.assertRaisesRegex(ValueError, "not a canonical primitive"):
            validate_message(_commit([{"op": "create", "id": 1, "kind": "Gadget"}]))

    def test_set_prop_extension_prop_valid(self):
        validate_message(_commit([
            {"op": "create", "id": 1, "kind": "TimerRing"},
            {"op": "set_prop", "id": 1, "name": "progress", "value": 0.5},
        ]))

    def test_set_prop_unknown_prop_rejected(self):
        with self.assertRaisesRegex(ValueError, "not a canonical property"):
            validate_message(_commit([
                {"op": "create", "id": 1, "kind": "TimerRing"},
                {"op": "set_prop", "id": 1, "name": "nope", "value": 1},
            ]))

    def test_set_props_mixed_extension_and_generic(self):
        validate_message(_commit([
            {"op": "create", "id": 1, "kind": "TimerRing"},
            {"op": "set_props", "id": 1, "props": {"progress": 1.0, "width": 50}},
        ]))

    def test_listen_extension_event_valid(self):
        validate_message(_commit([
            {"op": "create", "id": 1, "kind": "TimerRing"},
            {"op": "listen", "id": 1, "event": "complete", "handler": 7},
        ]))

    def test_listen_unknown_event_rejected(self):
        with self.assertRaisesRegex(ValueError, "not canonical"):
            validate_message(_commit([
                {"op": "create", "id": 1, "kind": "TimerRing"},
                {"op": "listen", "id": 1, "event": "mystery", "handler": 7},
            ]))


class ExtensionEventMessageTests(unittest.TestCase):
    def _event(self, event_type: str, payload: dict) -> dict:
        return {
            "type": "event", "seq": 1, "target": 1, "event": event_type,
            "handler": 7, "payload": payload,
        }

    def test_extension_event_with_open_payload_valid(self):
        validate_message(self._event("complete", {"finished": True, "n": 3}))

    def test_unknown_event_type_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown event type"):
            validate_message(self._event("mystery", {}))

    def test_core_event_payload_validation_unchanged(self):
        with self.assertRaisesRegex(ValueError, "Unexpected payload field"):
            validate_message(self._event("click", {"bogus": 1}))


if __name__ == "__main__":
    unittest.main()
