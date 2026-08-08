# Vyne Canonical UI Specification

Status: design baseline for future platform work. This document does not
change or promise current Android behavior.

Version: draft 1

## 1. Purpose

This specification defines the smallest platform-neutral UI model that Vyne
applications should compile into. Android, iOS, desktop, or any future host can
implement this model without importing another platform's widget hierarchy or
layout terminology.

The intended pipeline is:

```text
Public Python API and user components
                ↓
       canonical lowering
                ↓
 Canonical element tree described here
                ↓
 reconciliation and operation protocol
                ↓
  Android, iOS, or another native host
```

The public API may contain convenient widgets such as `Row`, `Column`,
`Divider`, `Path`, `Button`, or `Card`. Those do not all need corresponding
native renderer kinds. They can lower into the small primitive set in this
document.

The words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY describe requirements for
a conforming future implementation. They do not retroactively describe every
detail of the current Android implementation.

## 2. Design principles

1. Python owns application state, component execution, element identity,
   reconciliation, and event-handler registration.
2. The host owns native objects, measurement, drawing, input delivery,
   accessibility integration, focus, keyboard integration, and animation
   frames.
3. The canonical tree contains data only. It never contains a Java, Kotlin,
   Swift, Objective-C, UIKit, or Android View object.
4. The common API describes behavior rather than native implementation types.
5. Unsupported canonical properties MUST produce a clear error. A host MUST
   NOT silently ignore them.
6. Platform-only behavior is namespaced and is not part of the portable core.
7. Public convenience widgets are lowered before reconciliation whenever
   practical, so every host receives the same canonical tree.

## 3. Canonical element model

Every canonical element has this logical shape:

```text
Element {
    kind: string
    key: optional stable sibling key
    props: string-keyed canonical values
    listeners: event-name → handler ID
    children: ordered list of Elements
}
```

Rules:

- Elements are immutable descriptions. Native state is not stored in them.
- `kind` MUST be one of the required primitive kinds in section 7.
- `key` is local to a sibling list. Two siblings MUST NOT share a key.
- An element without a key is reconciled by position and kind.
- Event callbacks remain in Python. Only integer handler IDs cross the native
  boundary.
- Property values crossing the boundary MUST be null, boolean, finite number,
  string, array, or string-keyed object composed from those types.
- Removing a property resets it to the canonical default defined by this
  specification, not an arbitrary platform default.
- A leaf primitive MUST reject children.

## 4. Canonical value conventions

### 4.1 Logical lengths

All layout lengths use platform-independent logical units:

- Android: one logical unit maps to one density-independent pixel (`dp`).
- iOS: one logical unit maps to one point (`pt`).
- Hosts MUST perform pixel rounding only at the native layout/drawing boundary.
- Values MUST be finite. Negative values are allowed only where a property
  explicitly permits them, such as translation.

Font sizes use scaled text units. Android should map them to `sp`; iOS should
map them to points and apply the framework's chosen Dynamic Type policy. The
font-scaling policy must eventually be an explicit app or element option rather
than an accidental host default.

### 4.2 Dimension values

A dimension is one of:

```text
number   fixed logical length
"auto"   size from content and constraints
"fill"   consume the available size offered by the parent
```

The default for `width` and `height` is `"auto"`. The root element is offered
the safe viewport and is treated as `fill` in both dimensions unless the app
explicitly chooses otherwise.

Percentages are intentionally excluded from the minimal contract. They may be
added later without changing the meaning of the initial values.

### 4.3 Logical edges

Horizontal directional edges are named `start` and `end`, not `left` and
`right`. A host resolves them using the effective layout direction. Physical
left/right coordinates are used only by Canvas drawing commands.

### 4.4 Colors

The canonical string formats are:

```text
#RRGGBB
#RRGGBBAA
```

Alpha is last, following the CSS convention. Color parsing MUST NOT depend on
the native platform's preferred byte order. Named colors are not part of the
minimal contract.

### 4.5 Other numeric conventions

- Opacity is a finite number from `0` through `1`.
- Angles are clockwise degrees.
- Animation durations are non-negative integer milliseconds.
- Scale values are unitless and default to `1`.
- Canvas coordinates use the Canvas view-box coordinate system.

## 5. Common properties

These properties are available to every primitive unless the primitive states
otherwise.

### 5.1 Identity and layout

| Property | Type | Default | Meaning |
|---|---|---:|---|
| `key` | hashable Python value | none | Stable identity among siblings; not transported as a native prop. |
| `width` | dimension | `auto` | Outer width. |
| `height` | dimension | `auto` | Outer height. |
| `min_width` | number | `0` | Minimum width. |
| `min_height` | number | `0` | Minimum height. |
| `max_width` | number or null | null | Maximum width. |
| `max_height` | number or null | null | Maximum height. |
| `margin_top` | number | `0` | Top outer spacing. |
| `margin_bottom` | number | `0` | Bottom outer spacing. |
| `margin_start` | number | `0` | Logical start outer spacing. |
| `margin_end` | number | `0` | Logical end outer spacing. |
| `flex_grow` | number | `0` | Share of positive remaining space on a Layout's main axis. |
| `flex_shrink` | number | `0` | Share of overflow removed on a Layout's main axis. |
| `flex_basis` | dimension | `auto` | Initial main-axis size before grow/shrink. |
| `align_self` | alignment or null | null | Overrides the parent Layout's `align_items` for this child. |

Margins do not collapse. A negative margin is outside the minimal contract.

### 5.2 Padding and safe area

| Property | Type | Default | Meaning |
|---|---|---:|---|
| `padding` | number | `0` | Base padding on every edge. |
| `padding_top` | number or null | null | Overrides the top component of `padding`. |
| `padding_bottom` | number or null | null | Overrides the bottom component of `padding`. |
| `padding_start` | number or null | null | Overrides the logical start component. |
| `padding_end` | number or null | null | Overrides the logical end component. |
| `safe_area` | boolean | `false` | Adds native safe-area insets to the resolved padding. |

Safe-area insets are additive. They do not replace explicit padding.

### 5.3 Appearance

| Property | Type | Default | Meaning |
|---|---|---:|---|
| `background_color` | color or null | transparent | Solid background. |
| `opacity` | number | `1` | Opacity of the element and its rendered subtree. |
| `visible` | boolean | `true` | When false, the element is not drawn and consumes no layout space. |
| `overflow` | `visible` or `hidden` | `hidden` for containers | Whether descendants may draw outside the element bounds. |
| `corner_radius` | number | `0` | Radius for all corners. |
| `corner_radius_top_start` | number or null | null | Logical top-start override. |
| `corner_radius_top_end` | number or null | null | Logical top-end override. |
| `corner_radius_bottom_start` | number or null | null | Logical bottom-start override. |
| `corner_radius_bottom_end` | number or null | null | Logical bottom-end override. |
| `border_width` | number | `0` | Border drawn inside the element bounds. |
| `border_color` | color or null | transparent | Border color. |

Portable shadows should eventually use an explicit structure containing color,
opacity, blur radius, and x/y offset. Android `elevation`, `translation_z`, and
ripple configuration are not canonical common properties.

### 5.4 Interaction and focus

| Property | Type | Default | Meaning |
|---|---|---:|---|
| `enabled` | boolean | `true` | Whether interaction handlers may activate. |
| `focusable` | boolean | primitive-specific | Whether the element can receive input focus. |
| `focused` | boolean or null | null | Optional controlled focus state for focusable controls. |
| `hit_test` | `auto`, `none`, or `box_only` | `auto` | Pointer/touch hit-testing policy. |
| `pointer_capture_axis` | `horizontal`, `vertical`, or null | null | Wait for touch slop, then retain a gesture whose initial dominant movement matches this axis; otherwise release it to the parent. |

Setting `enabled=false` does not imply `visible=false`. Disabled elements remain
in layout and accessibility unless explicitly hidden.

### 5.5 Transforms

| Property | Type | Default | Meaning |
|---|---|---:|---|
| `translation_x` | number | `0` | Post-layout horizontal translation. |
| `translation_y` | number | `0` | Post-layout vertical translation. |
| `scale_x` | number | `1` | Horizontal scale around the element anchor. |
| `scale_y` | number | `1` | Vertical scale around the element anchor. |
| `rotation` | number | `0` | Clockwise planar rotation in degrees. |

Transforms affect drawing and hit testing but do not cause sibling reflow.
Three-dimensional platform transforms are outside the minimal contract.

## 6. Accessibility contract

**Note:** The current Android implementation supports a subset of these
props (marked ✅).  The remaining props are design targets for future
platform work.

Native primitives MUST expose their natural accessibility behavior. Composite
controls MUST be able to provide equivalent semantics through common props.

| Property | Type | Default | Meaning |
|---|---|---:|---|
| `accessibility_label` | string or null | inferred | [planned] Spoken label. |
| `accessibility_hint` | string or null | null | [planned] Additional usage hint. |
| `accessibility_value` | string or null | inferred | [planned] Current human-readable value. |
| `accessibility_role` | role or null | inferred | Semantic role. |
| `accessibility_hidden` | boolean | `false` | [planned] Removes this subtree from accessibility traversal. |
| `accessibility_checked` | boolean | `false` | Checkbox/switch toggle state (true=checked). |
| `accessibility_selected` | boolean | `false` | Selection state. |
| `accessibility_expanded` | boolean or null | null | [planned] Expanded/collapsed state. |
| `accessibility_state_description` | string or null | null | Additional state description for accessibility. |

The initial role vocabulary is:

```text
none, text, image, button, link, header, text_input,
checkbox, switch, radio, list, list_item, tab, slider
```

Range properties for sliders/progress indicators:

| Property | Type | Default | Meaning |
|---|---:|---|
| `accessibility_range_min` | number | `0` | Minimum range value. |
| `accessibility_range_max` | number | `0` | Maximum range value. |
| `accessibility_range_current` | number | `0` | Current range value. |

The Android compatibility name `content_description` maps to
`accessibility_label`; it is not the canonical cross-platform name.

## 7. Required renderer primitives

A minimal conforming host implements exactly these seven required kinds:

```text
Box
Layout
Scroll
Text
TextInput
Image
Canvas
```

Everything else can be built from these primitives. A host may implement
optimized additional kinds, but portable application behavior must not require
them.

### 7.1 `Box`

Purpose: general visual surface and overlay container.

```python
Box(*children, **common_props)
```

Contract:

- Accepts zero or more children.
- Children occupy the Box content region and may overlap.
- Default child placement is logical top-start.
- The Box size is resolved from explicit constraints and the union of its
  non-positioned children's measured bounds.
- Padding reduces the child content region.
- Background, border, corners, clipping, interaction, and accessibility use the
  common properties.
- A Box with no children is the canonical blank visual primitive. A separate
  native `View` kind is unnecessary.

An optional future child-positioning model may add logical top/end/bottom/start
insets. It should not alter the default overlay behavior.

### 7.2 `Layout`

Purpose: one-dimensional ordered layout. `Row` and `Column` lower to it.

```python
Layout(
    *children,
    orientation="horizontal" | "vertical",
    align_items="stretch",
    justify_content="start",
    **common_props,
)
```

Additional props:

| Property | Type | Default | Meaning |
|---|---|---:|---|
| `orientation` | `horizontal` or `vertical` | required | Main axis. |
| `gap` | number | `0` | [planned] Spacing between adjacent children. Use `margin` props for now. |
| `align_items` | alignment | `stretch` | Default cross-axis child alignment. |
| `justify_content` | distribution | `start` | Placement of the child group or remaining main-axis space. |

Alignment values:

```text
start, center, end, stretch
```

Distribution values:

```text
start, center, end, space_between, space_around, space_evenly
```

Layout algorithm requirements:

1. Resolve padding and available content size.
2. Measure non-flex and flex-basis sizes.
3. Add margins (and gaps, when implemented).
4. Distribute positive remaining main-axis space by `flex_grow`.
5. Resolve overflow by `flex_shrink` when enabled.
6. Position the group using `justify_content`.
7. Resolve each child's cross-axis position using `align_self` or
   `align_items`.

Hosts may use native stacks, constraints, or a custom layout engine, but the
observable result should follow these semantics.

### 7.3 `Scroll`

Purpose: native scrollable viewport.

```python
Scroll(
    content=None,
    axis="vertical" | "horizontal" | "both",
    shows_indicators=True,
    **common_props,
)
```

Contract:

- Accepts zero or one canonical child.
- Public APIs may accept multiple children by lowering them into one `Layout`.
- `axis` defaults to `vertical`.
- The viewport follows normal parent constraints. The content may exceed the
  viewport along enabled axes.
- Native momentum, touch arbitration, overscroll, and accessibility scrolling
  should follow platform conventions.
- Programmatic scroll position and scroll events may be added later using
  logical coordinates; they are not required for the first minimal renderer.

### 7.4 `Text`

Purpose: read-only native Unicode text.

```python
Text(
    text,
    color=None,
    font_size=None,
    font_weight="normal",
    line_height=None,
    max_lines=None,
    text_align="start",
    overflow="clip" | "ellipsis",
    selectable=False,
    **common_props,
)
```

Contract:

- Accepts no children.
- `text` is required and is converted to a Unicode string before transport.
- Intrinsic measurement includes the resolved font, line height, wrapping,
  line limit, and offered width.
- `max_lines=None` means no explicit line limit.
- `text_align` uses logical `start` and `end`.
- Font fallback follows native platform behavior unless Vyne later supplies a
  bundled-font policy.
- Android-only font-padding switches are platform overrides, not canonical
  Text props.

Current Vyne names such as `text_color` and `text_alignment` may remain public
compatibility aliases for `color` and `text_align`.

### 7.5 `TextInput`

Purpose: native editable text control with keyboard, selection, focus, and IME
integration.

```python
TextInput(
    text="",
    placeholder="",
    multiline=False,
    secure=False,
    keyboard_type="text",
    return_key="default",
    on_text_change=None,
    on_submit=None,
    on_focus_change=None,
    **common_props,
)
```

Contract:

- Accepts no children.
- `text` is controlled: the Python value is authoritative after an event is
  processed.
- User edits emit `text_change` with the complete current text.
- A host MUST avoid resetting native text and selection when Python returns the
  same value that originated the event.
- `placeholder` has no value semantics and is not emitted as text.
- `secure=true` requests native obscured-entry behavior.
- `multiline=false` uses a single-line control; `true` uses a multiline editor.
- Focus and software-keyboard operations occur on the native UI thread.
- Native submit/return actions emit `submit` when appropriate.

The current names `hint` and `on_editor_action` may remain compatibility aliases
for `placeholder` and `on_submit`.

### 7.6 `Image`

Purpose: native image display.

```python
Image(
    source,
    content_mode="contain" | "cover" | "center" | "stretch",
    **common_props,
)
```

Canonical sources are structured values:

```python
{"kind": "asset", "name": "logo"}
{"kind": "uri", "uri": "https://example.invalid/image.png"}
```

Contract:

- Accepts no children.
- Asset names are logical names. Android drawable names and iOS asset-catalog
  names are host mappings, not values embedded in application code.
- `contain` preserves aspect ratio and fits inside the content region.
- `cover` preserves aspect ratio and fills the region, cropping overflow.
- `center` preserves intrinsic size and centers the image.
- `stretch` fills both axes without preserving aspect ratio.
- URI loading, caching, failure, and placeholders require a defined image
  loader. A first minimal host may support asset sources only and must report a
  capability error for unsupported source kinds.

The current string `source` can lower to `{"kind": "asset", "name": source}`.
The current scale names `fit_center`, `center_crop`, and `center_inside` can
lower to `contain`, `cover`, and `center`.

### 7.7 `Canvas`

Purpose: retained, declarative 2D vector display list.

```python
Canvas(
    draw=[...],
    view_box=[x, y, width, height],
    **common_props,
)
```

Contract:

- Accepts no children.
- `draw` is an ordered list. Later operations paint over earlier operations.
- `view_box` defines logical drawing coordinates. Its width and height must be
  positive.
- The view box is uniformly scaled and centered using `contain` behavior unless
  a future explicit fit mode says otherwise.
- Numeric drawing fields such as path `trim_start` and `trim_end` can use
  `Animated.Value` expressions for retained, native-frame animation.
- Drawing is retained: Python sends a display list, while native code performs
  actual drawing and animation frames.

Required drawing operations:

```text
rect
round_rect
circle
line
path
```

Shared paint fields:

| Field | Type | Default |
|---|---|---:|
| `fill` | color or null | null |
| `stroke` | color or null | null |
| `stroke_width` | number | `1` |
| `stroke_cap` | `butt`, `round`, `square` | `butt` |
| `stroke_join` | `miter`, `round`, `bevel` | `miter` |
| `dash` | array of positive numbers or null | null |
| `dash_offset` | number | `0` |
| `opacity` | number | `1` |

Geometry fields:

```text
rect:       x, y, width, height
round_rect: x, y, width, height, radius
circle:     cx, cy, radius
line:       x1, y1, x2, y2
path:       commands
```

Required path commands are `M`, `L`, `C`, `Q`, and `Z`, plus their relative
lowercase forms. Commands are precompiled in Python into numeric arrays before
transport.

## 8. Public composites and lowering

These are useful public APIs but do not require native renderer kinds.

| Public widget | Canonical lowering |
|---|---|
| `Row(*children)` | `Layout(*children, orientation="horizontal")` |
| `Column(*children)` | `Layout(*children, orientation="vertical")` |
| `Divider(...)` | A childless `Box` with fixed width or height and background color. |
| `Spacer(...)` | A transparent childless `Box`, commonly with `flex_grow`. |
| `Path(...)` | A `Canvas` containing one `path` operation. |
| `Icon(...)` | `Image` for assets or `Canvas` for vector data. |
| `Card(...)` | Styled `Box`. |
| `Button(...)` | Interactive `Box` containing content, with button accessibility semantics. |
| `Checkbox(...)` | Interactive `Box`/`Layout` plus Canvas mark and checked accessibility state. |
| `List(...)` | `Scroll` containing a vertical `Layout`. Virtualization may later add an optimized primitive. |

A host MAY recognize and optimize a composite, but the optimized result must
preserve the canonical props, events, accessibility, and identity semantics.

## 9. Style and decoration lowering

`Style`, `Decoration`, `Fill`, `Stroke`, and similar Python objects are
source-level typed helpers. Native hosts should not need to decode Python class
shapes.

Before reconciliation, styling should lower into canonical element props:

```python
Text(
    text="Title",
    style=Style(color="#112233", font_size=24),
    opacity=0.8,
)
```

Conceptually becomes:

```python
Text(
    text="Title",
    color="#112233",
    font_size=24,
    opacity=0.8,
)
```

Rules:

- Explicit constructor props override values supplied by `style`.
- Style composition is resolved in Python before diffing.
- A native host receives only canonical props.
- Solid fills, borders, and corner radii use the common appearance props.
- Gradients, rich shadows, and press feedback require separately versioned
  canonical structures before becoming portable guarantees.
- Android ripple/elevation and iOS-specific layer options belong in namespaced
  platform overrides until a common semantic model exists.

## 10. Event model

Canonical native events have this logical shape:

```text
Event {
    sequence: monotonically increasing integer
    target: canonical node ID
    name: canonical event name
    handler: Python handler ID
    payload: string-keyed canonical object
}
```

Required events:

| Public callback | Native event | Payload | Meaning |
|---|---|---|---|
| `on_press` | `press` | `{}` | Primary activation completed. |
| `on_long_press` | `long_press` | `{}` | Sustained activation recognized. |
| `on_focus_change` | `focus_change` | `{"has_focus": bool}` | Focus changed. |
| `on_text_change` | `text_change` | `{"text": str}` | User changed TextInput text. |
| `on_submit` | `submit` | `{"text": str}` | TextInput submit/return action. |

Low-level pointer callbacks use density-independent coordinates and retain the
gesture origin and session identity in every payload:

| Public callback | Native event | Payload |
|---|---|---|
| `on_pointer_down` | `pointer_down` | `{"x": float, "y": float, "down_x": float, "down_y": float, "pointer_id": int, "gesture_id": int}` |
| `on_pointer_move` | `pointer_move` | Same pointer payload. |
| `on_pointer_up` | `pointer_up` | Same pointer payload. |
| `on_pointer_cancel` | `pointer_cancel` | Same pointer payload. |

These callbacks expose coordinates only. Gesture meaning, value conversion,
step snapping, and component state remain Python-owned. With
`pointer_capture_axis`, native touch slop and parent interception arbitrate the
initial direction; a matching direction stays captured for the rest of that
gesture even if later movement drifts across the other axis. A rejected axis
does not deliver a component pointer-down event.

High-frequency replaceable callbacks may opt into `latest(handler)`. Native
delivery keeps at most the newest pending event for the same target, event,
handler, and gesture while one Python batch is in flight. The active handler is
not interrupted, non-latest events remain ordered, and render commits are never
cancelled or skipped.

Current compatibility mappings may be maintained:

```text
on_click         → on_press
click            → press
on_long_click    → on_long_press
long_click       → long_press
on_editor_action → on_submit
editor_action    → submit
```

Event requirements:

- Native listeners MUST suppress events caused only by applying a Python
  commit.
- Events from removed nodes are ignored safely.
- Events may be batched in native sequence order.
- State changes produced by one event batch should result in at most one
  reconciliation commit.
- The native host should preserve platform-standard gesture cancellation and
  scroll arbitration.

## 11. Reconciliation and host operations

Python component scopes MAY cache their last canonical element output. A state
cell owned by an explicit component scope invalidates that scope rather than
the application root. The runtime then validates and reconciles the scope's
output directly against its existing native subtree. Unchanged cached output
MUST retain its handler registrations and MAY skip recursive validation and
diff traversal.

Component calls and state hooks are matched by stable call order within their
owning scope. Changing a component argument invalidates that component during
its parent's render. Removing a component scope releases its hooks and event
handlers; subsequent updates through a stale state reference have no effect.

The current Vyne operation model is suitable as the canonical host mutation
model:

```text
clear
create
set_props
set_prop
remove_prop
listen
listen_latest
unlisten
insert_child
move_child
remove_child
remove
motion_set_target
motion_cancel
motion_driver_set_target
motion_driver_cancel
```

Requirements:

- Node ID `0` is the host root and is never created by Python.
- `create` allocates an unattached native object for a canonical kind.
- Initial props and listeners may arrive before insertion.
- `insert_child` reparents when necessary and inserts at the requested index.
- `move_child` preserves native object identity.
- `remove` releases listeners, animations, native references, and descendants.
- Operations are applied in message order on the native UI thread.
- A failed operation should report the operation, kind, property, and host
  platform rather than continuing with a partially unknown state.

The logical operation contract is host-independent. Android receives typed
operations directly; another host can implement the same transaction model
without inheriting an Android-specific transport.

## 12. Animation contract

Animations are declarative commands executed entirely by the native host.
Python does not receive per-frame callbacks.

Animation commands share the ordered reconciliation commit which establishes
their node and logical target. The host MUST preflight the complete command and
MUST NOT start, replace, or cancel presentation work until every tree mutation
in that commit succeeds. A commit acknowledgement means the command was
accepted; it does not mean the timeline finished.

Minimal animatable props:

```text
opacity
translation_x
translation_y
scale_x
scale_y
rotation
Canvas drawing numeric fields
```

An animation contains:

```text
animation ID
target node ID
property
optional from value
one or more destination values
duration in milliseconds
easing
```

The destinations form one native timeline. They MUST NOT be lowered to
multiple target commands in the same commit, because later commands would
replace earlier ones before a display frame could present them. Tween duration
is per destination segment.

Required easings:

```text
linear, ease_in, ease_out, ease_in_out
```

`overshoot` and `bounce` may be supported, but exact native curves differ. If
cross-platform visual equivalence is important, their mathematical curves must
be specified rather than delegated to platform presets.

`Animated.spring(value, to=..., damping_ratio=..., stiffness=...)` describes a
generic spring. Python owns the parameters and component-specific targets.
Retained View and Canvas fields integrate the spring until rest and preserve
velocity when retargeted.

Only one animation may control a `(node, property)` pair at a time. Starting a
new one cancels or replaces the old one. If `from` is omitted, animation begins
at the native presentation value currently visible to the user.

Imperative animations have monotonically allocated IDs. Cancellation includes
the ID as well as the presentation slot, so a delayed handle cannot cancel a
newer replacement. On completion, cancellation, replacement, node removal, or
disposal, native may send an ordered lifecycle event containing the animation
ID, slot identity, terminal status, and reason. Lifecycle callbacks use the
normal synchronous/async event scheduler and any state they change is published
in a later commit.

The public API has two layers:

- `animate(target, x=..., y=..., scale=..., opacity=..., ...)` is the immediate
  API for one-off interactions. It needs no persistent value. Multiple named
  properties start together; numeric sequences are native keyframes.
- `Animated.Value(initial)` creates a persistent advanced driver.
  `Animated.timing()` and `Animated.spring()` create animation plans, while
  `Animated.parallel()` and `Animated.sequence()` compose them. Arithmetic,
  `clamp()`, and `interpolate()` create immutable derived expressions.

An advanced driver is independent of a presentation slot. One driver command
may update any number of View props and Canvas fields whose expressions
reference that driver. The host evaluates the expression graph and writes all
bound presentation slots on the same native frame. Python is involved only
when starting, retargeting, composing, or receiving a terminal lifecycle
event.

The older `AnimatedValue(target, duration=..., easing=..., retarget=...)`
surface remains a compatibility API. Its first target snaps into place;
subsequent target changes animate from the current presentation value.
`retarget="maintain_velocity"` carries the current derivative into a
replacement tween; tween defaults to `"restart"` and spring defaults to
`"maintain_velocity"`. Canvas drawing topology must remain stable across
target changes; non-animated drawing fields update immediately.

A host MUST NOT restart a Canvas animation clock at zero for every value in a
continuous target stream. It should retain one frame clock, advance the live
value before accepting a new target, and either adapt restarting transitions to
the observed update cadence or preserve the derivative when requested.
Isolated compatibility targets continue to use their declared duration and
easing. Velocity-preserving tweens match the current presentation velocity to
the measured target-stream velocity. Both tangents are bounded by the segment
slope so rapid input and direction reversal cannot overshoot the logical
target. Spring targets preserve their live value and velocity by default when
interrupted.

Once a command is accepted, the native display clock is the sole frame
scheduler. Python may await, process unrelated callbacks, or remain unavailable
for multiple frames without stopping the active timeline. Python remains the
owner of logical destination state; native remains the owner of the currently
visible presentation value.

## 13. Platform overrides

Platform overrides are escape hatches, not common props:

```python
Text(
    text="Example",
    android={"include_font_padding": False},
    ios={"adjusts_font_for_content_size": True},
)
```

Rules:

- Platform override objects are namespaced by platform.
- A host ignores override namespaces belonging to other platforms.
- An unknown property inside the active platform namespace is an error.
- Portable composites MUST NOT depend on an override for their fundamental
  behavior.
- Common props always define the fallback semantics.

## 14. Native host mapping guidance

The mapping is intentionally non-normative; observable behavior, not native
class choice, defines conformance.

| Canonical kind | Android candidate | iOS candidate |
|---|---|---|
| `Box` | `FrameLayout` or custom `ViewGroup` | `UIView` |
| `Layout` | custom linear `ViewGroup` or `LinearLayout` | custom `UIView` layout or `UIStackView` wrapper |
| `Scroll` | `ScrollView`/horizontal equivalent | `UIScrollView` |
| `Text` | `TextView` | `UILabel` |
| `TextInput` | `EditText` | `UITextField`/`UITextView` |
| `Image` | `ImageView` | `UIImageView` |
| `Canvas` | custom `View`/`Canvas` | custom `UIView`/Core Graphics/CAShapeLayer |

An iOS implementation should normally use UIKit for this operation-driven
architecture. SwiftUI may be used inside specialized components, but making it
own the canonical tree would duplicate Vyne's existing identity and
reconciliation responsibilities.

## 15. Capability and version rules

Every host must expose or embed:

```text
UI specification version
operation protocol version
supported optional capabilities
active platform and platform version
```

Rules:

- All seven required primitive kinds are mandatory for UI spec version 1.
- Missing required kinds or props fail during startup, not after a screen is
  partially rendered.
- Adding an optional prop or drawing operation is a compatible extension.
- Changing an existing default or semantic meaning requires a UI spec version
  change.
- Platform-specific behavior does not change the common spec version.
- Python and the native host bundled into one application should still perform
  a version check to catch packaging mismatches.

## 16. Conformance suite requirements

A future second host should be developed against shared fixtures rather than
the Android implementation alone.

The conformance suite should include:

1. Canonical lowering fixtures for every public composite.
2. Create/update/remove/reparent operation traces.
3. Keyed and unkeyed reconciliation traces.
4. Required/default/removed property behavior.
5. Layout fixtures for fixed, auto, fill, margins, padding, gaps, flex, RTL,
   safe areas, and nested constraints.
6. Text measurement fixtures with explicit fonts and widths where feasible.
7. Controlled TextInput event-and-commit round trips.
8. Event ordering, batching, and removed-handler cases.
9. Canvas display-list fixtures and reference images.
10. Accessibility tree assertions.
11. Animation unit and replacement tests.
12. Cross-language logical transaction fixtures.

Pixel-perfect equality is not required where native text rasterization differs,
but layout bounds, semantic state, event payloads, and protocol behavior should
be deterministic within documented tolerances.

## 17. Current Vyne compatibility summary

The current public surface can fit this model without discarding its central
architecture:

| Current concept | Canonical role |
|---|---|
| `Element` | Canonical immutable UI description. |
| `Box` | Required primitive. |
| `Layout` | Required primitive. |
| `Row` / `Column` | Public composites lowering to Layout. |
| `Scroll` | Required primitive; multiple public children lower through Column. |
| `Text` | Required primitive. |
| `TextInput` | Required primitive. |
| `Image` | Required primitive with future structured source lowering. |
| `Canvas` | Required primitive. |
| `Path` | Public convenience or optional optimized primitive; canonical fallback is Canvas. |
| `Divider` | Public composite lowering to Box. |
| `View` | Compatibility renderer kind; unnecessary in the minimal future set. |
| `Style` and decorations | Python-side typed helpers lowered to canonical props. |
| state and keyed diffing | Platform-independent runtime behavior. |
| direct commits and event batches | Platform-independent logical transactions with typed host adapters. |
| native-driven animation | Shared model with platform-specific animation engines. |

This boundary allows the Android renderer to continue evolving now while
preserving a sufficiently precise target for an iOS host later.
