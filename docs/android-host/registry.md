# The Android Host: Registry and Widgets

Sources: `ElementRegistry.kt`, `NativeWidgets.kt`,
`PropertyApplicators.kt`, `generated/ElementContracts.kt`,
`tools/generate_schema.py`.

## ElementRegistry

Maps Python element kinds to Android View factories.

Each `ElementSpec` encodes:

- `create` — the View factory
- `props` — per-prop handlers invoked on `set_prop`; the SAME handler
  with a null value handles removal (each handler owns its default in one
  place)
- `events` — extension event hooks `(view, emit) -> detach` for
  extension-specific events; core events keep their dedicated
  `Renderer.attachListener` when-block
- `container` — whether the native view is a ViewGroup and accepts
  children

Registration lifecycle:

1. core widgets register via `registerNativeWidgets`
2. extensions register via the generated `registerAppExtensions`
3. `freeze()` locks the registry; the Renderer uses it read-only

Python queries `extensionKinds()` at startup and builds its validation
tables from the frozen registry. One contract, one code path, no drift
(see [extensions.md](../extensions/extensions.md)).

## Core widget mapping

| kind | Android class |
|---|---|
| `Box` | rounded `FrameLayout` (absolute + z-order layout) |
| `Layout` | rounded `LinearLayout` |
| `Scroll` | `ScrollView` (at most one child; Python wraps extras in a Column) |
| `Text` | `TextView` |
| `TextInput` | `EditText` (IME support) |
| `Image` | `ImageView` |
| `Path` | `PathView` (SVG-like commands) |
| `Canvas` | `CanvasView` (declarative display list) |

`Row` and `Column` are Python conveniences that lower to `Layout` with
`orientation`.

Rounded corners: `RoundedFrameLayout` / `RoundedLinearLayout`
(`RoundedViewGroup.kt`) support per-corner radii via `dispatchDraw`.

## PropertyApplicators

The table-driven applicator maps canonical Python prop names to strict
Android setters and resetters.

Design principles:

- **one set/reset table** — every supported property has exactly one
  apply and one remove entry
- **generated contracts are production inputs** — ElementContracts
  defines kind applicability; the applicator validates against it
- **no fallback coercion** — unknown or inapplicable props reject with a
  clear error, never silently default to zero/transparent
- **neutral Views** — no policy assumptions baked into construction
- **Python-owned dimensions** — tagged wire tokens converted
  mechanically (see [renderer.md](renderer.md))

## Generated contracts

`ElementContracts.kt` is generated from `vyne/spec/schema_v2.py` by
`tools/generate_schema.py`:

- `KINDS`
- per-kind prop sets (`ALL_PROPS_BY_KIND`)
- per-kind event sets (`ALL_EVENTS_BY_KIND`)
- `GENERIC_PROPS` (the intersection of all core kind prop sets — the same
  derivation on both sides)
- `ANIMATABLE_PROPS`

Python is the source; Kotlin is generated. If you add a prop or kind,
regenerate the contracts.

## Extension kinds

`ElementRegistry.isValidProp` / `isValidEvent`:

- core kinds validate against the generated contracts
- extension kinds accept `GENERIC_PROPS` plus the spec's declared props /
  events

`extensionKinds()` returns every non-core kind with its widget-specific
props, events, and container flag — the exact shape Python's
`ExtensionKindInfo.from_bridge` validates.

## Related

- [renderer.md](renderer.md) — how specs are used at apply time
- [../extensions/extensions.md](../extensions/extensions.md) — the extension contract
- [framework/lowering.md](../framework/lowering.md) — Python validation
