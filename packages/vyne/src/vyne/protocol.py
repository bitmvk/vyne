"""Logical Vyne commit and event model.

The protocol has two message types flowing in opposite directions:

  Python → Native:  "commit" messages carrying tree-patch operations
  Native → Python:  "event" (single) or "events" (batch) messages

Operations within a commit describe the full lifecycle of a view tree:
create, set props, insert/move/remove children, register listeners, and
start/cancel animations.  The native renderer applies them in order.

``listen_latest`` coalesces only queued not-yet-dispatched events keyed by
``(target, event, handler, gesture/session id)``; it never cancels a
running handler.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from vyne.style import Style
from vyne.animations import encode_animated_values

JsonObject = dict[str, Any]

MSG_COMMIT = "commit"
MSG_EVENT = "event"
MSG_EVENTS = "events"

OP_CLEAR = "clear"
OP_CREATE = "create"
OP_INSERT_CHILD = "insert_child"
OP_LISTEN = "listen"
OP_LISTEN_LATEST = "listen_latest"
OP_MOTION_CANCEL = "motion_cancel"
OP_MOTION_SET_TARGET = "motion_set_target"
OP_MOVE_CHILD = "move_child"
OP_REMOVE = "remove"
OP_REMOVE_CHILD = "remove_child"
OP_REMOVE_PROP = "remove_prop"
OP_SET_PROP = "set_prop"
OP_SET_PROPS = "set_props"
OP_SCROLL_TO = "scroll_to"
OP_UNLISTEN = "unlisten"

EVENT_ACCESSIBILITY_PROGRESS = "accessibility_progress"
EVENT_CLICK = "click"
EVENT_EDITOR_ACTION = "editor_action"
EVENT_FOCUS_CHANGE = "focus_change"
EVENT_LONG_CLICK = "long_click"
EVENT_POINTER_CANCEL = "pointer_cancel"
EVENT_POINTER_DOWN = "pointer_down"
EVENT_POINTER_MOVE = "pointer_move"
EVENT_POINTER_UP = "pointer_up"
EVENT_TEXT_CHANGE = "text_change"


def error_commit(message: str, *, revision: int = -1, prefix: str = "") -> JsonObject:
    """Build the standard error-screen commit.

    Uses ``Layout(vertical)`` containing a ``Text`` — both valid v2 primitives.
    ``Column`` is not a registered native kind and must not be emitted.
    """
    text = f"{prefix}{message}" if prefix else message
    return {
        "type": MSG_COMMIT,
        "revision": revision,
        "ops": [
            {"op": OP_CLEAR, "id": 0},
            {"op": OP_CREATE, "id": 1, "kind": "Layout"},
            {"op": OP_SET_PROPS, "id": 1, "props": {"orientation": "vertical"}},
            {"op": OP_INSERT_CHILD, "parent": 0, "child": 1, "index": 0},
            {"op": OP_CREATE, "id": 2, "kind": "Text"},
            {"op": OP_SET_PROPS, "id": 2, "props": {"text": text}},
            {"op": OP_INSERT_CHILD, "parent": 1, "child": 2, "index": 0},
        ],
    }


def validate_message(message: JsonObject) -> None:
    """Validate one exact logical message before it affects framework state."""
    msg_type = message.get("type")
    if not isinstance(msg_type, str):
        raise TypeError(
            f"Protocol message 'type' must be a string, got {type(msg_type).__name__}"
        )

    if msg_type == MSG_COMMIT:
        _validate_commit_message(message)
    elif msg_type == MSG_EVENT:
        _validate_event_message(message)
    elif msg_type == MSG_EVENTS:
        events = message.get("events")
        if not isinstance(events, list):
            raise TypeError("events batch must be a list")
        _reject_unknown_fields(message, {"type", "events"}, "events envelope")
        for index, evt in enumerate(events):
            if not isinstance(evt, dict):
                raise TypeError(f"events[{index}] must be an object")
            _validate_event_message(evt)
    else:
        raise ValueError(f"Unknown protocol message type {msg_type!r}")


def _validate_commit_message(message: JsonObject) -> None:
    """Validate an exact commit envelope and every operation."""
    _reject_unknown_fields(
        message, {"type", "revision", "origin_event_seq", "ops"}, "commit"
    )
    if "revision" not in message:
        raise TypeError("Commit requires revision")
    revision = message["revision"]
    if type(revision) is not int:
        raise TypeError(
            f"Commit revision must be an integer, got {type(revision).__name__}"
        )
    if revision < -1:
        raise ValueError("Commit revision must be -1 fallback or non-negative")
    if "origin_event_seq" in message:
        origin = message["origin_event_seq"]
        if type(origin) is not int or origin < 0:
            raise TypeError("origin_event_seq must be a non-negative integer")
    ops = message.get("ops")
    if not isinstance(ops, list):
        raise TypeError("Commit ops must be a list")
    for index, op in enumerate(ops):
        if not isinstance(op, dict):
            raise TypeError(f"commit.ops[{index}] must be an object")
        _validate_operation(op, path=f"commit.ops[{index}]")


def _reject_unknown_fields(value: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{path} has unknown fields: {sorted(unknown)!r}")


def _non_negative_int(value: Any, *, path: str, node_id: bool = False) -> int:
    if type(value) is not int:
        raise TypeError(f"{path} must be an integer")
    if value < 0:
        raise ValueError(f"{path} must be non-negative")
    if node_id and value > 2_147_483_647:
        raise ValueError(f"{path} exceeds maximum Android node id")
    return value


@dataclass(frozen=True)
class _OperationSpec:
    """One immutable declaration of an operation's shape and semantics.

    ``required_fields`` / ``optional_fields`` define the envelope; the
    validator owns the semantic checks. The motion operations register
    their existing strict validators directly.
    """

    name: str
    required_fields: frozenset[str]
    optional_fields: frozenset[str]
    validator: Callable[[JsonObject, str], None]


def _simple_op_validator(
    name: str,
    required: frozenset[str],
    optional: frozenset[str],
    semantic: Callable[[JsonObject, str], None] | None = None,
) -> Callable[[JsonObject, str], None]:
    """Factory for the plain operations: envelope + numeric + semantics."""

    def validate(op: JsonObject, path: str) -> None:
        missing = required - set(op)
        if missing:
            raise ValueError(f"{path} missing fields: {sorted(missing)!r}")
        _reject_unknown_fields(op, required | optional, path)
        for field in ("id", "parent", "child"):
            if field in op:
                _non_negative_int(op[field], path=f"{path}.{field}", node_id=True)
        if "index" in op:
            _non_negative_int(op["index"], path=f"{path}.index")
        if "handler" in op:
            _non_negative_int(op["handler"], path=f"{path}.handler")
        if semantic is not None:
            semantic(op, path)

    return validate


def _semantic_create(op: JsonObject, path: str) -> None:
    from vyne.extensions_registry import resolve_kind
    if resolve_kind(op["kind"]) is None:
        raise ValueError(f"{path}.kind is not a canonical primitive")


def _semantic_prop(op: JsonObject, path: str) -> None:
    from vyne.extensions_registry import is_known_prop, resolve_prop
    prop_name = op["name"]
    if not isinstance(prop_name, str) or not is_known_prop(prop_name):
        raise ValueError(f"{path}.name is not a canonical property")
    if op["op"] == "set_prop":
        prop_spec = resolve_prop(prop_name)
        if prop_spec is not None:
            prop_spec.value.validate(op["value"], path=f"{path}.value")


def _semantic_set_props(op: JsonObject, path: str) -> None:
    from vyne.extensions_registry import is_known_prop, resolve_prop
    props = op["props"]
    if not isinstance(props, dict):
        raise TypeError(f"{path}.props must be an object")
    for prop_name, prop_value in props.items():
        if not isinstance(prop_name, str) or not is_known_prop(prop_name):
            raise ValueError(f"{path}.props has unknown property {prop_name!r}")
        prop_spec = resolve_prop(prop_name)
        if prop_spec is not None:
            prop_spec.value.validate(
                prop_value, path=f"{path}.props.{prop_name}"
            )


def _semantic_event(op: JsonObject, path: str) -> None:
    from vyne.extensions_registry import resolve_event
    if resolve_event(op["event"]) is None:
        raise ValueError(f"{path}.event is not canonical")


def _semantic_scroll_to(op: JsonObject, path: str) -> None:
    if op["id"] == 0:
        raise ValueError(f"{path}.id must be positive")
    for field in ("offset_x", "offset_y"):
        value = op[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"{path}.{field} must be finite and non-negative")
    if type(op["animated"]) is not bool:
        raise TypeError(f"{path}.animated must be a boolean")


def _validate_motion_operation(op: JsonObject, *, path: str) -> None:
    """Validate the complete ordered animation control-plane operation."""
    from vyne.motion import CanvasOpIdentity
    from vyne.spec.schema_v2 import ANIMATABLE_PROPS

    name = op["op"]
    if name in {"motion_cancel", "motion_driver_cancel"}:
        required = {"op", "slot_key", "animation_id"}
        if name == "motion_driver_cancel":
            required.add("driver_id")
        missing = required - set(op)
        if missing:
            raise ValueError(f"{path} missing fields: {sorted(missing)!r}")
        _reject_unknown_fields(op, required, path)
        animation_id = op["animation_id"]
        if type(animation_id) is not int or animation_id <= 0:
            raise ValueError(f"{path}.animation_id must be a positive integer")
        if not isinstance(op["slot_key"], str) or not op["slot_key"]:
            raise ValueError(f"{path}.slot_key must be a non-empty string")
        if name == "motion_driver_cancel":
            driver_id = op["driver_id"]
            if type(driver_id) is not int or driver_id <= 0:
                raise ValueError(f"{path}.driver_id must be a positive integer")
            if op["slot_key"] != f"driver:{driver_id}":
                raise ValueError(f"{path}.slot_key does not match driver_id")
        return

    common = {
        "op", "animation_id", "slot_key", "node_id", "property",
        "targets", "slot_id", "from_value", "spec_type", "retarget",
    }
    if name == "motion_driver_set_target":
        common.remove("slot_id")
        common.add("driver_id")
    tween = {"duration_ms", "easing"}
    spring = {
        "stiffness", "damping_ratio",
        "rest_value_threshold", "rest_velocity_threshold",
    }
    spec_type = op.get("spec_type")
    if spec_type == "tween":
        allowed = common | tween
    elif spec_type == "spring":
        allowed = common | spring
    else:
        raise ValueError(f"{path}.spec_type must be 'tween' or 'spring'")
    required = allowed - {"slot_id", "from_value"}
    missing = required - set(op)
    if missing:
        raise ValueError(f"{path} missing fields: {sorted(missing)!r}")
    _reject_unknown_fields(op, allowed, path)

    animation_id = op["animation_id"]
    if type(animation_id) is not int or animation_id <= 0:
        raise ValueError(f"{path}.animation_id must be a positive integer")
    node_id = _non_negative_int(
        op["node_id"], path=f"{path}.node_id", node_id=True
    )
    if node_id == 0:
        raise ValueError(f"{path}.node_id must be positive")
    property_name = op["property"]
    if not isinstance(property_name, str) or not property_name:
        raise ValueError(f"{path}.property must be a non-empty string")
    driver_operation = name == "motion_driver_set_target"
    driver_id = op.get("driver_id")
    if driver_operation:
        if type(driver_id) is not int or driver_id <= 0:
            raise ValueError(f"{path}.driver_id must be a positive integer")
        if op["slot_key"] != f"driver:{driver_id}":
            raise ValueError(f"{path}.slot_key does not match driver_id")
    slot_id = op.get("slot_id")
    if slot_id is not None and (
        not isinstance(slot_id, str) or not slot_id
    ):
        raise ValueError(f"{path}.slot_id must be a non-empty string or null")
    if not driver_operation:
        expected_slot = (
            f"view:{node_id}:slot:{slot_id}:{property_name}"
            if slot_id is not None
            else f"view:{node_id}:prop:{property_name}"
        )
        if op["slot_key"] != expected_slot:
            raise ValueError(f"{path}.slot_key does not match its slot fields")

        if slot_id is None:
            if property_name not in ANIMATABLE_PROPS:
                raise ValueError(f"{path}.property is not animatable")
        else:
            canvas_fields = {
                field
                for fields in CanvasOpIdentity.animatable_fields().values()
                for field in fields
            }
            if property_name not in canvas_fields:
                raise ValueError(f"{path}.property is not an animatable Canvas field")

    targets = op["targets"]
    if not isinstance(targets, list) or not targets:
        raise ValueError(f"{path}.targets must be a non-empty list")
    for index, value in enumerate(targets):
        if (
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ValueError(f"{path}.targets[{index}] must be finite")
    if not driver_operation and property_name in {"opacity", "trim_start", "trim_end"} and any(
        not 0 <= value <= 1 for value in targets
    ):
        raise ValueError(f"{path}.targets are outside the {property_name} domain")
    if not driver_operation and property_name in {
        "elevation", "width", "height", "radius", "r", "stroke_width",
    } and any(value < 0 for value in targets):
        raise ValueError(f"{path}.targets must be non-negative")
    from_value = op.get("from_value")
    if from_value is not None and (
        not isinstance(from_value, int | float)
        or isinstance(from_value, bool)
        or not math.isfinite(from_value)
    ):
        raise ValueError(f"{path}.from_value must be finite or null")
    domain_values = targets if from_value is None else [*targets, from_value]
    if not driver_operation and property_name in {"opacity", "trim_start", "trim_end"} and any(
        not 0 <= value <= 1 for value in domain_values
    ):
        raise ValueError(
            f"{path}.from_value is outside the {property_name} domain"
        )
    if not driver_operation and property_name in {
        "elevation", "width", "height", "radius", "r", "stroke_width",
    } and any(value < 0 for value in domain_values):
        raise ValueError(f"{path}.from_value must be non-negative")
    if op["retarget"] not in {
        "restart", "maintain_velocity", "snap_to_end", "ignore",
    }:
        raise ValueError(f"{path}.retarget is invalid")

    if spec_type == "tween":
        duration = op["duration_ms"]
        if type(duration) is not int or duration < 0:
            raise ValueError(f"{path}.duration_ms must be non-negative")
        if op["easing"] not in {
            "linear", "ease_in", "ease_out", "ease_in_out",
            "overshoot", "bounce",
        }:
            raise ValueError(f"{path}.easing is invalid")
        return

    for field in ("stiffness", "damping_ratio"):
        value = op[field]
        if (
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(f"{path}.{field} must be positive and finite")
    for field in ("rest_value_threshold", "rest_velocity_threshold"):
        value = op[field]
        if (
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"{path}.{field} must be non-negative and finite")


def _validate_event_message(event: JsonObject) -> None:
    """Validate an exact event envelope against EventSpec payload metadata."""
    from vyne.extensions_registry import resolve_event

    _reject_unknown_fields(
        event, {"type", "seq", "target", "event", "handler", "payload"}, "event"
    )
    if event.get("type") != MSG_EVENT:
        raise ValueError("Event entry must have type 'event'")
    event_type = event.get("event")
    if not isinstance(event_type, str):
        raise TypeError("Event 'event' field must be a string")

    target = _non_negative_int(event.get("target"), path="event.target", node_id=True)
    handler = _non_negative_int(event.get("handler"), path="event.handler")
    del target, handler
    if "seq" in event:
        _non_negative_int(event["seq"], path="event.seq")

    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise TypeError("Event payload must be an object")

    if event_type == "__vyne_system__":
        if payload.get("type") == "native_apply_result":
            _validate_receipt_payload(payload)
        elif payload.get("type") == "animation_lifecycle":
            _validate_animation_lifecycle_payload(payload)
        elif payload.get("type") == "app_state":
            _validate_app_state_payload(payload)
        else:
            raise ValueError("Unknown system event payload")
        return

    spec = resolve_event(event_type)
    if spec is None:
        raise ValueError(f"Unknown event type {event_type!r}")

    if spec.open_payload:
        # Extension events declare no payload fields: the payload is an
        # open bridge-safe dict owned by the extension.
        return

    # Validate payload fields against their ValueSpecs.
    for field_name, value_spec in spec.payload_specs.items():
        if field_name in payload:
            value_spec.validate(
                payload[field_name],
                path=f"event.{event_type}.payload.{field_name}",
            )

    # Reject unexpected payload fields not declared in the spec.
    for field_name in payload:
        if field_name not in spec.payload_fields:
            raise ValueError(
                f"Unexpected payload field {field_name!r} in event {event_type!r}"
            )


def _validate_receipt_payload(payload: JsonObject) -> None:
    _reject_unknown_fields(
        payload, {"type", "result", "revision", "session"}, "apply receipt"
    )
    if payload.get("type") != "native_apply_result":
        raise ValueError("Unknown system event payload")
    result = payload.get("result")
    if result not in {"ok", "rejected_known", "verified_rollback", "partial", "unknown"}:
        raise ValueError(f"Unknown native apply result {result!r}")
    _non_negative_int(payload.get("revision"), path="receipt.revision")
    session = payload.get("session")
    if not isinstance(session, str) or not session:
        raise TypeError("receipt.session must be a non-empty string")


def _validate_app_state_payload(payload: JsonObject) -> None:
    _reject_unknown_fields(payload, {"type", "state"}, "app state")
    if payload.get("type") != "app_state":
        raise ValueError("Unknown system event payload")
    state = payload.get("state")
    if state not in {"active", "inactive", "background"}:
        raise ValueError(f"Unknown app state {state!r}")


def _validate_animation_lifecycle_payload(payload: JsonObject) -> None:
    _reject_unknown_fields(
        payload,
        {
            "type", "animation_id", "status", "node_id", "property", "reason",
        },
        "animation lifecycle",
    )
    animation_id = payload.get("animation_id")
    if type(animation_id) is not int or animation_id <= 0:
        raise ValueError("animation lifecycle id must be positive")
    node_id = _non_negative_int(
        payload.get("node_id"),
        path="animation lifecycle.node_id",
        node_id=True,
    )
    if node_id == 0:
        raise ValueError("animation lifecycle node_id must be positive")
    if payload.get("status") not in {"completed", "cancelled"}:
        raise ValueError("animation lifecycle status is invalid")
    property_name = payload.get("property")
    if not isinstance(property_name, str) or not property_name:
        raise TypeError("animation lifecycle property must be non-empty")
    reason = payload.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise TypeError("animation lifecycle reason must be a string or null")


def ensure_bridge_value(value: Any, *, prop_name: str) -> None:
    """Fail early if a prop cannot cross the direct Python/Kotlin bridge."""
    try:
        bridge_value = value.to_props() if isinstance(value, Style) else value
        _validate_bridge_value(encode_animated_values(bridge_value), seen=set())
    except (TypeError, ValueError, RecursionError) as exc:
        raise TypeError(f"Prop {prop_name!r} cannot cross the native bridge") from exc


def _validate_bridge_value(value: Any, *, seen: set[int]) -> None:
    """Validate the values supported by the typed Python/Kotlin boundary."""
    from vyne.values import FrozenMap

    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int):
        if -(1 << 63) <= value < (1 << 63):
            return
        raise ValueError("Integer is outside the signed 64-bit bridge range")
    if isinstance(value, float):
        if math.isfinite(value):
            return
        raise ValueError("Non-finite numbers cannot cross the native bridge")

    is_mapping = isinstance(value, (Mapping, FrozenMap))
    is_sequence = isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )
    if not is_mapping and not is_sequence:
        raise TypeError(f"Unsupported bridge value {type(value).__name__}")

    identity = id(value)
    if identity in seen:
        raise ValueError("Cyclic containers cannot cross the native bridge")
    seen.add(identity)
    try:
        if is_mapping:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError("Bridge mapping keys must be strings")
                _validate_bridge_value(item, seen=seen)
        else:
            for item in value:
                _validate_bridge_value(item, seen=seen)
    finally:
        seen.remove(identity)


def _to_json_compatible(value: Any) -> Any:
    """Convert immutable Vyne types to JSON-compatible equivalents.

    FrozenMap → dict (recursively).  This is only used for
    validation/serialization — the original frozen value is preserved
    for immutability guarantees.
    """
    from vyne.values import FrozenMap
    if isinstance(value, FrozenMap):
        return {k: _to_json_compatible(v) for k, v in value.items()}
    if isinstance(value, dict):
        return {k: _to_json_compatible(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_json_compatible(v) for v in value]
    if isinstance(value, tuple):
        return [_to_json_compatible(v) for v in value]
    return value

def _spec(name, required, semantic=None):
    req = frozenset(required)
    return _OperationSpec(
        name, req, frozenset(),
        _simple_op_validator(name, req, frozenset(), semantic),
    )


_OPERATION_SPECS: dict[str, _OperationSpec] = {
    s.name: s
    for s in [
        _spec("clear", {"op", "id"}),
        _spec("create", {"op", "id", "kind"}, _semantic_create),
        _spec("set_props", {"op", "id", "props"}, _semantic_set_props),
        _spec("set_prop", {"op", "id", "name", "value"}, _semantic_prop),
        _spec("remove_prop", {"op", "id", "name"}, _semantic_prop),
        _spec("listen", {"op", "id", "event", "handler"}, _semantic_event),
        _spec("listen_latest", {"op", "id", "event", "handler"}, _semantic_event),
        _spec("unlisten", {"op", "id", "event"}, _semantic_event),
        _spec("insert_child", {"op", "parent", "child", "index"}),
        _spec("move_child", {"op", "parent", "child", "index"}),
        _spec("remove_child", {"op", "parent", "child"}),
        _spec("remove", {"op", "id"}),
        _spec(
            "scroll_to",
            {"op", "id", "offset_x", "offset_y", "animated"},
            _semantic_scroll_to,
        ),
        _OperationSpec("motion_set_target", frozenset(), frozenset(), _validate_motion_operation),
        _OperationSpec("motion_cancel", frozenset(), frozenset(), _validate_motion_operation),
        _OperationSpec("motion_driver_set_target", frozenset(), frozenset(), _validate_motion_operation),
        _OperationSpec("motion_driver_cancel", frozenset(), frozenset(), _validate_motion_operation),
    ]
}


def _validate_operation(op: JsonObject, *, path: str) -> None:
    """Validate one operation through its registered spec — one dispatcher."""
    name = op.get("op")
    if not isinstance(name, str):
        raise TypeError(f"{path}.op must be a string")
    spec = _OPERATION_SPECS.get(name)
    if spec is None:
        raise ValueError(f"{path} has unknown operation {name!r}")
    spec.validator(op, path=path)
