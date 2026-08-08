# The Android Host: Input

Sources: `InputController.kt`, `PointerSession.kt`, `EventBindings.kt`.

## InputController

Installed on the root view by the Renderer. It is the single routing
point for touch input.

- intercepts `MotionEvent`s at the root
- routes pointer streams to `PointerSession`s
- detects taps and long presses for the core `click` / `long_click`
  events
- owns focus behavior (e.g. `blur_on_tap_outside` for TextInput)

## PointerSession

Tracks one pointer stream from down to up/cancel:

- pointer id, down position and time
- current x/y, event time, pressure, size, tool type, source
- touch slop filtering (`scaledTouchSlop`) — jitter below the slop does
  not become movement
- a **gesture id** per down-up session

The gesture id is the key that makes `latest` coalescing correct: while a
handler for `pointer_move` runs, native retains only the most recent
event for the same (target, event, handler, gesture).

## Pointer event payload

`pointer_down` / `pointer_move` / `pointer_up` / `pointer_cancel`
deliver:

```text
x, y, pointer_id, event_time, pressure, size,
tool_type, source, down_x, down_y, down_time, gesture_id
```

These fields are validated by the schema on the Python side
(`_POINTER_PAYLOAD_SPECS`).

## EventBindings

`EventBindings` maps (node id, event) to binding records:

- handler id, delivery policy
- attach/detach functions (setOnClickListener, text watchers, focus
  change listeners, editor action listeners, touch listeners, insets
  listeners)
- `clear()` detaches everything (dispose path)

Core events keep their dedicated attach when-block in the Renderer;
extension events use their spec hooks (see
[registry.md](registry.md)).

## Text input

`TextInput` (EditText) specifics:

- `text_change` with the new text (controlled) — the acknowledgement map
  suppresses the echo write-back (see
  [framework/events.md](../framework/events.md))
- `focus_change` with `has_focus`
- `editor_action` with action id and text
- focus props: `focused`, `blur_on_keyboard_hide`, `blur_on_tap_outside`,
  `blur_on_submit`

## Accessibility

Accessibility state is driven by Python props:

- `content_description`, `accessibility_role`
- `accessibility_checked`, `accessibility_selected`
- `accessibility_state_description`
- `accessibility_range_min/max/current`
- `accessibility_progress` events report range progress back to Python
  (controlled)

## Related

- [overview.md](overview.md) — where events go next
- [framework/events.md](../framework/events.md) — dispatch and delivery
- [registry.md](registry.md) — event contracts per kind
