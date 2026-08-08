# Animation: The Python API

Sources: `vyne/animations.py`, `vyne/motion.py`.

## PresentationSlot

A stable identity for one animatable property.

- View property: `node_id` + property name (e.g. `"opacity"`)
- Canvas field: `node_id` + stable op id + dot-path field
  (e.g. `fill.color.alpha`)

Wire key:

```text
view:<node>:prop:<prop>              # View property
view:<node>:slot:<op_id>:<field>     # Canvas field
driver:<driver_id>                   # persistent driver
```

The Kotlin engine matches commands to active transitions by this key.

## Animatable View properties

```text
elevation, height, opacity, rotation, rotation_x, rotation_y,
scale_x, scale_y, stroke_dash_offset, translation_x, translation_y, width
```

Aliases: `alpha` -> `opacity`, `x` -> `translation_x`, `y` ->
`translation_y`. In `animate()`, `scale` expands to both scale axes.

## MotionSpec

### Tween

Fixed duration plus a named easing curve.

- easings: `linear`, `ease_in`, `ease_out`, `ease_in_out`, `overshoot`,
  `bounce`
- default retarget: `restart`

### Spring

Damped harmonic oscillator, parameterized by physics.

- `stiffness` (default 380.0)
- `damping_ratio` (default 0.8)
- `rest_value_threshold` (default 0.01)
- `rest_velocity_threshold` (default 0.01)
- default retarget: `maintain_velocity`

## Retarget policies

| policy | behavior when retargeted |
|---|---|
| `restart` | start from the retarget point (implicit from-value) |
| `maintain_velocity` | carry current velocity into the new spec |
| `snap_to_end` | jump to the current target, then start the new animation |
| `ignore` | let the current animation finish |

## animate()

```python
animate(
    target,                # int view id | Ref | ViewHandle
    x=80, y=-8, scale=[0.96, 1.0],   # named destinations
    duration=90,           # per keyframe segment
    easing="ease_out",
    retarget="maintain_velocity",
    on_complete=..., on_cancel=...,
)
```

- targets must be a mounted view; stale handles raise
- named properties start together and return one group handle
- `to=`/`from_=` mapping forms supported
- the legacy positional form `animate(ref, "opacity", to=1.0)` remains
  supported
- keyframes are one native timeline, not a series of replacing commands

Returns `AnimationHandle` (one property) or `AnimationGroupHandle`
(several). Both are generation-safe.

## Handles

- `AnimationHandle` — status (`queued`/`running`/`completed`/`cancelled`/
  `rejected`), `cancel()`, `done`
- `AnimationGroupHandle` — aggregates children; terminal when all
  children are terminal; `stop_together` controls sibling cancellation
- `AnimationSequenceHandle` — plays plans one after another; a child
  completion starts the next plan

## Animated.Value (persistent drivers)

```python
progress = Animated.Value(0.0)
width = progress.interpolate([0, 1], [12, 240], extrapolate="clamp")
opacity = progress.interpolate([0, 1], [0.35, 1.0])

Animated.parallel([
    Animated.timing(progress, to=1.0, duration=420, easing="ease_in_out"),
    Animated.spring(pulse, to=[0.94, 1.0]),
]).start()
```

- `Animated.Value()` is a hook: stable order within its component,
  allocated by the Runtime
- `timing`/`spring` create plans; `parallel`/`sequence` compose them
- `.start()` returns a generation-safe handle
- a driver is animated once; every bound expression is evaluated from the
  same live value each frame
- one driver may drive many View props and Canvas fields

### Expressions

`AnimatedNode` supports:

- arithmetic: `+`, `-`, `*`, `/`, unary `-`
- `interpolate(input_range, output_range, extrapolate="extend"|"clamp"|"identity")`
- `clamp(minimum, maximum)`

Expressions are evaluated natively every frame. Initial values are
computed in Python at creation.

Validation:

- parallel cannot animate the same driver twice
- expressions cannot cross Runtime instances
- results must stay finite

## Legacy AnimatedValue

```python
position = AnimatedValue(72, duration=80, easing="ease_out",
                         retarget="maintain_velocity")
Box(translation_x=position)
```

- target-driven: the first target applies immediately; later targets
  animate from the live displayed value
- arithmetic returns another AnimatedValue with matching motion settings
- supports Canvas fields, retarget policies, and generic springs
  (`easing="spring"`)

## Wire encoding

`AnimatedValue`/`AnimatedNode` lower to protocol markers:

```json
{ "__vyne_animated_value__": true, "value": ..., "duration": ... }
{ "__vyne_animated_node__": true, "value": ..., "expression": {...} }
```

Canvas draw ops carry these markers inline; the Kotlin engine resolves
them through the stable operation identity.

## Related

- [overview.md](overview.md) — lifecycle and ordering
- [native-engine.md](native-engine.md) — what Kotlin does with commands
- [protocol.md](../framework/protocol.md) — motion operation validation
