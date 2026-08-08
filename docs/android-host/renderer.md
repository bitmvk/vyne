# The Android Host: Renderer

Source: `Renderer.kt`, `RenderTransactionApplier.kt`, `NativeTree.kt`.

The Renderer is the Android counterpart of the Python Runtime. It
receives commits (typed transactions built by `DirectRenderHost`) and
applies them directly to Android Views.

There is **no virtual DOM on this side**. The Renderer trusts the Python
diff and mechanically executes the ops. It keeps only the mutable view
state needed for property reset and rollback.

## Commit application

One transaction applies in four phases:

### 1. Preflight

Every operation is validated **before any View mutation**:

- op types are known
- kinds are in the generated contracts
- prop names are in the applicable kind's prop set
- parent/child relationships are checked against shadow indexes
  (inserts, moves, removes, subtree consistency, cycles)
- listener events are in the kind's event contract
- motion ops validate slots, domains, easing, retarget, spring
  parameters

Rejections throw, nothing mutates, and the result is `REJECTED_KNOWN`.

### 2. Apply with journal

Each operation is journalled with an undo closure before execution:

- `record { ... }` appends the undo for the current mutation
- undo closures restore exact prior state
- after successful apply, `afterCommit` hooks run (e.g. animation
  binding setup)

### 3. Rollback

On failure the journal replays in reverse. `restoreAll(actions)` runs
**every** restoration action; the first failure is rethrown after all
run, later failures attach as suppressed exceptions — nothing is silently
erased (design-pattern #3).

- rollback success -> `PARTIAL` (prior revision is known-good)
- rollback failure -> `UNKNOWN` (native state is unknown)

### 4. Digest

`mechanicalDigest()` fingerprints the native tree: for each view, id,
kind, parent, child order, visibility, enabled, alpha, rotation, scale,
and TextView text; plus every event binding (handler, delivery).

The digest is compared before and after application. Unexplained drift
returns `UNKNOWN`. This is the authoritative check that Python's mirror
and the native tree agree.

## ApplyResult

```kotlin
enum class ApplyResult {
    OK,              // all operations applied
    REJECTED_KNOWN,  // preflight rejected; nothing mutated
    PARTIAL,         // rollback succeeded; prior revision known-good
    UNKNOWN,         // native state unknown; snapshot required
}
```

## NativeTree

The authoritative native-tree storage, owned by the Renderer:

- `views` — id -> View (0 is the root FrameLayout)
- `specs` — id -> ElementSpec (kind)
- `parentOf`, `childrenOf` — structural indexes
- `viewStates` — per-view state (ViewState, NodeLayout)
- `propMementos` — accepted-prop records

## PropMemento (design-pattern #2)

One record per (node, prop) holding what the framework accepted:

- `present` — whether the prop is present
- `acceptedWireValue` — the accepted wire value (deep-copied on store
  and retrieve)
- `livePresentationValues` — slot-keyed live values (Canvas keeps
  several live values per slot)

This is the single authority for props. One rollback algorithm covers all
kinds, and it is digest-consistent.

## Generic props

Common properties (width, height, padding, background, corners,
elevation, transforms, visibility, enabled, ...) are applied by one
central table in `PropertyApplicators.kt` (`handleGenericProp`), not
scattered across widget handlers.

Each property has exactly one setter (apply) and one resetter (remove).
Views are created neutral: e.g. `focusable=False` never disables a
TextInput's default editing focus.

Dimensions arrive as tagged wire tokens:

- numeric -> dp -> pixels
- `"wrap_content"` / `"match_parent"` -> Android layout constants
- `"16dp"`, `"16sp"` -> dp/sp -> pixels

Kotlin converts mechanically; Python owns the meaning.

## Animation integration

- `PresentationEngine` runs the frames (see
  [animation/native-engine.md](../animation/native-engine.md))
- declarative animated props and Canvas slots register adapters during
  prop application
- removed nodes unregister their slots
- unbound drivers are pruned after each commit
- dispose cancels every transition with reason `disposed`

## Events out

Widget events go through `eventSink` -> `BridgeWorkScheduler` (see
[overview.md](overview.md)). `latest`-delivered listeners coalesce
natively by (target, event, handler, gesture id).

## Related

- [overview.md](overview.md) — the threading boundary
- [registry.md](registry.md) — kinds and contracts
- [framework/recovery.md](../framework/recovery.md) — how Python reacts
