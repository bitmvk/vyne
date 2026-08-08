# The Commit Protocol

Source: `vyne/protocol.py`.

The protocol defines the logical message model. Two message types flow in
opposite directions:

- Python -> Native: `commit` messages carrying tree-patch operations
- Native -> Python: `event` (single) or `events` (batch) messages

Every message is validated before it can affect framework state.

## Commit envelope

```json
{
  "type": "commit",
  "revision": 7,
  "origin_event_seq": 42,
  "ops": [ ... ]
}
```

- `revision` must be an integer (>= -1, where -1 is the fallback error
  form)
- `origin_event_seq` is optional

## Operations

| op | fields | meaning |
|---|---|---|
| `clear` | id (0) | wipe native tree |
| `create` | id, kind | create a native view |
| `set_props` | id, props | set many props |
| `set_prop` | id, name, value | set one prop |
| `remove_prop` | id, name | reset one prop to its default |
| `listen` | id, event, handler | attach handler (`all` delivery) |
| `listen_latest` | id, event, handler | attach handler (`latest` delivery) |
| `unlisten` | id, event | detach handler |
| `insert_child` | parent, child, index | insert a view |
| `move_child` | parent, child, index | move a view |
| `remove_child` | parent, child | detach a child |
| `remove` | id | destroy a subtree |
| `motion_set_target` | animation_id, slot_key, node_id, property, targets, spec... | start/retarget an animation |
| `motion_cancel` | animation_id, slot_key | cancel an animation |
| `motion_driver_set_target` | + driver_id | animate a persistent driver |
| `motion_driver_cancel` | + driver_id | cancel a driver animation |

## Events

| event | kind | payload |
|---|---|---|
| `click`, `long_click` | all kinds | none |
| `pointer_down` / `pointer_move` / `pointer_up` / `pointer_cancel` | all kinds | x, y, pointer_id, event_time, pressure, size, tool_type, source, down_x, down_y, down_time, gesture_id |
| `text_change` | TextInput | text (controlled) |
| `focus_change` | TextInput | has_focus (controlled) |
| `editor_action` | TextInput | action_id, text |
| `accessibility_progress` | all kinds | value (controlled) |
| `__vyne_system__` | internal | native_apply_result \| animation_lifecycle |

`controlled_props` in the event schema marks payload fields that report a
native-held value (e.g. the current text of a TextInput). These feed the
acknowledgement map (see [events.md](events.md)).

## Validation

Validation is spec-driven. Each operation has an immutable `_OperationSpec`
with required fields, optional fields, and a semantic validator.

Checks include:

- unknown fields reject
- ids are non-negative integers (fits Android's int node id range)
- `create.kind` must be a canonical primitive (core or extension)
- `set_prop` name must be a known prop; values validate against ValueSpec
- `listen` event must be canonical
- `insert_child` index must be in range per the shadow model

### Motion validation

Motion ops are validated strictly:

- `slot_key` must exactly match its slot fields
  (`view:<node>:prop:<prop>` or `view:<node>:slot:<op_id>:<field>`)
- driver ops: `slot_key` must be `driver:<driver_id>`
- targets must be finite numbers
- domains enforced: `opacity`/`trim_start`/`trim_end` in 0..1,
  `elevation`/`width`/`height`/`radius`/`r`/`stroke_width` non-negative
- retarget policy in `restart` / `maintain_velocity` / `snap_to_end` /
  `ignore`
- tween: `duration_ms` non-negative, easing in `linear`, `ease_in`,
  `ease_out`, `ease_in_out`, `overshoot`, `bounce`
- spring: stiffness and damping ratio positive and finite; rest
  thresholds non-negative

### System events

`__vyne_system__` carries:

- `native_apply_result` — result in `ok` / `rejected_known` /
  `verified_rollback` / `partial` / `unknown`, plus revision and session
- `animation_lifecycle` — animation_id, status (`completed` /
  `cancelled`), node_id, property, optional reason

The session id makes receipts session-scoped: a receipt from a stale
session is ignored.

## Error commit

`error_commit()` builds the standard error screen using only valid v2
primitives (`Layout(vertical)` containing a `Text`). `Column` is a Python
convenience, not a registered native kind, and must never be emitted.

## Bridge safety

`ensure_bridge_value()` fails early if a prop cannot cross the direct
Python/Kotlin bridge:

- bool, str: fine
- int: signed 64-bit range
- float: must be finite
- mappings (string keys) and sequences: recursive, no cycles

## Related

- [transport.md](transport.md) — how validated commits leave Python
- [events.md](events.md) — event dispatch and acknowledgement
- [android-host/renderer.md](../android-host/renderer.md) — native preflight
