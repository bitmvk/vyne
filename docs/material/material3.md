# Material 3

Source: `vyne_material/` (components.py, theme.py, _foundation.py,
_callbacks.py, _geometry.py, _validation.py). The package is distributed as
`vyne-material` and imports as `vyne_material`; it depends on the `vyne` core.

## The approach

Vyne implements the complete Material 3 Expressive catalog (36 component
families) as **Python-owned composites**.

Key fact: components lower to the existing primitives — `Box`, `Layout`,
`Text`, `TextInput`, `Canvas`. There are **no** Material-specific Kotlin
view kinds, state machines, or selection policies.

## Controlled components

Components are **controlled**: Python owns the state.

Python owns:

- `checked`, `selected`, `value`, `visible`, `expanded`
- picker dates and times
- carousel indices
- progress

Callbacks receive the **proposed next Python value**:

```python
Slider(
    volume.value,
    minimum=0,
    maximum=1,
    step=0.05,
    on_change=volume.set,
)
```

This makes initial rendering and later updates use the same path — one
code path, no special cases.

## Theme and tokens

- `MaterialTheme(colors=ColorScheme(...), typography=Typography(...),
  shapes=ShapeScale(...))`
- color scheme: the full Material 3 palette (primary, on_primary,
  containers, surface tones, outline, ...)
- typography: type styles per role (font size, line height)
- shared color/type/shape/motion tokens are Python data

## Composition helpers

`vyne_material/_foundation.py` provides shared building blocks:

- `text()`, `slot()` — typography-aware text
- `spacer()`, `spaced_row()`, `spaced_column()` — gap layout (gaps are
  spacer elements, since flex/gap props are not yet supported)
- `checkmark_canvas()`, `radio_canvas()`, `switch_canvas()` — drawn
  indicators via Canvas
- `progress_path()`, `wavy_path()` — geometry generators
- `value_handler()`, `invoke()` — controlled callback adapters (one-time
  signature inspection)

## Selection and gesture logic

- selection models (tabs, chips, segmented buttons, navigation) live in
  Python (`_callbacks.py`)
- slider geometry and gesture math live in Python (`_geometry.py`,
  `test_material_slider_model.py` covers the model)
- `_validation.py` provides shared domain checks

## Catalog

All 36 Material 3 Expressive families are exported from `vyne_material`
(the `vyne-material` distribution). See
[../material3-expressive.md](../material3-expressive.md) for the catalog
table and usage guide.

## Testing

Material components are covered by Python unit tests:

- callbacks, colors, dates, disabled states, selection
- slider model and gestures
- measurement contract
- non-animation counters
- the showcase app (`examples/app.py`) exercises them on device

## Related

- [drawing/canvas-path.md](../drawing/canvas-path.md) — drawn indicators
- [framework/state.md](../framework/state.md) — controlled state
- [extensions.md](../extensions.md) — if a component is not in the catalog
