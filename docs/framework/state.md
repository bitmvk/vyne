# State, Components, and the Hooks Model

Sources: `vyne/state.py`, `vyne/component.py`, `vyne/scheduler.py`.

## State cells

`state(initial)` allocates a `State` cell. Cells are matched to calls by
index within their owning component scope — React-style.

Rules:

- hooks must keep a stable order within their component
- hooks must not be conditional or reordered (violations raise)
- setting the same value (by equality) is a no-op

Each cell is bound to its owning Runtime at creation (StateHost protocol).
`State.set()` delegates to the owner's single write path. There is no
ContextVar lookup on write and no attribute probing.

## Render-phase mutation guard (SCHED-03)

`State.set()` during a render pass raises `RenderPhaseMutationError`.

State changes must be driven by:

- event handlers
- animation callbacks
- async callback continuations

Never by the render pass itself.

## Pass guard (SCHED-03)

A bounded pass counter (`MAX_PASSES_PER_FLUSH = 5`) prevents accidental
infinite re-render loops.

- reset on every external flush
- nested re-renders share one bound
- if the guard trips, the runtime routes to controlled recovery

## The state journal (COORD-05)

During a flush (event dispatch + render pass), every `State.set()` is
recorded in the `StateJournal` with its pre-flush value.

- flush success -> journal commits (values already applied)
- flush failure -> journal rolls back every mutated cell to its pre-flush
  value

A failed event handler or render pass never leaves component state
inconsistent, even though the tree resets to the error commit.

## Component scopes

`@component` creates an explicit render boundary (`ComponentScope`).

Each scope owns:

- its function, args, and kwargs
- an ordered hook list (State cells and Animated.Value drivers)
- cached output Element
- child scopes
- dirty flags

Behavior:

- output is cached; the function re-executes only when dirty or inputs
  differ
- `state.set()` marks only the owning scope dirty (subtree-local
  invalidation)
- ancestors get `descendant_dirty`, so they re-render but keep their own
  cached outputs
- reconciliation always covers the full tree (SCHED-04): component
  boundaries are a performance optimisation, not an isolation boundary

## Keyed components

`@component(key=lambda ...)` gives each call stable identity across
sibling reordering.

- the key callable receives the same arguments as the component
- a keyed component's returned root Element receives the same key when it
  does not already have one
- an explicitly returned, different root key is rejected, so component
  state and native identity cannot diverge
- duplicate component keys in one parent reject

## Component checkpoint

Before a flush, the runtime snapshots every scope's mutable fields
(component checkpoint). On rejection or failure, the checkpoint restores:

- args, kwargs, hooks, hook index
- children, child index
- output, root node id
- dirty flags

This is part of the framework transaction rollback (COORD-05).

## Async callback writes

State writes from an async callback:

- while a commit is in flight: deferred (recorded with a baseline);
  adopted when the commit resolves
- otherwise: journaled normally

A failed async callback reverts its deferred writes to their baselines.

## Outside a runtime

Outside a runtime render, `@component` wrappers are transparent: they just
call the function. Stateless components stay convenient to construct and
test directly.

## Related

- [runtime.md](runtime.md) — the render loop that drives scopes
- [coordinator.md](coordinator.md) — promotion and rollback
- [events.md](events.md) — what runs handlers
