# Lowering (Element -> CanonicalElement)

Source: `vyne/lowering.py`.

Lowering is the single validation point for every prop value. It converts
user-facing Element trees into fully resolved, immutable canonical
representations before the diff engine sees them.

## Precedence

```text
kind defaults < Decoration tier < explicit direct props
```

Layers are merged with ordered `dict.update`: later layers win. An explicit
value always replaces a same-valued default and gets validated — dict
semantics never treat `1 == True` as equal.

The merge decides precedence. No producer consults another layer's keys.

## Aliases and shorthands

Resolved before merging:

| alias | canonical |
|---|---|
| `alpha` | `opacity` |
| `accessibility_state_checked` | `accessibility_checked` |
| `accessibility_state_selected` | `accessibility_selected` |

| shorthand | expands to |
|---|---|
| `padding` | `padding_top/bottom/start/end` |
| `corner_radius` | four corner props |
| `size` | rejected (not supported) |

Conflicting explicit aliases (e.g. `alpha` and `opacity` set to different
values) reject at lowering time.

## Decoration tier

Supported:

- solid rectangle fill color -> `background_color`
- stroke color/width -> `border_color` / `border_width`
- corner radii -> four corner props
- `Shadow.elevation` -> `elevation`
- `Ripple.color` -> `ripple_color`

Rejected (unknown fields reject; removed constructors/fields are gone from
the `vyne.style` API):

- gradients (linear/radial/sweep)
- dashed strokes
- Shape oval/line/ring
- `translation_z`
- unbounded ripple
- `Decoration.clip` (not part of the API — needs a native outline slot,
  planned but not implemented)

## Validation flow

For each prop, in order:

1. Canonicalize animated values (extension constructors may bypass the
   widget encoding, so the marker normalization lives here).
2. Drop `None` values early.
3. Event props: check the callback is callable and the delivery policy is
   `all` or `latest`.
4. Unknown props for the kind reject (`Unsupported prop 'x' for Kind`).
5. Known props validate against their `ValueSpec`.
6. Extension props (no value spec) pass `ensure_bridge_value`: bridge-safe
   domain enforced here, not at commit time.
7. Animated payloads reject on props that are not animatable.

Deep validation:

- `Path.commands` — command letters and arity checked
- `Canvas.draw` — every operation validated against `CANVAS_OP_SPECS`,
  then `CanvasOpIdentity.stabilize()` assigns stable op ids
- `view_box` — `[x, y, width, height]`, positive width/height

Child rules:

- duplicate sibling keys reject
- `max_children` enforced (e.g. `Scroll` allows at most one child)
- kind-specific child allowlists enforced for core kinds; extension
  children are always accepted by core containers

## Defaults

`_materialize_defaults(kind)` builds the canonical defaults from the
schema. Props with `drop_default=True` are excluded: their default must
not be sent to native because the native View's inherent behavior is
already correct (e.g. `focusable=False` must not disable a TextInput's
editing focus).

## Identity cache

The Runtime keeps `id(Element) -> (element, canonical)`.

- Unchanged component output reuses the cached canonical subtree.
- After each render, entries not used again are pruned.

## Deep freezing

All resolved props are recursively frozen (MODEL-03). Nested dicts and
lists become `FrozenMap` and tuples. Mutation after lowering is
impossible.

## Related

- [core-model.md](../concepts/core-model.md) — CanonicalElement
- [protocol.md](protocol.md) — what crosses the wire
- [reconciliation.md](reconciliation.md) — what consumes canonical trees
