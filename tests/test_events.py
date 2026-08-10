"""Caveat tests for the event system and per-mount refs.

EventRegistry handler mapping, zero-arg handler wrapping, delivery
policies, Event construction from wire messages, and the Ref/ViewHandle
lifecycle contract.
"""

from __future__ import annotations

import unittest

from vyne.events import (
    Event,
    EventRegistry,
    event_delivery,
    latest,
)
from vyne.refs import Ref, ViewHandle


class EventDeliveryTests(unittest.TestCase):
    def test_latest_requires_callable(self):
        with self.assertRaises(TypeError):
            latest("not-callable")  # type: ignore[arg-type]

    def test_event_delivery_unwraps(self):
        def handler(event):
            return None

        self.assertEqual(event_delivery(handler), (handler, "all"))
        wrapped = latest(handler)
        callback, delivery = event_delivery(wrapped)
        self.assertIs(callback, handler)
        self.assertEqual(delivery, "latest")

    def test_event_delivery_is_transparently_callable(self):
        wrapped = latest(lambda event: event.target)
        self.assertEqual(wrapped(type("E", (), {"target": 5})()), 5)


class EventConstructionTests(unittest.TestCase):
    def test_from_message_defaults(self):
        event = Event.from_message({
            "type": "event", "target": 3, "event": "click", "handler": 9,
        })
        self.assertEqual(event.payload, {})
        self.assertIsNone(event.sequence)
        self.assertEqual(event.target, 3)

    def test_from_message_rejects_non_object_payload(self):
        with self.assertRaisesRegex(TypeError, "JSON object"):
            Event.from_message({
                "type": "event", "target": 1, "event": "click",
                "handler": 1, "payload": [1],
            })

    def test_get_reads_payload_with_default(self):
        event = Event(name="text_change", target=1, handler=1,
                      payload={"text": "hi"})
        self.assertEqual(event.get("text"), "hi")
        self.assertIsNone(event.get("missing"))
        self.assertEqual(event.get("missing", 42), 42)


class EventRegistryTests(unittest.TestCase):
    def test_register_dispatches_with_event_argument(self):
        registry = EventRegistry()
        received: list[Event] = []
        handler_id = registry.register(received.append)
        registry.dispatch(Event(name="click", target=1, handler=handler_id,
                                payload={}))
        self.assertEqual(len(received), 1)

    def test_zero_arg_handlers_are_wrapped(self):
        registry = EventRegistry()
        calls: list[str] = []
        handler_id = registry.register(lambda: calls.append("fired"))
        registry.dispatch(Event(name="click", target=1, handler=handler_id,
                                payload={}))
        self.assertEqual(calls, ["fired"])

    def test_varargs_handlers_pass_through(self):
        registry = EventRegistry()
        received: list[Event] = []
        handler_id = registry.register(lambda *args: received.append(args[0]))
        registry.dispatch(Event(name="click", target=1, handler=handler_id,
                                payload={}))
        self.assertEqual(len(received), 1)

    def test_register_rejects_non_callable(self):
        registry = EventRegistry()
        with self.assertRaises(TypeError):
            registry.register(42)  # type: ignore[arg-type]

    def test_dispatch_unknown_handler_raises(self):
        registry = EventRegistry()
        with self.assertRaises(KeyError):
            registry.dispatch(Event(name="click", target=1, handler=999,
                                    payload={}))

    def test_update_refreshes_closure(self):
        registry = EventRegistry()
        values: list[int] = []
        handler_id = registry.register(lambda e: values.append(1))
        registry.update(handler_id, lambda e: values.append(2))
        registry.dispatch(Event(name="click", target=1, handler=handler_id,
                                payload={}))
        self.assertEqual(values, [2])

    def test_update_rejects_non_callable(self):
        registry = EventRegistry()
        handler_id = registry.register(lambda e: None)
        with self.assertRaises(TypeError):
            registry.update(handler_id, None)  # type: ignore[arg-type]

    def test_unregister_removes_and_is_idempotent(self):
        registry = EventRegistry()
        handler_id = registry.register(lambda e: None)
        registry.unregister(handler_id)
        registry.unregister(handler_id)  # second call is a no-op
        self.assertNotIn(handler_id, registry.handler_ids)

    def test_clear_resets_ids(self):
        registry = EventRegistry()
        registry.register(lambda e: None)
        registry.clear()
        self.assertEqual(registry.handler_ids, frozenset())
        self.assertEqual(registry.register(lambda e: None), 1)

    def test_clone_is_detached_with_shared_allocator_state(self):
        registry = EventRegistry()
        handler_id = registry.register(lambda e: 1)
        clone = registry.clone()
        # Same handler ids and next id, but updates stay local.
        self.assertEqual(clone.handler_ids, registry.handler_ids)
        clone.update(handler_id, lambda e: 2)
        original_event = Event(name="click", target=1, handler=handler_id,
                               payload={})
        # Original registry still holds the first closure.
        registry.dispatch(original_event)  # would raise if missing
        new_id = clone.register(lambda e: 3)
        self.assertNotIn(new_id, registry.handler_ids)


class RefLifecycleTests(unittest.TestCase):
    def test_unmounted_ref_has_no_current(self):
        ref = Ref()
        self.assertIsNone(ref.current)
        self.assertIn("unmounted", repr(ref))

    def test_attach_then_invalidate(self):
        ref = Ref()
        handle = ViewHandle(7, "Box")
        ref.attach(handle)
        self.assertIs(ref.current, handle)
        self.assertTrue(handle.valid)
        ref.invalidate()
        self.assertIsNone(ref.current)
        self.assertFalse(handle.valid)  # staleness propagates to the handle

    def test_double_attach_rejected(self):
        ref = Ref()
        ref.attach(ViewHandle(1, "Box"))
        with self.assertRaisesRegex(RuntimeError, "already attached"):
            ref.attach(ViewHandle(2, "Text"))

    def test_invalidate_without_attach_is_safe(self):
        Ref().invalidate()

    def test_view_handle_exposes_identity(self):
        handle = ViewHandle(11, "Text")
        self.assertEqual(handle.node_id, 11)
        self.assertEqual(handle.kind, "Text")
        self.assertTrue(handle.valid)
        handle._invalidate()
        self.assertIn("stale", repr(handle))


if __name__ == "__main__":
    unittest.main()
