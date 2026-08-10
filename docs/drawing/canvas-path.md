# Canvas and Path

Sources: `vyne/path_data.py`, `vyne/elements.py` (Path, Canvas),
`vyne/spec/schema_v2.py` (CANVAS_OP_SPECS), `vyne/motion.py`
(CanvasOpIdentity), and the Kotlin `CanvasView.kt` / `PathView.kt`.

## Canvas

`Canvas(draw=[...])` is a declarative 2D drawing surface. The `draw` list
describes drawing operations as JSON dicts.

The public `Canvas()` constructor compiles a **list** of operations
(`_compile_canvas_draw`); canonical storage freezes that list into an
immutable tuple, and the schema value domain accepts both forms so the
lowered tuple validates directly.

### Draw operations

| kind | required fields | extra fields |
|---|---|---|
| `rect` | x, y, width, height | — |
| `round_rect` | x, y, width, height | radius |
| `circle` | cx, cy, r | — |
| `line` | x1, y1, x2, y2 | — |
| `path` | none | d \| commands, trim_start, trim_end |

Shared paint fields (all kinds):

```text
fill, stroke, stroke_width, stroke_cap, stroke_join,
dash, dash_offset, opacity
```

Validation is schema-driven (`validate_canvas_draw_ops`):

- unknown kinds reject
- missing required fields reject
- every field validates against its ValueSpec
- unknown fields reject

`view_box` (`[x, y, width, height]`) scales the display list into the
view. Width and height must be positive.

Path strings inside draw ops (`d`) are compiled to command lists at
Element creation time — malformed input fails fast, off the UI thread.

### Stable operation identity

Canvas animation needs stable identities that survive insert, reorder,
and removal of sibling operations. `CanvasOpIdentity.stabilize()` assigns
each operation a `_vyne_op_id`:

- the id is a content hash (first 12 hex chars) plus an occurrence
  counter: `circle_ab12cd34ef56_0`
- animated markers (`__vyne_animated_node__`) are replaced by a placeholder
  before hashing, so changing a target does not replace the native
  presentation slot
- operations that already carry an id keep it

### Animatable Canvas fields

```text
rect:        x, y, width, height, opacity, stroke_width, dash_offset
round_rect:  + radius
circle:      cx, cy, r, opacity, stroke_width, dash_offset
line:        x1, y1, x2, y2, opacity, stroke_width, dash_offset
path:        trim_start, trim_end, opacity, stroke_width, dash_offset
```

A Canvas field is animated through `PresentationSlot(node_id, field,
slot_id=op_id)` — see [animation/python-api.md](../animation/python-api.md).

## Path

`Path(d="...")` renders an SVG-path-backed vector shape. The `d` string
is compiled at creation time into JSON-safe commands.

### Command grammar

| command | arity | meaning |
|---|---|---|
| `M` / `m` | 2 | move to (absolute / relative) |
| `L` / `l` | 2 | line to |
| `C` / `c` | 6 | cubic bezier curve |
| `Q` / `q` | 4 | quadratic bezier curve |
| `Z` / `z` | 0 | close path |

Each command is a dict `{"cmd": "M", "values": [x, y]}`. Validation checks
the letter, the arity, and that every value is a finite number.

### Stroke and fill props

- `stroke_color`, `stroke_width`, `stroke_line_cap` (butt/round/square),
  `stroke_line_join` (miter/round/bevel)
- `stroke_dash_array` — even-length tuple of positive numbers, or the
  string `"full"` (resolved to `[pathLength, pathLength]` by PathView),
  or a comma string like `"4,8"`
- `stroke_dash_offset` — animatable (marching-ants effect)
- `fill_color`
- `trim_start` / `trim_end` — animate path drawing (0..1)

## Related

- [lowering.md](../framework/lowering.md) — validation and stabilization
- [animation/python-api.md](../animation/python-api.md) — animating fields
- [android-host/registry.md](../android-host/registry.md) — CanvasView / PathView
