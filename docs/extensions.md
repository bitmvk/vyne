# Vyne Extensions

A Vyne extension is a developer-written bundle that adds native widgets to a
Vyne application. It lives in the project — no packaging, no installation.

## Anatomy

```text
extensions/timer_ring/
  extension.toml        # one field: the Kotlin registration object
  python/               # Python modules, packaged into the APK
  android/              # Kotlin source root, compiled into the app
  res/                  # optional Android resource root
```

```toml
# extension.toml — the directory name is the extension identity.
android_register = "dev.vyne.ext.timerring.TimerRingExtension"
```

## The contract: one source of truth

The Kotlin `ElementSpec` is the single source of truth. At app startup the
host queries its frozen registry and Python builds its validation tables
from the answer — extension kinds, props, events, and container capability
flow through the exact same lowering / preflight / rollback pipeline as core
widgets. Python never declares anything; drift is impossible by design.

```kotlin
object TimerRingExtension {
    internal fun register(context: Context, registry: ElementRegistry) {
        registry.register(
            ElementSpec(
                kind = "TimerRing",
                create = { TimerRingView(it.context) },   // leaf: not a ViewGroup
                props = mapOf(
                    // One handler per prop; a null value means REMOVAL, so
                    // each handler owns its default in one place.
                    "progress" to floatProp(0f) { view, v ->
                        (view as TimerRingView).progress = v
                    },
                    "ring_color" to colorProp(0xFF6750E8.toInt()) { view, c ->
                        (view as TimerRingView).ringColor = c
                    },
                ),
                events = mapOf(
                    "complete" to { view, emit ->
                        val v = view as TimerRingView
                        v.onComplete = { emit(mapOf("finished" to true)) }
                        { v.onComplete = null }    // returned detach lambda
                    },
                ),
                container = false,   // default: a leaf view rejects children
            ),
        )
    }
}
```

Typed helpers: `floatProp(default)`, `colorProp(default)`, `stringProp(default)`,
`boolProp(default)` — all treat null as removal.

## Python side: tools, not wiring

The extension's Python module is a plain module the APP imports:

```python
# extensions/timer_ring/python/timer_ring.py
from vyne.elements import Element

def TimerRing(progress=0.0, ring_color="#6750E8", **base):
    return Element("TimerRing", props={"progress": progress,
                                       "ring_color": ring_color, **base})

def on_launch(context) -> None:
    """Capture function: compose into the app's pre_launch hook.

    Reads the launch from ``context.launch``.
    """
    ...
```

Launch handling is one framework tool: `run_app(App, pre_launch=fn)`. The
hook runs on every launch (cold and warm) before the render and receives
the same `AppContext` as the app; it is capture-only (no `state()`), errors
are logged and never block, and the app composes extension functions into
it:

```python
from timer_ring import on_launch as timer_launch
from notification_entry import on_launch as notification_launch

def pre_launch(context):
    notification_launch(context)
    timer_launch(context)

run_app(App, pre_launch=pre_launch)
```

`LaunchData` carries `action`, `uri`, `extras`, `sequence`, and `origin`
(`"cold"` for the session's first entry, `"warm"` for later ones — derived
from the session sequence).

## Build

`vyne build` regenerates `ExtensionRegistrant.kt` (journaled, byte-identical
skip) from the discovered `extensions/*/extension.toml` files, then compiles
the Kotlin dirs, packages the Python dirs, and assembles the APK. `vyne
doctor` validates each extension. `vyne extension new <name>` scaffolds one.

## Behavior notes

- Unknown kinds/props/events fail at lowering with a hint that the
  extension's Kotlin must be registered.
- `Animated(...)` values on extension props are rejected (v1: extension
  props are not animatable; generic props like `width`/`opacity` are).
- Extension kinds are allowed as children of core containers; a leaf
  extension kind (`container = false`) rejects children on both sides.
- Notification entry is fully app/extension-owned: build the PendingIntent
  with a stable `entryKey` in the intent data URI (PendingIntent identity),
  `CLEAR_TOP|SINGLE_TOP` flags, and plain action/extras. Delivery is
  at-most-once; durability is the app's (persist-then-drain in
  `pre_launch`, idempotent by a stable key — see the notification_entry
  example).

## v1 limits

- No animatable extension props, no per-extension dependencies, no pip
  distribution, no sandboxing.
- `pre_launch` is synchronous; a failing event handler logs its traceback
  and preserves the accepted UI (RE-1).
- Deferred model work: authoritative wire props for rollback (today a
  surgical shadow covers extension props), session-object resource
  ownership, durable processed-key persistence in the notification example.
