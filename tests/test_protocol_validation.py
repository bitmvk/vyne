"""Caveat tests for logical commit and event validation.

This suite covers envelopes, operations, events, receipts, and values which
cross the direct Python/Kotlin bridge.
"""

from __future__ import annotations

import math
import unittest

from vyne.protocol import (
    ensure_bridge_value,
    error_commit,
    validate_message,
)


def _commit(ops: list[dict], **fields) -> dict:
    message = {"type": "commit", "revision": 1, "ops": ops}
    message.update(fields)
    return message


class EnvelopeValidationTests(unittest.TestCase):
    def test_missing_or_non_string_type(self):
        with self.assertRaises(TypeError):
            validate_message({})
        with self.assertRaises(TypeError):
            validate_message({"type": 7})

    def test_unknown_message_type(self):
        with self.assertRaisesRegex(ValueError, "Unknown protocol message type"):
            validate_message({"type": "teleport"})

    def test_commit_requires_revision(self):
        with self.assertRaisesRegex(TypeError, "revision"):
            validate_message({"type": "commit", "ops": []})

    def test_commit_revision_rules(self):
        # bool is not an int for protocol purposes
        with self.assertRaises(TypeError):
            validate_message(_commit([], revision=True))
        # Only -1 is allowed as a negative (fallback) revision
        with self.assertRaisesRegex(ValueError, "-1 fallback"):
            validate_message(_commit([], revision=-2))
        validate_message(_commit([], revision=-1))  # fallback marker is valid
        validate_message(_commit([], revision=0))

    def test_commit_rejects_unknown_envelope_fields(self):
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            validate_message(_commit([], comment="hello"))

    def test_origin_event_seq_must_be_non_negative_int(self):
        with self.assertRaises(TypeError):
            validate_message(_commit([], origin_event_seq=-1))
        with self.assertRaises(TypeError):
            validate_message(_commit([], origin_event_seq="3"))
        validate_message(_commit([], origin_event_seq=3))

    def test_ops_must_be_list_of_objects(self):
        with self.assertRaisesRegex(TypeError, "list"):
            validate_message({"type": "commit", "revision": 1, "ops": "x"})
        with self.assertRaisesRegex(TypeError, "object"):
            validate_message(_commit([42]))

    def test_events_envelope_rules(self):
        with self.assertRaisesRegex(TypeError, "list"):
            validate_message({"type": "events", "events": {}})
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            validate_message({"type": "events", "events": [], "extra": 1})
        with self.assertRaisesRegex(TypeError, "object"):
            validate_message({"type": "events", "events": [None]})


class OperationValidationTests(unittest.TestCase):
    def test_op_name_must_be_string(self):
        with self.assertRaises(TypeError):
            validate_message(_commit([{"op": 3, "id": 1}]))

    def test_unknown_op_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown operation"):
            validate_message(_commit([{"op": "fly", "id": 1}]))

    def test_scroll_to_command_is_strict(self):
        valid = {
            "op": "scroll_to",
            "id": 4,
            "offset_x": 0.0,
            "offset_y": 120.5,
            "animated": True,
        }
        validate_message(_commit([valid]))

        for changes in (
            {"id": 0},
            {"offset_x": -1},
            {"offset_y": float("inf")},
            {"animated": 1},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises((TypeError, ValueError)):
                    validate_message(_commit([{**valid, **changes}]))

    def test_removed_legacy_anim_ops_rejected(self):
        """anim_start / anim_cancel are no longer part of the protocol."""
        with self.assertRaisesRegex(ValueError, "unknown operation"):
            validate_message(_commit([
                {"op": "anim_start", "id": 1, "view": 1, "prop": "alpha",
                 "to": 1.0, "duration": 300, "easing": "ease_out"},
            ]))
        with self.assertRaisesRegex(ValueError, "unknown operation"):
            validate_message(_commit([{"op": "anim_cancel", "id": 1}]))

    def test_missing_required_fields(self):
        with self.assertRaisesRegex(ValueError, "missing fields"):
            validate_message(_commit([{"op": "create", "id": 1}]))
        with self.assertRaisesRegex(ValueError, "missing fields"):
            validate_message(_commit([{"op": "set_prop", "id": 1, "name": "text"}]))

    def test_unknown_extra_fields_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            validate_message(_commit([
                {"op": "create", "id": 1, "kind": "Text", "flavor": "spicy"},
            ]))

    def test_negative_and_oversized_ids_rejected(self):
        with self.assertRaises(ValueError):
            validate_message(_commit([{"op": "remove", "id": -1}]))
        with self.assertRaises(TypeError):
            validate_message(_commit([{"op": "remove", "id": 1.5}]))
        with self.assertRaisesRegex(ValueError, "maximum Android node id"):
            validate_message(_commit([{"op": "remove", "id": 2_147_483_648}]))

    def test_create_kind_must_be_canonical(self):
        with self.assertRaisesRegex(ValueError, "canonical primitive"):
            validate_message(_commit([{"op": "create", "id": 1, "kind": "View"}]))
        with self.assertRaisesRegex(ValueError, "canonical primitive"):
            validate_message(_commit([{"op": "create", "id": 1, "kind": "Column"}]))
        validate_message(_commit([{"op": "create", "id": 1, "kind": "Box"}]))

    def test_set_prop_name_must_be_canonical(self):
        with self.assertRaisesRegex(ValueError, "canonical property"):
            validate_message(_commit([
                {"op": "set_prop", "id": 1, "name": "made_up", "value": 1},
            ]))

    def test_set_prop_value_schema_validated(self):
        # opacity must be within 0..1
        with self.assertRaises(ValueError):
            validate_message(_commit([
                {"op": "set_prop", "id": 1, "name": "opacity", "value": 9.5},
            ]))

    def test_set_props_requires_object_with_known_props(self):
        with self.assertRaisesRegex(TypeError, "object"):
            validate_message(_commit([{"op": "set_props", "id": 1, "props": []}]))
        with self.assertRaisesRegex(ValueError, "unknown property"):
            validate_message(_commit([
                {"op": "set_props", "id": 1, "props": {"nope": 1}},
            ]))

    def test_listen_event_must_be_canonical(self):
        with self.assertRaisesRegex(ValueError, "canonical"):
            validate_message(_commit([
                {"op": "listen", "id": 1, "event": "explode", "handler": 1},
            ]))
        validate_message(_commit([
            {"op": "listen", "id": 1, "event": "click", "handler": 1},
        ]))

    def test_motion_op_field_rules(self):
        # Motion ops require a complete, self-consistent slot and spec.
        validate_message(_commit([{
            "op": "motion_set_target", "animation_id": 7,
            "slot_key": "view:1:prop:opacity", "node_id": 1,
            "property": "opacity", "targets": [0.5, 1.0],
            "spec_type": "spring",
            "stiffness": 380.0, "damping_ratio": 0.8,
            "rest_value_threshold": 0.01, "rest_velocity_threshold": 0.01,
            "retarget": "restart",
        }]))
        # but unknown fields are still rejected
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            validate_message(_commit([{
                "op": "motion_cancel", "animation_id": 7,
                "slot_key": "view:1:prop:opacity", "speed": 4,
            }]))

    def test_invalid_motion_identity_timeline_and_policy_are_rejected(self):
        valid = {
            "op": "motion_set_target",
            "animation_id": 1,
            "slot_key": "view:1:prop:opacity",
            "node_id": 1,
            "property": "opacity",
            "targets": [0.5],
            "spec_type": "tween",
            "duration_ms": 100,
            "easing": "linear",
            "retarget": "restart",
        }
        invalid_changes = (
            {"animation_id": 0},
            {"slot_key": "view:2:prop:opacity"},
            {"node_id": 0, "slot_key": "view:0:prop:opacity"},
            {"property": "text", "slot_key": "view:1:prop:text"},
            {"targets": []},
            {"targets": [float("nan")]},
            {"from_value": 1.5},
            {"duration_ms": -1},
            {"easing": "platform_default"},
            {"retarget": "race"},
        )
        for changes in invalid_changes:
            with self.subTest(changes=changes):
                with self.assertRaises((TypeError, ValueError)):
                    validate_message(_commit([{**valid, **changes}]))


class EventValidationTests(unittest.TestCase):
    def _event(self, **fields) -> dict:
        event = {
            "type": "event", "target": 1, "event": "click",
            "handler": 1, "payload": {},
        }
        event.update(fields)
        return event

    def test_event_envelope_rules(self):
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            validate_message(self._event(extra=1))
        # Batch entries must be events, not other message types.
        with self.assertRaisesRegex(ValueError, "type 'event'"):
            validate_message({"type": "events", "events": [
                {"type": "commit", "target": 1, "event": "click",
                 "handler": 1, "payload": {}},
            ]})

    def test_event_ids_validated(self):
        with self.assertRaises(ValueError):
            validate_message(self._event(target=-1))
        with self.assertRaises(TypeError):
            validate_message(self._event(handler="x"))
        with self.assertRaises(ValueError):
            validate_message(self._event(seq=-1))

    def test_event_payload_must_be_object(self):
        with self.assertRaisesRegex(TypeError, "object"):
            validate_message(self._event(payload="text"))

    def test_unknown_event_type_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown event type"):
            validate_message(self._event(event="explode"))

    def test_unexpected_payload_field_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unexpected payload field"):
            validate_message(self._event(payload={"surprise": True}))

    def test_payload_field_specs_validated(self):
        # text_change carries a string "text"
        validate_message(self._event(
            event="text_change", payload={"text": "hello"},
        ))
        with self.assertRaises(TypeError):
            validate_message(self._event(
                event="text_change", payload={"text": 42},
            ))

    def test_internal_list_metric_payloads_are_strict(self):
        validate_message(self._event(
            event="layout_metrics",
            payload={"x": 0.0, "y": 20.0, "width": 100.0, "height": 40.0},
        ))
        validate_message(self._event(
            event="scroll_metrics",
            payload={
                "offset_x": 0.0,
                "offset_y": 120.0,
                "viewport_width": 360.0,
                "viewport_height": 640.0,
                "content_width": 360.0,
                "content_height": 5000.0,
                "velocity_x": 0.0,
                "velocity_y": 240.0,
                "projected_offset_x": 0.0,
                "projected_offset_y": 120.0,
                "event_time": 50,
            },
        ))

        with self.assertRaises(ValueError):
            validate_message(self._event(
                event="scroll_metrics",
                payload={
                    "offset_x": -1,
                    "offset_y": 0,
                    "viewport_width": 1,
                    "viewport_height": 1,
                    "content_width": 1,
                    "content_height": 1,
                    "velocity_x": 0,
                    "velocity_y": 0,
                    "projected_offset_x": 0,
                    "projected_offset_y": 0,
                    "event_time": 1,
                },
            ))
        with self.assertRaises(ValueError):
            validate_message(self._event(
                event="layout_metrics",
                payload={"x": 0, "y": 0, "width": 1, "height": -1},
            ))


class ReceiptValidationTests(unittest.TestCase):
    def _receipt(self, **payload_fields) -> dict:
        payload = {
            "type": "native_apply_result", "result": "ok",
            "revision": 1, "session": "s",
        }
        payload.update(payload_fields)
        return {
            "type": "event", "target": 0, "event": "__vyne_system__",
            "handler": 0, "payload": payload,
        }

    def test_valid_results_accepted(self):
        for result in ("ok", "rejected_known", "verified_rollback",
                       "partial", "unknown"):
            with self.subTest(result=result):
                validate_message(self._receipt(result=result))

    def test_invalid_receipts_rejected(self):
        with self.assertRaisesRegex(ValueError, "apply result"):
            validate_message(self._receipt(result="maybe"))
        with self.assertRaisesRegex(ValueError, "system event"):
            validate_message(self._receipt(type="something_else"))
        with self.assertRaises(ValueError):
            validate_message(self._receipt(revision=-1))

    def test_animation_lifecycle_system_event_validation(self):
        event = {
            "type": "event",
            "seq": 8,
            "target": 1,
            "event": "__vyne_system__",
            "handler": 0,
            "payload": {
                "type": "animation_lifecycle",
                "animation_id": 4,
                "status": "cancelled",
                "node_id": 1,
                "property": "opacity",
                "reason": "replaced",
            },
        }
        validate_message(event)

        for field, value in (
            ("animation_id", 0),
            ("status", "running"),
            ("node_id", 0),
            ("property", ""),
            ("reason", 4),
        ):
            with self.subTest(field=field):
                invalid = {
                    **event,
                    "payload": {**event["payload"], field: value},
                }
                with self.assertRaises((TypeError, ValueError)):
                    validate_message(invalid)
        with self.assertRaises(TypeError):
            validate_message(self._receipt(session=""))
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            validate_message(self._receipt(extra="field"))


class BridgeValueTests(unittest.TestCase):
    def test_non_finite_numbers_rejected(self):
        for bad in (math.nan, math.inf, -math.inf):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(TypeError, "native bridge"):
                    ensure_bridge_value(bad, prop_name="opacity")

    def test_unserializable_types_rejected(self):
        for bad in ({1, 2}, object(), b"bytes"):
            with self.subTest(type=type(bad).__name__):
                with self.assertRaisesRegex(TypeError, "native bridge"):
                    ensure_bridge_value(bad, prop_name="width")

    def test_style_and_frozen_values_can_cross_bridge(self):
        from vyne.style import Style
        from vyne.values import FrozenMap
        ensure_bridge_value(Style(text_color="#123456"), prop_name="style")
        ensure_bridge_value(
            FrozenMap([("a", (1, 2)), ("b", FrozenMap([("c", "x")]))]),
            prop_name="draw",
        )
        with self.assertRaisesRegex(TypeError, "native bridge"):
            ensure_bridge_value({"value": float("nan")}, prop_name="value")

    def test_nested_values_checked_recursively(self):
        with self.assertRaisesRegex(TypeError, "native bridge"):
            ensure_bridge_value({"a": [1, {"b": math.nan}]}, prop_name="draw")


class ErrorCommitTests(unittest.TestCase):
    def test_error_commit_is_schema_valid(self):
        commit = error_commit("boom", revision=3, prefix="Error: ")
        validate_message(commit)
        texts = [
            op["props"]["text"] for op in commit["ops"]
            if op["op"] == "set_props" and "text" in op.get("props", {})
        ]
        self.assertEqual(texts, ["Error: boom"])
        kinds = [op["kind"] for op in commit["ops"] if op["op"] == "create"]
        self.assertEqual(kinds, ["Layout", "Text"])

    def test_error_commit_carries_revision_and_prefix(self):
        commit = error_commit("failed", revision=7, prefix="Error: ")
        self.assertEqual(commit["revision"], 7)
        self.assertEqual(commit["ops"][-2]["props"], {"text": "Error: failed"})


if __name__ == "__main__":
    unittest.main()
