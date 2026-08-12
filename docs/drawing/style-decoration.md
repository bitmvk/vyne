# Style and Decoration

Sources: `vyne/style.py`, `vyne/lowering.py`.

## Style

`Style` is a typed value object:

```python
Style(text_color="#172554", font_size=24)
```

Styles compose with `+` — the right side wins:

```python
title = Style(text_color="#172554", font_size=24)
warning = title + Style(text_color="#dc2626")
```

### Supported Style fields

| field | canonical prop |
|---|---|
| `text_color` | text_color |
| `color` (alias) | text_color |
| `background_color` | background_color |
| `font_size` | font_size |
| `padding` | four padding edges |
| `width`, `height` | dimensions |
| `align_items`, `justify_content` | layout (containers) |
| `decoration` | handled separately (below) |

Removed Style fields (`gap`, `size`, `flex`, `flex_grow`, `flex_shrink`,
`flex_basis`, `align_self`) are not part of the API; a raw dict carrying
them rejects with an unknown-field path.

## Decoration

`Decoration` provides native drawable-backed visual chrome:

```python
Decoration.rectangle(
    fill="#ffffff",
    stroke=Stroke(color="#e5e7eb", width=1),
    corners=8,
    shadow=Shadow(elevation=2),
    ripple=Ripple(color="#22000000"),
)
```

The first decoration tier maps to:

- Android shape drawables (fill + stroke + corner radii)
- elevation shadows
- ripple foregrounds
- outline clipping

### Tier mapping

| Decoration field | canonical props |
|---|---|
| solid rectangle fill | `background_color` |
| stroke color / width | `border_color` / `border_width` |
| corner radii | four `corner_radius_*` props |
| `Shadow.elevation` | `elevation` |
| `Ripple.color` | `ripple_color` |

### Rejected features (fail loudly)

- gradients (linear / radial / sweep)
- dashed strokes
- Shape oval / line / ring
- `translation_z`
- unbounded ripple
- `Decoration.clip` — removed from the API; needs a native outline slot,
  planned but not implemented

The removed constructors and fields (`Fill.linear_gradient`/`radial_gradient`/
`sweep_gradient`, `Stroke.dash_width`/`dash_gap`, `Shape.oval`/`line`/`ring`,
`Shadow.translation_z`, `Ripple.bounded`, `Decoration.clip`) no longer exist
on the Python types; raw dicts carrying those keys still reject at lowering.

## Precedence

The lowering merge decides who wins:

```text
kind defaults < Style/Decoration tier < explicit direct props
```

Explicit props always beat Style; Style beats defaults. The ordered merge
never lets `1 == True` hide a malformed value.

See [lowering.md](../framework/lowering.md).

## Related

- [lowering.md](../framework/lowering.md) — the tier system
- [android-host/renderer.md](../android-host/renderer.md) — composite
  background generation
