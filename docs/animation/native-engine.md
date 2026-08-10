# Animation: The Native Engine

Source: `android/host/src/main/java/dev/vyne/PresentationEngine.kt`.

Commits are only the ordered control plane. Once a target is accepted,
the `PresentationEngine` owns every presentation frame, independently of
Python and commit timing.

## Frame clock

A `Choreographer`-backed frame clock posts one frame callback per frame
(~16 ms). The engine runs only while transitions exist; idle engines do
not consume frames.

## Adapters

Each presentation slot registers a `PropertyAdapter`:

```kotlin
interface PropertyAdapter {
    fun read(): Float      // current live presentation value
    fun write(value: Float)
    fun settle(value: Float)  // optional post-settle hook
}
```

- View properties: adapters wrap View setters/getters.
- Canvas fields: adapters wrap the display-list field, located by the
  stable op id.

## setTarget semantics

`setTarget(...)` starts or retargets one timeline:

- duration is **per tween segment** (keyframes advance segment by
  segment)
- **springs settle at each destination** before advancing
- a missing `from_value` always reads the adapter's current live value,
  so a delayed Python result cannot cause a jump
- target history keeps `(lastTargetNanos, lastTarget)` for velocity
  carry-over

## Retargeting

When a new target arrives for a live slot, the retarget policy decides:

- `restart` — new timeline from the current live value
- `maintain_velocity` — carry the current velocity into the new spec
- `snap_to_end` — jump to the previous target, then start
- `ignore` — leave the current timeline alone

## Cancellation

- `cancel(slotKey)` stops the transition on that slot.
- Cancellation is generation-safe: the command carries `animation_id`,
  and only a matching generation is cancelled.
- `unregisterSlot`/`unregisterNode` clean adapters, transitions, and
  history when views or Canvas ops are removed.

## Prime (declarative values)

`prime(slotKey, target)` establishes the first declarative value without
animating it. A declarative driver applies its first target immediately;
a later target for the same stable slot uses the adapter's then-live value.

## Drivers

`motion_driver_set_target` animates one numeric driver. Every View/Canvas
expression bound to that driver is evaluated from the same live value each
frame.

Expression evaluation is a small tree walk: `value`, `constant`, `add`,
`subtract`, `multiply`, `divide`, `negate`, `interpolate`, `clamp`.

Driver bindings are registered when props are applied (a driver id inside
an encoded prop value binds that slot). Unbound drivers are pruned after
each commit.

## Lifecycle events

When a transition completes or is cancelled, the engine emits a
`Lifecycle` (animation id, slot key, node id, property, status, reason)
through the sink. `MainActivity` wraps these as `__vyne_system__`
`animation_lifecycle` events back to Python.

Reasons include `disposed`, `removed`, `reprimed`, and user cancellation.

## Testability

The engine takes its frame clock and clock source as constructor
parameters, so JVM unit tests drive frames deterministically
(`RendererAnimationUnitsTest`, `PresentationEngineTest`).

## Related

- [python-api.md](python-api.md) — the commands the engine consumes
- [overview.md](overview.md) — policy vs mechanics
- [renderer.md](../android-host/renderer.md) — slot registration during apply
