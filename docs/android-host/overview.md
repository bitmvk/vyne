# The Android Host: Overview

Sources: `MainActivity.kt`, `RuntimeOwner.kt`, `BridgeWorkScheduler.kt`,
`DirectRenderHost.kt`, `RenderTransaction.kt`, `LaunchIntentAdapter.kt`,
`VyneCallback.kt`, `async_runtime.py` (AsyncRuntimeDispatcher),
`android.py`.

## MainActivity

The single Activity that hosts a Vyne application.

- Chaquopy bridge calls run on a dedicated Python executor (not the UI
  thread).
- All Python-side work runs on one asyncio owner thread.
- The Renderer runs on the UI thread (it touches Views).
- Events flow: widget -> Renderer.eventSink -> BridgeWorkScheduler ->
  Python owner thread -> commit -> runOnUiThread -> Renderer.

### Cold vs warm launch

`RuntimeOwner.claim(activity)` decides:

- if another instance owns the live runtime, the new Activity forwards
  its Intent there and finishes — never a second Python owner
- the first Android `Intent` is supplied before the initial render
- a later `onNewIntent` delivery reruns the same root with new
  `LaunchData`, preserving state and runtime

`LaunchIntentAdapter` converts Android Intents into bridge-safe
`LaunchData` (action, uri, extras, sequence). Application manifest,
notifications, PendingIntent, and launch-mode configuration remain owned
by the application.

## The threading boundary

`AsyncRuntimeDispatcher` (Python) runs a dedicated asyncio loop thread:

- every bridge turn is submitted as one task (`dispatcher.call(...)`)
- synchronous callbacks, async continuations, rendering, and commit
  creation never mutate the Runtime concurrently
- a pipe wakes the loop; `settle` runs newly scheduled callbacks through
  their first useful yield before the bridge turn returns

Android enters Python on a short-lived bridge executor; the dispatcher
moves the work onto the one persistent loop.

## BridgeWorkScheduler

One explicit backpressure gate for everything entering Python.

- separate ordered queues: receipts, events, launches, callbacks
- at most one Python dispatch in flight (`inFlight`)
- `latest` events coalesce by (target, event, handler, gesture_id): a
  newer event replaces the queued one at the same slot, and later slot
  indices shift
- `latest` callbacks coalesce by callback slot
- receipts are delivered before the events they unlock
- as soon as the active dispatch completes, queued work dispatches
  without waiting for a display-frame boundary

## DirectRenderHost

The typed call surface Python sees (see
[framework/transport.md](../framework/transport.md)).

- calls arrive on the Python executor and only build an immutable
  `RenderTransaction`
- `finishCommit()` posts one transaction to the UI thread; the Renderer
  applies it
- `abortCommit()` discards the transaction on error
- `setSessionId()` publishes the Python session uuid before the first
  commit, so receipts are session-scoped
- `extensionKinds()` answers the registry query
- `createCallback()` wraps a Python callable in the Activity's ordered
  bridge-work queue
- optional `beginMeasurement`/`commitScheduled` support benchmark
  instrumentation (logcat `VYNE_BENCH` lines)

## Apply results

The Renderer answers every commit with one result (see
[renderer.md](renderer.md)):

| result | Python action |
|---|---|
| `ok` | promote the candidate (SYNCED) |
| `rejected_known` | preflight failed; discard candidate, replan |
| `verified_rollback` / `partial` | rollback succeeded; same as rejected_known |
| `unknown` | native state unknown; complete snapshot required |

## Application-owned callbacks

`callback(fn, delivery=..., sample_interval_ms=...)` returns a
`VyneCallback` safe to invoke from any Android thread:

- `delivery="all"` preserves every queued value
- `delivery="latest"` bounds a backed-up subscription to its newest value
- `sample_interval_ms` mechanically limits how often values enter the
  queue
- `dispose()` removes queued values and releases the Python callable;
  runtime shutdown disposes every remaining subscription

`ScheduledVyneCallback` holds the Activity by weak reference and admits
calls through `CallbackAdmission`, so a destroyed Activity is never
retained by application-owned work.

## Related

- [list-host-contract.md](list-host-contract.md) — portable list policy/host split
- [renderer.md](renderer.md) — the UI-thread applier
- [input.md](input.md) — touch routing
- [framework/transport.md](../framework/transport.md) — the call surface
- [concepts/data-flow.md](../concepts/data-flow.md) — the full thread flow
