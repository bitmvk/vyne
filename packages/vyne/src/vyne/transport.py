"""Logical transports emitted by the Python runtime.

The transport layer is deliberately thin.  The Runtime calls ``transport.send()``
with a logical message dict; the transport decides how to deliver it.

- ``MemoryTransport`` stores messages in a list — used by tests/demos.
  When given a runtime reference, it auto-acknowledges every commit
  so the recovery state machine advances (CORE-02).
The Transport Protocol class defines the minimal interface that any custom
backend must satisfy.
"""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

from vyne.protocol import JsonObject, MSG_COMMIT

if TYPE_CHECKING:
    from vyne.runtime import Runtime

class Transport(Protocol):
    def send(self, message: JsonObject) -> None:
        """Send a framework protocol message."""


class MemoryTransport:
    """In-memory transport used by tests, demos, and early host integration.

    When ``runtime`` is provided, every commit is auto-acknowledged so the
    recovery state machine advances from AWAITING_APPLY to SYNCED without
    requiring a real native round-trip (CORE-02).
    """

    def __init__(
        self,
        *,
        keep_history: bool = True,
        runtime: Runtime | None = None,
    ) -> None:
        self.keep_history = keep_history
        self.messages: list[JsonObject] = []
        self.send_count = 0
        self._latest: JsonObject | None = None
        self._runtime: Runtime | None = runtime

    def send(self, message: JsonObject) -> None:
        self.send_count += 1
        self._latest = message
        if self.keep_history:
            self.messages.append(message)
        # Auto-acknowledge commits so the recovery state machine advances.
        # In production, the native side sends a __vyne_system__ event with
        # native_apply_result; in tests we simulate that here.
        if self._runtime is not None and message.get("type") == MSG_COMMIT:
            revision = message.get("revision")
            if revision is not None:
                self._runtime.acknowledge_native_apply(revision)

    @property
    def latest(self) -> JsonObject | None:
        return self._latest

    def set_runtime(self, runtime: Runtime) -> None:
        """Associate a Runtime for auto-acknowledgement (CORE-02)."""
        self._runtime = runtime
