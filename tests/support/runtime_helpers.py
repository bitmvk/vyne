"""Shared helpers for Runtime/scheduler/reconciliation tests.

Consolidates the transport, listener/Event construction, commit-introspection,
native-event dispatch, and coordinator reserve helpers that many test modules
defined identically.  Tests import with alias names so call sites stay stable:

    from tests.support.runtime_helpers import (
        SilentTransport,
        find_listeners,
        props_for_kind,
        set_props,
        dispatch_native_event,
        reserve,
        native_listener_event,
    )
"""

from __future__ import annotations

from typing import Any

from vyne.events import Event


class SilentTransport:
    """A transport that never auto-acknowledges (native stays silent)."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    @property
    def latest(self) -> dict[str, Any] | None:
        return self.messages[-1] if self.messages else None


def find_listeners(commit: dict[str, Any], event: str) -> list[dict[str, Any]]:
    """Return the listen operations for *event* in *commit*."""
    return [
        op
        for op in commit["ops"]
        if op.get("op") == "listen" and op.get("event") == event
    ]


def first_listener(
    commit: dict[str, Any], event: str = "click"
) -> dict[str, Any]:
    """Return the first listen operation for *event*.

    Raises StopIteration when no listener exists so the failure is loud.
    """
    return next(
        op
        for op in commit["ops"]
        if op.get("op") == "listen" and op.get("event") == event
    )


def props_for_kind(
    commit: dict[str, Any], kind: str
) -> list[dict[str, Any]]:
    """Return the set_props payloads applied to nodes of *kind*."""
    create_ops = {
        op["id"]: op["kind"]
        for op in commit["ops"]
        if op.get("op") == "create"
    }
    return [
        op["props"]
        for op in commit["ops"]
        if op.get("op") == "set_props" and create_ops.get(op["id"]) == kind
    ]


def set_props(commit: dict[str, Any], name: str) -> list[dict[str, Any]]:
    """Return the set_prop operations for one prop *name*."""
    return [
        op
        for op in commit["ops"]
        if op.get("op") == "set_prop" and op.get("name") == name
    ]


def dispatch_native_event(
    runtime: Any,
    listener: dict[str, Any],
    *,
    event: str = "click",
    seq: int = 1,
    payload: dict[str, Any] | None = None,
) -> None:
    """Dispatch one native event targeting *listener*."""
    runtime.dispatch_event({
        "type": "event",
        "seq": seq,
        "target": listener["id"],
        "event": event,
        "handler": listener["handler"],
        "payload": payload or {},
    })


def reserve(coordinator: Any, revision: int) -> None:
    """Complete the same provisional-send transition used by Runtime."""
    coordinator.reserve_send(revision)
    coordinator.finish_send(revision)


def native_listener_event(
    transport: Any, *, sequence: int = 1
) -> Event:
    """Build an Event for the first listen op in the latest commit."""
    listener = next(
        op
        for op in transport.latest["ops"]
        if op["op"].startswith("listen")
    )
    return Event(
        name=listener["event"],
        target=listener["id"],
        handler=listener["handler"],
        payload={},
        sequence=sequence,
    )
