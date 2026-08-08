# Extensions

A Vyne extension adds native widgets to a Vyne application. It lives in
the project — no packaging, no installation.

See [../extensions.md](../extensions.md) for the full guide. This page is
the developer summary.

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

The Kotlin `ElementSpec` is the single source of truth.

At app startup the host queries its frozen registry
(`DirectRenderHost.extensionKinds()`) and Python builds its validation
tables from the answer (`sync_from_host`). Extension kinds, props,
events, and container capability flow through the exact same lowering /
preflight / rollback pipeline as core widgets.

Python never declares anything. Drift is impossible by design.

An `ElementSpec` declares:

- `create` — the View factory
- `props` — one handler per prop; a null value means removal, so each
  handler owns its default in one place
- `events` — `(view, emit) -> detach` hooks for extension events
- `container` — whether the view accepts children

Typed helpers: `floatProp`, `colorProp`, `stringProp`, `boolProp` — all
treat null as removal.

## Python side: tools, not wiring

The extension's Python module is a plain module the app imports:

```python
from vyne.elements import Element

def TimerRing(progress=0.0, ring_color="#6750E8", **base):
    return Element("TimerRing", props={"progress": progress,
                                       "ring_color": ring_color, **base})
```

Launch handling is one framework tool: `run_app(App, pre_launch=fn)`.
The hook runs on every launch (cold and warm) before the render. It is
capture-only (no `state()`), errors are logged and never block, and the
app composes extension functions into it.

## Validation behavior

- unknown kinds/props/events fail at lowering with a hint that the
  extension's Kotlin must be registered
- animated values on extension props are rejected (v1: extension props
  are not animatable; generic props like `width`/`opacity` are)
- extension kinds are allowed as children of core containers
- a leaf extension kind (`container = false`) rejects children on both
  sides

## Build

- `vyne build` regenerates `ExtensionRegistrant.kt` (journaled,
  byte-identical skip) from the discovered `extensions/*/extension.toml`
  files, compiles the Kotlin dirs, packages the Python dirs, and
  assembles the APK
- `vyne doctor` validates each extension
- `vyne extension new <name>` scaffolds one

## v1 limits

- no animatable extension props
- no per-extension dependencies
- no pip distribution
- no sandboxing
- `pre_launch` is synchronous
- a failing event handler logs its traceback and preserves the accepted
  UI (RE-1)

## Related

- [extensions.md](../extensions.md) — the full guide
- [android-host/registry.md](../android-host/registry.md) — ElementRegistry
- [framework/lowering.md](../framework/lowering.md) — validation tables
