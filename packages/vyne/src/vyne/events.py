"""Framework-side event objects and handler registry.

The EventRegistry maps protocol-safe handler IDs to Python callbacks.
Handler garbage collection is owned by the Runtime: candidate registries
are detached copies (``clone()``) and handler IDs whose listeners left
the accepted tree are unregistered during promotion.  When a user removes
an ``on_click`` handler from their tree, the old handler ID is freed and
won't fire on stale events.

Event handler wrapping: zero-argument handlers (``on_click=lambda: ...``) are
wrapped automatically so users don't need to accept an unused event parameter.
This is done once at registration time for efficiency.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from vyne.protocol import JsonObject


@dataclass(frozen=True)
class EventDelivery:
    """A callback annotated with a native event-delivery policy."""

    callback: Callable[..., Any]
    delivery: str

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Remain transparently callable for tests and component composition."""
        return self.callback(*args, **kwargs)


def latest(callback: Callable[..., Any]) -> EventDelivery:
    """Keep only the newest queued event for this handler.

    This is intended for high-frequency, replaceable events such as pointer
    movement.  A currently executing handler is never cancelled; while it is
    running, native delivery retains only the most recent pending event.
    """
    if not callable(callback):
        raise TypeError("latest() requires a callable event handler")
    return EventDelivery(callback=callback, delivery="latest")


def event_delivery(value: Any) -> tuple[Any, str]:
    """Return the underlying callback and delivery policy for an event prop."""
    if isinstance(value, EventDelivery):
        return value.callback, value.delivery
    return value, "all"


@dataclass(frozen=True)
class Event:
    """Event delivered from a native renderer to Python user code."""

    name: str
    target: int
    handler: int
    payload: JsonObject
    sequence: int | None = None

    @classmethod
    def from_message(cls, message: JsonObject) -> "Event":
        payload = message.get("payload")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise TypeError("Event payload must be a JSON object")
        return cls(
            name=str(message["event"]),
            target=int(message["target"]),
            handler=int(message["handler"]),
            payload=payload,
            sequence=message.get("seq"),
        )

    def get(self, name: str, default: Any = None) -> Any:
        """Safely access a payload field by name."""
        return self.payload.get(name, default)


class EventRegistry:
    """Maps protocol-safe handler IDs to Python callbacks.

    Candidate registries are detached copies created by ``clone()``;
    handler garbage collection is owned by the Runtime, which unregisters
    handler IDs whose listeners left the accepted tree.
    """

    def __init__(self) -> None:
        self._next_handler_id = 1
        self._handlers: dict[int, Callable[..., Any]] = {}

    def unregister(self, handler_id: int) -> None:
        """Remove a handler whose listener or native subtree was removed."""
        self._handlers.pop(handler_id, None)

    def clear(self) -> None:
        """Remove all registered handlers and reset ID counter."""
        self._handlers.clear()
        self._next_handler_id = 1

    def clone(self) -> "EventRegistry":
        """Return a detached candidate registry with identical allocator state."""
        candidate = EventRegistry()
        candidate._next_handler_id = self._next_handler_id
        candidate._handlers = dict(self._handlers)
        return candidate

    @property
    def handler_ids(self) -> frozenset[int]:
        return frozenset(self._handlers)

    def register(self, callback: Callable[..., Any]) -> int:
        if not callable(callback):
            raise TypeError("Event handlers must be callable")
        handler_id = self._next_handler_id
        self._next_handler_id += 1
        self._handlers[handler_id] = _wrap_handler(callback)
        return handler_id

    def update(self, handler_id: int, callback: Callable[..., Any]) -> None:
        if not callable(callback):
            raise TypeError("Event handlers must be callable")
        self._handlers[handler_id] = _wrap_handler(callback)

    def dispatch(self, event: Event) -> Any:
        handler = self._handlers.get(event.handler)
        if handler is None:
            raise KeyError(f"No active handler for id {event.handler}")
        return handler(event)


def _wrap_handler(handler: Callable[..., Any]) -> Callable[[Event], Any]:
    """Wrap a handler so zero-arg callables work as event handlers.

    Signature inspection is done once at registration time, not per event.
    If the handler has no positional parameters, it's wrapped in a lambda
    that discards the event argument.  Otherwise it's used as-is.
    """
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        return handler  # can't inspect, assume it accepts event

    has_positional_or_varargs = any(
        param.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        )
        for param in signature.parameters.values()
    )

    if has_positional_or_varargs:
        return handler
    else:
        return lambda event: handler()
