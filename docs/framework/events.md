# Events, Handlers, and Acknowledgements

Sources: `vyne/events.py`, `vyne/scheduler.py` (AcknowledgementMap).

## The Event object

`Event` carries: `name`, `target` (node id), `handler` (handler id),
`payload`, and `sequence`.

Events arrive from native in batches. `dispatch_events()` validates the
batch, then runs one ordered dispatch.

## EventRegistry

`EventRegistry` maps protocol-safe handler IDs to Python callbacks.

The registry is cloned per render (`clone()`). The candidate registry
becomes the accepted registry only on promotion. This keeps handler state
transactional like the tree.

Handler wrapping: zero-argument handlers (`on_click=lambda: ...`) are
wrapped once at registration time, so users never see the event argument.
Signature inspection happens once, not per event.

## Delivery policies

- `"all"` — every event is delivered in order.
- `"latest"` — `latest(callback)` keeps only the newest queued event per
  key. A running handler is never cancelled; while it runs, native retains
  only the most recent pending event.

The native side coalesces by `(target, event, handler, gesture_id)` in the
`BridgeWorkScheduler` (see [android-host/overview.md](../android-host/overview.md)).

## Listener identity

A listener that stays installed across renders keeps its handler ID; only
its closure is refreshed in the detached registry.

Consequences:

- a delayed event never binds to a replacement callback (the runtime
  checks `event.handler == node.listeners[event.name]`)
- delivery policy changes emit a `listen`/`listen_latest` swap op

## Handler lifetime

The runtime keeps the accepted `RenderNode.listeners` map. During intent
binding:

- new listeners register and emit `listen` ops
- removed listeners unregister and emit `unlisten` ops
- handlers with no live listener are dropped from the candidate registry

## Acknowledgements (SCHED-02)

When a controlled event arrives (e.g. `text_change` with the new text),
the runtime records `(node_id, prop_name) -> native_value` in the
`AcknowledgementMap`.

During the next render, `set_prop` ops whose desired value equals the
acknowledged native value are **suppressed**.

Why: without suppression, Python would write back the exact text the user
just typed. That causes cursor jumps in TextInput and visual flicker.

Extraction is schema-driven: `extract_acknowledgements()` reads
`EventSpec.controlled_props`. No event name is hardcoded. The map is
cleared after each commit is sent.

## Batch ordering

A native batch may begin with apply receipts. The runtime consumes that
leading receipt prefix first, closing the previous framework transaction,
before opening the next event transaction. Otherwise an acknowledgement
would commit the journal underneath a completion callback in the same
batch.

## Failure behavior

- Invalid messages are discarded without clearing a known-good tree.
- A handler that raises: the traceback is logged, journaled state rolls
  back, and the accepted UI is preserved (RE-1).
- Awaitable handlers are scheduled on the asyncio owner loop after the
  batch commit; their continuations run under the same runtime context.

## Related

- [protocol.md](protocol.md) — event schemas
- [state.md](state.md) — the state journal
- [runtime.md](runtime.md) — dispatch loops
- [recovery.md](recovery.md) — failure handling
