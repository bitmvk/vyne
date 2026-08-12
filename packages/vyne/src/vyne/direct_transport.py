"""Direct Chaquopy transport for Android.

Python remains the commit coordinator. Each logical commit is serialized to
one JSON document and handed to a single Java entry point, which decodes it
with org.json and applies the completed transaction on the UI thread. There
is no message envelope, opcode table, or binary codec on this path.
"""

from __future__ import annotations

import json
from typing import Any

from vyne.protocol import JsonObject, _to_json_compatible


class DirectTransport:
    """Publish logical commits through one JSON bridge call per commit."""

    # Kotlin's transaction builder and Renderer preflight validate the direct
    # operation stream before it mutates the accepted native tree. The runtime
    # can therefore skip the legacy JSON-envelope validation pass.
    preflights_commits = True

    def __init__(self, host: Any, session_id: str | None = None) -> None:
        from uuid import uuid4

        self.host = host
        self.session_id = session_id if session_id is not None else uuid4().hex
        self.send_count = 0
        self._latest: JsonObject | None = None
        self._session_published = False

    @property
    def latest(self) -> JsonObject | None:
        return self._latest

    def send(self, message: JsonObject) -> None:
        # Publish the session identity on the host BEFORE the first commit
        # so native receipts carry the real session id (design-pattern #1).
        if not self._session_published:
            setter = getattr(self.host, "setSessionId", None)
            if setter is not None:
                setter(self.session_id)
            self._session_published = True
        if message.get("type") != "commit":
            raise ValueError("DirectTransport only accepts commit messages")

        revision = message.get("revision")
        if type(revision) is not int:
            raise TypeError("Direct commit revision must be an integer")

        # One JNI crossing per commit: the whole ordered op stream travels as
        # one JSON document, decoded by org.json inside the same host call.
        # Commits normally contain plain containers, but extension props may
        # still carry immutable Mapping/Sequence implementations.
        payload = json.dumps(
            {
                "revision": revision,
                "ops": _to_json_compatible(message.get("ops", [])),
            },
            separators=(",", ":"),
            allow_nan=False,
        )
        self.host.commitJson(payload)
        self.send_count += 1
        self._latest = message
