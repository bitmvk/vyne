# Virtualized lists

> The future extensibility direction is recorded in
> [List building blocks](list-building-blocks.md). It is not part of the current
> fixed-list implementation.

`List` renders a fixed-extent virtualized list: only the items inside the
selected window are composed, everything else is a blank spacer. The native
host keeps scrolling free and reports where the in-flight gesture is heading;
Python plans one contiguous window from the current viewport through the
projected target, so fast flings render their path instead of chasing the
finger.

```python
from vyne import List, ListController

controller = ListController()


def Items():
    return List(
        tuple(range(10_000)),
        render_item=lambda item, index: Text(text=f"Item {item}"),
        item_extent=48,
        key_for_item=lambda item, index: item,
        controller=controller,
        width="match_parent",
        height=400,
    )
```

## Arguments

`data`, `render_item`, and `item_extent` are required. Everything else has a
default:

| argument | default | meaning |
|---|---|---|
| `key_for_item` | item index | `(item, index) -> key` cell identity. Provide it for correct behavior across reorders and resizes, and for rows that hold state. |
| `axis` | `"vertical"` | `"vertical"` or `"horizontal"`. |
| `overscan` | `1.0` | extra window margin in viewports, both sides. |
| `max_render_ahead_viewports` | `0` (unbounded) | caps how far ahead of the viewport the projected window may reach. Default renders the full fling path in one commit (smoothest); a finite cap bounds commit size but makes the window follow in steps during fast flings. |
| `initial_item_count` | `5` | cells to render before native metrics arrive, used only when no numeric main-axis size is declared. |
| `controller` | owned internally | `ListController` for imperative scrolling. One controller drives one mounted list; pass `key=` when sibling lists can reorder. |
| `key` | `None` | list identity for sibling reorder. |
| `**scroll_props` | — | scroll-view props: `height`, `width`, `background_color`, margins, padding, `content_description`, ... |

## Dynamic data

`data` is a plain prop; pass state-derived data to update the list. Changes
are picked up by the next render; keys keep existing cells (and their state)
stable, and the window replans against the new layout.

```python
data = state(tuple(range(100)))

def append():
    data.set(data.value + (len(data.value),))

List(data.value, render_item=..., item_extent=42, key_for_item=lambda item, index: item)
```

Appended items become visible when they enter the mounted window; the list
does not auto-scroll.

## Imperative control

```python
controller.scroll_to_index(500, alignment="center", animated=False)
controller.scroll_to_offset(24_000, animated=False)
```

Supported index alignments are `start`, `center`, `end`, and `nearest`.
`center`, `end`, and `nearest` require native viewport metrics.

## Behavior notes

- The native host never clamps scrolling. A fast fling may briefly show
  spacer content until Python publishes the window, but the projected path is
  pre-rendered, and view recycling keeps the mount cheap.
- Cell views (`Box`, `Layout`, `Text`) are recycled by the host: removed
  cells return to a pool and new cells reuse the exact view instances, with
  stale props reset only when the new cell does not set them.
- A numeric main-axis `height` or `width` lets the first render cover the
  viewport before native metrics arrive; otherwise `initial_item_count`
  covers it and offset jumps wait for native metrics.

## Current scope

- fixed item extent
- vertical and horizontal axes
- windowed mount/unmount
- keyed reconciliation with index fallback
- native fling/drag projection with a render-ahead cap
- transactional offset and index scrolling
- dynamic sequence updates

Not implemented: variable item extents, sections or multiple columns,
headers/footers/separators, sticky items, refresh controls.
