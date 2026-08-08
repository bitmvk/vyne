# Animation Overview

The animation system is split by the same principle as everything else:

> Python owns animation policy. Kotlin owns the mechanics.

Python sends motion commands inside commits. Kotlin's `PresentationEngine`
owns every presentation frame afterwards — one frame clock, one
integration engine, shared by View properties and Canvas operations.

There is **zero Python involvement during frames**. An accepted animation
continues while Python is awaiting or temporarily busy.

## The three APIs

| API | use case |
|---|---|
| `animate(...)` | one-off property transitions, no declared state |
| `Animated.Value` | persistent drivers, derived expressions, composed timelines |
| `AnimatedValue(...)` | legacy target-driven values (compatibility) |

All three lower to `MotionCommand` objects.

## Lifecycle

1. A command is created in a render or event context
   (`SetTarget`/`Cancel`/`DriverSetTarget`/`DriverCancel`).
2. The Runtime allocates an animation id and queues the command.
3. Queued commands merge into the next commit (SCHED-01) — they travel
   alongside tree changes from the same handler.
4. If only animations are pending, an animation-only commit is sent.
5. The native engine starts the timeline on acceptance.
6. Terminal state returns as an ordered `__vyne_system__`
   `animation_lifecycle` event (`completed` or `cancelled`, with reason).
7. The handle finishes; `on_complete` / `on_cancel` callbacks run as
   ordered events (async callbacks supported).

## Ordering rules

- Animation commands are ordered with the commit that created or updated
  their target.
- Commits are gated: animation-only commits also respect the
  one-in-flight rule.
- If a commit is rejected, its animations are rejected too
  (`framework_rollback`, `native_state_unknown`).
- Declarative `AnimatedValue` first targets apply immediately on mount;
  later targets animate from the live displayed value.

## Generation safety

Every handle carries its animation id and slot:

- `handle.cancel()` from an event or render callback cannot cancel a newer
  replacement animation on the same slot.
- A stale `ViewHandle`/`Ref` target raises instead of animating a removed
  view.
- Cancelling a group stops every still-active child (or only the
  cancelled one, with `stop_together=False`).

## What Python never does

- Python is not called per frame.
- Python does not read live presentation values.
- Python does not integrate physics.

The engine reads `from_value` natively when the command omits it, so
interruption and reversal are continuous — a delayed Python result cannot
cause a jump.

## Related

- [python-api.md](python-api.md) — slots, specs, handles, drivers
- [native-engine.md](native-engine.md) — the Kotlin engine
- [protocol.md](../framework/protocol.md) — motion operations
- [runtime.md](../framework/runtime.md) — command queueing
