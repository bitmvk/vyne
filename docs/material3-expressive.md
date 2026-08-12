# Material 3 Expressive components

Vyne implements the complete 36-family Material 3 component catalog as
Python-owned composites. Components lower to the existing `Box`, `Layout`,
`Text`, `TextInput`, `Canvas`, and other renderer primitives; there are no new
Material-specific Kotlin view kinds or state machines.

Import widgets from `vyne_material` (the `vyne-material` distribution):

Install the distribution into the same environment as `vyne`:

```bash
uv add vyne-material
```

```python
from vyne import Column, state
from vyne_material import Button, Checkbox, Slider, TextField


def Settings():
    accepted = state(False)
    volume = state(0.5)
    name = state("")

    return Column(
        TextField(
            value=name.value,
            label="Name",
            on_text_change=name.set,
        ),
        Checkbox(
            accepted.value,
            label="Accept terms",
            on_change=accepted.set,
        ),
        Slider(
            volume.value,
            minimum=0,
            maximum=1,
            step=0.05,
            on_change=volume.set,
        ),
        Button("Save", on_click=lambda: save(name.value)),
    )
```

Components use controlled values: Python owns `checked`, `selected`, `value`,
`visible`, `expanded`, picker dates/times, carousel indices, and progress.
Callbacks receive the proposed next Python value. This keeps policy and state
in Python and makes initial rendering and later updates use the same path.

## Catalog coverage

| Material catalog family | Vyne API |
|---|---|
| App bars | `TopAppBar`, `BottomAppBar` |
| Badges | `Badge`, `Badged` |
| Bottom sheets | `BottomSheet` |
| Button groups | `ButtonGroup`, `ButtonGroupItem` |
| Buttons | `Button` (`filled`, `tonal`, `elevated`, `outlined`, `text`; five Expressive sizes) |
| Cards | `Card` (`elevated`, `filled`, `outlined`) |
| Carousel | `Carousel` |
| Checkbox | `Checkbox` (checked and indeterminate) |
| Chips | `Chip` (`assist`, `filter`, `input`, `suggestion`) |
| Date pickers | `DatePicker`, `DateRangePicker` |
| Dialogs | `Dialog` |
| Divider | `MaterialDivider` |
| Extended FAB | `ExtendedFloatingActionButton` |
| FAB menu | `FloatingActionButtonMenu`, `FabMenuItem` |
| Floating action button | `FloatingActionButton` |
| Icon buttons | `IconButton` (`standard`, `filled`, `tonal`, `outlined`) |
| Lists | `MaterialList`, `ListItem` (one-, two-, and three-line) |
| Loading indicator | `LoadingIndicator` |
| Menus | `Menu`, `MenuItem` |
| Navigation bar | `NavigationBar` (standard and short) |
| Navigation drawer | `NavigationDrawer` |
| Navigation rail | `NavigationRail` (collapsed and expanded) |
| Progress indicators | `CircularProgressIndicator`, `LinearProgressIndicator`, `LinearWavyProgressIndicator` |
| Radio button | `RadioButton` |
| Search | `SearchBar` (collapsed and expanded results) |
| Segmented buttons | `SegmentedButton`, `SegmentedButtonGroup` |
| Side sheets | `SideSheet` |
| Sliders | `Slider`, `RangeSlider` |
| Snackbar | `Snackbar` |
| Split button | `SplitButton` |
| Switch | `Switch` |
| Tabs | `Tab`, `Tabs` (primary and secondary) |
| Text fields | `TextField` (`filled`, `outlined`, supporting/error/prefix/suffix/icon slots) |
| Time pickers | `TimePicker` (12/24 hour, hour/minute dial selection) |
| Toolbars | `Toolbar`, `FloatingToolbar` (horizontal and vertical) |
| Tooltips | `Tooltip` (plain and rich) |

## Theme tokens

Every component accepts a `theme=MaterialTheme(...)` argument. A theme bundles
`ColorScheme`, `Typography`, and `ShapeScale`; components resolve these Python
values to primitive props before reconciliation.

```python
from dataclasses import replace
from vyne_material import Button, DEFAULT_THEME

brand = replace(
    DEFAULT_THEME,
    colors=replace(DEFAULT_THEME.colors, primary="#006A6A"),
)

Button("Continue", theme=brand)
```

## Current native-protocol boundaries

The Kotlin renderer stays mechanical; component behavior remains Python-owned.

- Sliders use horizontal pointer-axis capture, so an initially horizontal drag
  remains attached despite vertical finger jitter while an initially vertical
  gesture scrolls the parent. Pointer moves use `latest(handler)` delivery to
  discard obsolete queued positions. Thumb and track geometry track the
  controlled value directly; continuous/discrete value calculation,
  range-thumb selection, and step snapping remain Python-owned.
- Switch handles snap between the 16 dp off and 24 dp on geometry. Python
  owns the geometry and supplies static numeric Canvas targets; the native
  Canvas only draws them. There is no separate oversized pressed-handle
  phase.
- Carousel currently uses controlled previous/next actions; swipe selection is
  not yet implemented on top of the generic pointer events.
- Sheets are controlled and dismissible; drag-to-expand/dismiss and velocity
  interpretation are not yet implemented.
- Indeterminate/loading animation is controlled through `phase`; autonomous,
  repeating host animation needs repeat/timeline protocol support.
- Tooltips use controlled visibility and long press. Hover events are not in
  the protocol.
- The renderer exposes a basic accessibility label only. Roles, checked/
  selected/expanded semantics, traversal grouping, and live regions need
  native accessibility props.
- Variable font weight/width, input type/password configuration, IME options,
  and press-time shape morphing are not renderer properties today.

All other component selection, visibility, picker, menu, navigation, text,
action, and controlled-state behavior is implemented in Python.
