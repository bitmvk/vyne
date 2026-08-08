# The Runtime

Source: `vyne/runtime.py`.

The `Runtime` is the heart of Vyne. It owns the entire lifecycle:

1. calls the user's root component function to produce an Element tree
2. lowers and diffs the tree against the previous RenderSnapshot
3. sends the commit through a Transport
4. receives native events and dispatches them to user handlers
5. re-renders

It is the single-owner orchestrator. A host (test runner, Android bridge,
CLI) creates one Runtime per application and calls `mount()`.

## Phases

The runtime tracks its phase in a ContextVar:

- `None` — outside a flush
- `"render"` — executing component functions
- `"event"` — running handlers

The render-phase mutation guard reads this phase.

## Mount and root arguments

- `mount()` renders the root and emits the first commit.
- The root may accept one `LaunchData` argument (immutable launch data:
  action, uri, extras, sequence).
- `update_root_arguments()` queues later launches; each renders in
  delivery order after the preceding commit resolves. A rapid sequence of
  launches is not collapsed into only the final launch.

## The render loop

`_render_loop()` runs passes until no more are requested, bounded by the
pass guard. Each pass (`_render_once`):

1. executes the root component under `runtime_context` and phase
   `"render"`
2. lowers the Element tree (with the identity cache)
3. plans reconciliation from the accepted snapshot
4. binds candidate runtime intents (listeners, refs)
5. applies acknowledgement suppression to `set_prop` ops
6. stages the candidate
7. sends the commit with a provisional reservation

## Render scheduling

`request_render()`:

- defers when already inside a batch or render
- defers when a commit is in flight (the ack handler picks it up)
- otherwise renders synchronously

`_flush_batched_render()` runs after event batches, then emits the commit,
then clears the acknowledgement map.

## Event dispatch

- `dispatch_events()` validates a native batch and dispatches.
- One batch = one state journal session = one render = one commit.
- Handlers that return awaitables are scheduled on the asyncio owner loop
  after the batch.
- The leading apply-receipt prefix of a batch is consumed first (closes
  the previous transaction).

## Animation integration

- `start_animation()` allocates an animation id and queues a
  `SetTarget`/`DriverSetTarget` command.
- Commands queue separately during dispatch and merge into the next
  commit (SCHED-01).
- If only animations are pending, `_send_animation_only_commit()` emits
  an animation-only commit.
- `cancel_animation()` is generation-safe: it checks the handle is still
  the registered one.
- Native `animation_lifecycle` events close handles and run
  `on_complete`/`on_cancel` callbacks as ordered events.
- Rejected commits reject their animations (`framework_rollback`,
  `native_state_unknown`).

## Error handling

`_send_error_commit()`:

- if accepted UI exists: log, roll back the journal, discard the staged
  candidate, preserve the accepted tree (RE-1)
- if no accepted UI: emit the fallback error commit
- after 5 consecutive faults: enter `FAULTED`, stop emitting error
  commits (RE-6)

## External callbacks (application-owned Android code)

`subscribe_external_callback()` registers one callable under Runtime
lifecycle ownership. `dispatch_external_callbacks()`:

- disposes subscriptions first
- validates ownership
- runs one journaled, batched render
- schedules awaitable callbacks

Disposal removes queued values and releases the Python callable. Runtime
shutdown disposes every remaining subscription.

## Disposal

`dispose()`:

- rolls back state and components
- invalidates every live Ref
- clears the coordinator, animations, drivers, pending arguments, ack map
- disposes the async callback manager
- deactivates external callback subscriptions

After disposal the runtime cannot be remounted.

## Related

- [coordinator.md](coordinator.md) — commit lifecycle
- [recovery.md](recovery.md) — native synchronization health
- [state.md](state.md) — hooks and journal
- [transport.md](transport.md) — where commits go
