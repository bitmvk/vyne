"""Notification-entry example — Python side.

Demonstrates the extension-owned notification entry pattern:

1. The Kotlin side (NotificationEntryExtension) builds the entry
   PendingIntent: stable requestCode identity (extras do not participate in
   PendingIntent identity), CLEAR_TOP|SINGLE_TOP flags, plain action/extras.
2. This module implements the persist-then-drain durability pattern: the
   pre_launch capture hook runs on every launch (cold and warm) before the
   render, so it can persist the entry FIRST and drain leftovers from a
   previous process lifetime AFTER — at-most-once framework delivery,
   extension-owned durability, idempotent by the stable entry key.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from vyne.launch import LaunchData

_logger = logging.getLogger("vyne.ext.notification_entry")

#: Notification actions this extension handles (developer-owned prefix).
ACTION_PREFIX = "notify."

#: Entries handled in this process lifetime (idempotency by stable key).
_handled_keys: set[str] = set()

_store_path: Path | None = None


def configure_store(path: Path | None) -> None:
    """Point the durable store at a writable location (tests override this)."""
    global _store_path
    _store_path = path


def _default_store_path() -> Path:
    from vyne.android import activity

    files_dir = activity().getFilesDir().getAbsolutePath()
    return Path(files_dir) / "notification_entry_entries.json"


def _load() -> list[dict]:
    path = _store_path or _default_store_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(entries: list[dict]) -> None:
    path = _store_path or _default_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(entries), encoding="utf-8")
    os.replace(temp, path)


def handle(entry: dict) -> None:
    """Extension logic for one notification entry (idempotent by key)."""
    key = entry.get("key")
    if key is None or key in _handled_keys:
        return
    _handled_keys.add(key)
    _logger.info(
        "notification_entry handled key=%s action=%s origin=%s",
        key,
        entry.get("action"),
        entry.get("origin"),
    )


def _key_from_uri(uri: str | None) -> str | None:
    """The helper stores the stable entryKey in the intent data URI."""
    if not uri or not uri.startswith("vyne://entry/"):
        return None
    from urllib.parse import unquote
    key = unquote(uri.removeprefix("vyne://entry/"))
    return key or None


def on_launch(context) -> None:
    """Capture function: call from the app's pre_launch hook.

    Persist first, then drain (at-least-once, idempotent by entry key).
    """
    launch = context.launch
    if launch.action is not None and launch.action.startswith(ACTION_PREFIX):
        entry = {
            "key": str(
                launch.extras.get("entry_key")
                or _key_from_uri(launch.uri)
                or launch.sequence
            ),
            "action": launch.action,
            "origin": launch.origin,
            "uri": launch.uri,
            "extras": dict(launch.extras),
        }
        pending = _load()
        pending.append(entry)
        _save(pending)
    for entry in _load():
        handle(entry)
    _save([])
