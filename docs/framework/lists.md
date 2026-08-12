# Virtualized lists

> The extensibility direction and milestone records live in
> [List building blocks](list-building-blocks.md). `VirtualList` (M2), the
> generic-list contracts (M1), native sticky positioning (M3), and the public
> migration with one controller (M4) are implemented.

## `List` — fixed extent

`List` renders a fixed-extent virtualized list on the generic engine: it is a
convenience wrapper around `VirtualList` with the built-in `FixedLinearLayout`.
Only the cells inside the selected window are composed, positioned inside a
canonical content `Box` by `translation_x`/`y`. The native host keeps scrolling
free and reports where the in-flight gesture is heading; Python plans one
contiguous window from the current viewport through the projected target, so
fast flings render their path instead of chasing the finger.

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

## `VirtualList` — generic engine

`VirtualList` is the generic virtualized-list engine (M2). It composes only
the cells a custom `VirtualLayout` places and the framework selects,
positioned inside a canonical content `Box` by `translation_x`/`y`, and it
drives the same window policy, measurement feedback, and transactional scroll
commands as `List`. One `ListController` drives both components.

```python
from vyne import ListController, VirtualList
from vyne.lists import FixedLinearLayout

controller = ListController()


def Grid():
    return VirtualList(
        tuple(range(10_000)),
        render_item=lambda item, index: Text(text=f"Item {item}"),
        layout=FixedLinearLayout(48, "vertical"),
        key_for_item=lambda item, index: item,
        controller=controller,
        width=300,
        height=400,
    )
```

Arguments match `List` (`data`, `render_item`, `key_for_item`, `axis`,
`overscan`, `max_render_ahead_viewports`, `initial_item_count`, `controller`,
`key`, `interactive_scrollbar`, `scroll_props`) with two additions:

- `layout` (required): a `VirtualLayout` strategy — `FixedLinearLayout` for
  fixed extent, or a custom layout that consumes a `LayoutRequest` and
  returns `LayoutResult` with positioned `VirtualPlacement` cells (grids,
  masonry, flattened sections with sticky headers/footers).
- `max_offscreen_items` (default `64`): strict allowance of offscreen cells
  kept beyond the visible viewport, nearest first.

`data` may be a plain `Sequence` or a custom `VirtualData` implementation
(for lazy/paged sources). Custom `VirtualData` sources own their keys, so
`key_for_item` is rejected for them.

Behavior notes specific to `VirtualList`:

- the no-frame path requires the clamped actual viewport inside the accepted
  safe coverage **and** the clamped planning viewport inside the accepted
  realization; when the offscreen budget dropped candidates the safe coverage
  narrows to the actual viewport's local band (or the exact viewport), so a
  jump into an un-realized projected span always replans;
- observed actual and projected offsets are clamped to the content scroll
  bounds before anchor resolution and layout planning;
- per-cell `layout_metrics` sizes are cached by stable source key in a
  bounded 4096-entry insertion-order cache (reads do not refresh recency;
  a re-measured key is re-inserted newest); identical measurements are no-ops;
- anchor preservation is optional: a layout that exposes `index_near_offset`
  keeps the anchored cell's fraction stable across measurement drift;
  `None` disables the anchor, malformed results raise;
- sticky headers/footers are returned as candidates and retained whenever
  their section boundary interval intersects the realization viewport, so a
  scroll into a section finds its sticky already mounted.  The Android host
  applies the native per-frame sticky movement from private `_virtual_*`
  metadata on the cell wrappers (see the M3 section of
  `list-building-blocks.md`): half-open section activation, start/end
  clamping with push-off, no bridge event, and no Python commit per frame.
  The content Box is marked `_virtual_content` only when a sticky placement
  is selected, so non-sticky lists pay no per-frame sticky traversal;
- a pending scroll target is retained only while the current data is the
  same accepted source it was computed against and its index is still in
  range: any sequence or custom-source replacement cancels it (even at an
  unchanged item count), and a stale target is dropped from renders and
  cleared by the next scroll observation — it never wedges the list and can
  never silently retarget a different item on new data;
- controller commands prefer the latest native physical viewport observation
  and fall back to immutable promoted snapshots. Programmatic destinations do
  not enter that observation before acknowledgement, so an in-flight or
  rejected commit cannot leak into a later command;

`ListController` drives both `List` and `VirtualList` with the same API
(`scroll_to_offset`, `scroll_to_index`, `scroll_to_key`). It owns the private
generic engine and dispatches every command to the mounted list; a controller
bound to two mounted lists raises clearly on every command.

`scroll_to_key` never scans the source: a plain `Sequence` with default index
keys resolves in O(1), an explicit `key_for_item` consults the key registry
of already-realized keys, and a custom `VirtualData` source answers through
its optional `index_for_key`. Any other key raises without a scan.

## Arguments

`data`, `render_item`, and `item_extent` are required. Everything else has a
default:

| argument | default | meaning |
|---|---|---|
| `key_for_item` | item index | `(item, index) -> key` cell identity. Provide it for correct behavior across reorders and resizes, and for rows that hold state. Keys are validated lazily: only realized cells are read, and a key that maps to two different indices of the same data raises `ValueError` the second time it is realized, even across windows. The key must be a pure function of `item` and `index`. |
| `axis` | `"vertical"` | `"vertical"` or `"horizontal"`. |
| `overscan` | `1.0` | extra window margin in viewports, both sides. |
| `max_render_ahead_viewports` | `3` | caps how far ahead (or behind) of the viewport the projected window may reach, bounding the size of one commit. The window follows fast flings in bounded steps instead of rendering the full fling path at once. Pass `0` explicitly to opt back into an unbounded projection. |
| `initial_item_count` | `5` | cells to render before native metrics arrive, used only when no numeric main-axis size is declared. |
| `controller` | owned internally | `ListController` for both `List` and `VirtualList`. One controller drives one mounted list; pass `key=` when sibling lists can reorder. |
| `key` | `None` | list identity for sibling reorder. |
| `interactive_scrollbar` | `True` | always-visible host-native indicator when scrollable; drag the thumb or tap its track. Pass `False` to use the host's ordinary passive scrollbar. Plain `Scroll` containers default this prop to `False`. |
| `**scroll_props` | — | scroll-view props: `height`, `width`, `background_color`, margins, padding, `content_description`, ... |

## Dynamic data

`data` is a plain prop; pass state-derived data to update the list. Changes
are picked up by the next render; keys keep existing cells (and their state)
stable, and the window replans against the new layout.

Replace the sequence with a new object (for example a new tuple from
`state`) when the data changes. The list never copies or scans the whole
sequence: items and keys are read only for the realized window. A per-list
key registry records every realized key so a duplicate key at a different
index of the same data fails early instead of reusing cell state; the
registry resets automatically when the data object, key callback, or item
count changes. Mutating a mutable sequence in place is not supported:
replacement with a new sequence is required so identity tracking and
reconciliation stay correct.

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
`center`, `end`, and `nearest` require native viewport metrics or a declared
numeric main-axis size.

## Behavior notes

- The native host clamps actual and projected offsets to its current content
  range. A fast fling may briefly show the previous window until Python
  publishes the destination cells, but the projected path is pre-rendered and
  view recycling keeps the mount cheap.
- Cell views (`Box`, `Layout`, `Text`) are recycled by the host: removed
  cells return to a pool and new cells reuse the exact view instances, with
  stale props reset only when the new cell does not set them.
- A numeric main-axis `height` or `width` lets the first render cover the
  viewport before native metrics arrive; otherwise `initial_item_count`
  covers it and offset jumps wait for native metrics.
- `interactive_scrollbar=True` uses a generic native scroll-host tool: a 7
  logical-unit thumb, a 32-unit edge touch target, and a minimum 40-unit thumb.
  A plain `Scroll` moves directly because all of its content exists. A virtual
  list instead uses transactional seek: the thumb follows every pointer frame,
  but content stays at the accepted window until Python publishes destination
  cells and the existing accepted `scroll_to` effect reveals them. Internal
  seek crossings are throttled to 32 ms, use latest delivery, and never queue
  more stale positions than the Runtime already permits. Final release bypasses
  throttling and has two bounded 750 ms retries after rejection or loss. The
  initiating pointer owns the drag; extra fingers do not steal the thumb.
- Android positioned-content extents are limited by the platform's 24-bit
  measured-size field (`View.MEASURED_SIZE_MASK`, in device pixels). The host
  rejects a larger semantic extent instead of silently truncating it. This is
  density-dependent and does not define a Python or future-iOS logical limit;
  larger Android ranges need segmented/rebased native scrolling.

## Current scope

### `List` (fixed extent, generic engine)

`List` renders a fixed-extent window through `VirtualList` with
`FixedLinearLayout`: the layout is O(1) per offset-to-index query and the
window covers the projected span plus overscan. It inherits the generic
engine's scope: fixed linear extents on both axes, windowed mount/unmount,
keyed reconciliation with index fallback, native fling/drag projection with a
render-ahead cap, transactional offset/index/key scrolling, and dynamic
sequence updates.

### `VirtualList` (generic)

Implemented: custom `VirtualLayout` strategies (fixed linear, grids,
staggered/masonry, flattened sections with sticky headers/footers), lazy
`VirtualData` sources, keyed measurement feedback with a bounded
stable-key insertion-order cache, anchor preservation, bounded projection
with safe-coverage no-frame path, transactional offset/index/key scrolling,
and native Android sticky movement for retained headers/footers (per-frame
host pass from private metadata; no bridge event or commit).

Generic wrappers use the host's ordinary kind-based view pool: removed Box
and cell-content views are reset and reused without a list-specific recycler.
Sticky limitations: RTL horizontal start/end mapping is unsupported (LTR
increasing x only) and sticky movement is Android-only for now. The generic
content Box publishes private semantic `_virtual_content_width`/`height`
values instead of a fake child. Android enforces them during measurement; a
future iOS host maps the same contract to its native content-size mechanism.
See the host contract section of `list-building-blocks.md`.
