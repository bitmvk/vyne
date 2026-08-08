# Data Flow

This page shows how one render cycle moves through the stack, and how
threads are organized.

## One render cycle

```text
user event (native)
  -> BridgeWorkScheduler (ordered queue, backpressure)
  -> Python asyncio owner thread
  -> Runtime: state journal begins
  -> Runtime: event handlers run (may call state.set())
  -> Runtime: render pass
      -> root component function runs -> Element tree
      -> lowering -> CanonicalElement tree
      -> plan_reconcile -> operations + new RenderSnapshot
      -> listener ops and refs are bound
      -> commit message (revision + ops)
  -> DirectTransport: typed Kotlin calls build a transaction
  -> UI thread: Renderer preflights, applies, journals undo
  -> native apply receipt (ok / rejected_known / verified_rollback / unknown)
  -> Runtime: promote candidate or enter recovery
```

Every commit has one revision number. At most one commit is in flight at a
time. The native side always answers with an apply result.

## Threading model

Four places run work:

| place | runs | owns |
|---|---|---|
| Android UI thread | the Renderer | Views, drawing, input delivery |
| Python executor (Chaquopy) | thin adapters | decoding bridge calls |
| asyncio owner thread | the Runtime | state, dispatch, render, commit |
| Choreographer frames | the PresentationEngine | animation frames |

The Runtime is never mutated concurrently. All framework work moves to one
asyncio loop thread (`AsyncRuntimeDispatcher`). This makes state writes,
renders, and commits single-threaded and ordered.

## Backpressure

All work entering Python goes through one gate: `BridgeWorkScheduler`.

- It keeps separate ordered queues for receipts, events, launches, and
  application callbacks.
- At most one Python dispatch is in flight.
- `latest` events coalesce by (target, event, handler, gesture id): a
  newer event replaces the queued one at the same slot.
- Receipts are delivered before the events they unlock.

See [android-host/overview.md](../android-host/overview.md).

## Event batching

Native events are delivered in batches. One batch:

1. opens one state journal session
2. runs all handlers in order
3. runs one render pass
4. produces one commit

A handler that fails rolls back all journaled state mutations and preserves
the accepted UI (RE-1).

## Commit ordering rules

- Renders that arrive while a commit is in flight are deferred.
- The ack handler picks them up and renders the coalesced change.
- Animation commands queue during event dispatch and merge into the next
  commit (SCHED-01).
- If only animations are pending, an animation-only commit is sent.
- Python is never called for individual animation frames.

## Async callbacks

Event handlers and `callback()` functions may be `async def`.

- The returned awaitable runs on the asyncio owner loop.
- State writes before an `await` are batched into one ordered commit.
- State writes after resume are batched into a later commit.
- Other callbacks can still run while one is suspended.

## Related

- [principles.md](principles.md) — who owns what
- [framework/runtime.md](../framework/runtime.md) — the orchestrator
- [framework/transport.md](../framework/transport.md) — how commits leave Python
- [android-host/overview.md](../android-host/overview.md) — the native side
