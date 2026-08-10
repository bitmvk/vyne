"""Notification-entry example tests (EXT-06).

The persist-then-drain durability pattern: pre_launch persists the entry
FIRST, then drains leftovers from a previous process lifetime; handling is
idempotent by the stable entry key.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vyne.extensions_registry import sync_from_host
from vyne.launch import LaunchData

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "extensions" / "notification_entry" / "python"))

import notification_entry as ext  # noqa: E402


class NotificationEntryDurabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        ext.configure_store(Path(self._tmp.name) / "entries.json")
        ext._handled_keys.clear()

    def tearDown(self) -> None:
        ext.configure_store(None)
        self._tmp.cleanup()
        sync_from_host({})

    def _launch(self, action: str, extras: dict | None = None, origin: str = "warm") -> LaunchData:
        return LaunchData(action=action, extras=extras or {}, origin=origin)

    def _context(self, launch: LaunchData) -> object:
        from types import SimpleNamespace

        return SimpleNamespace(launch=launch)

    def test_entry_persisted_then_handled(self):
        ext.on_launch(self._context(self._launch("notify.order", {"entry_key": "order_1", "id": 7}, "warm")))
        # Persisted BEFORE handling; the drain runs after.
        self.assertIn("order_1", ext._handled_keys)
        self.assertEqual([], ext._load())

    def test_leftover_from_previous_process_lifetime_is_drained(self):
        # Simulate a previous process lifetime: an entry persisted but the
        # process died before handling.
        store = Path(self._tmp.name) / "entries.json"
        store.write_text(
            '[{"key": "order_9", "action": "notify.order", "origin": "warm", "extras": {}}]',
            encoding="utf-8",
        )
        ext.on_launch(self._context(self._launch("notify.order", {"entry_key": "order_10"}, "warm")))
        self.assertIn("order_9", ext._handled_keys)
        self.assertIn("order_10", ext._handled_keys)
        self.assertEqual([], ext._load())

    def test_handling_is_idempotent_by_key(self):
        ext.on_launch(self._context(self._launch("notify.order", {"entry_key": "order_1"}, "warm")))
        ext.on_launch(self._context(self._launch("notify.order", {"entry_key": "order_1"}, "cold")))
        self.assertEqual(1, len(ext._handled_keys))

    def test_key_derived_from_helper_data_uri(self):
        # The Kotlin helper stores the stable key in the intent data URI.
        ext.on_launch(self._context(self._launch("notify.order", {"other": 1}, "warm").__class__(
            action="notify.order",
            uri="vyne://entry/order_99",
            extras={},
            origin="warm",
        )))
        self.assertIn("order_99", ext._handled_keys)

    def test_encoded_uri_key_roundtrips(self):
        import urllib.parse
        key = "order/99#a b"
        ext.on_launch(self._context(self._launch("notify.order", {}, "warm").__class__(
            action="notify.order",
            uri="vyne://entry/" + urllib.parse.quote(key, safe=""),
            extras={},
            origin="warm",
        )))
        self.assertIn(key, ext._handled_keys)

    def test_non_notification_launches_are_not_persisted(self):
        ext.on_launch(self._context(self._launch("android.intent.action.MAIN", {}, "cold")))
        self.assertEqual(set(), ext._handled_keys)
        self.assertEqual([], ext._load())


if __name__ == "__main__":
    unittest.main()
