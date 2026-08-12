# List building blocks

This document records the direction and implementation status of Vyne
lists.  M0 (fixed-list performance), M1 (public generic-list contracts and
the realization filter), M2 (generic Python engine), M3 (native sticky
positioning), and M4 (public migration, controller unification, and the
performance gate) are implemented.

## Goal

Vyne should provide the difficult framework primitives needed for virtualized
content. Applications and separate packages should be able to build sectioned,
grid, and staggered layouts without reimplementing reconciliation, measurement,
scroll coordination, or native view recycling.

Vyne should not ship a separate product component for every list layout.

## Public layers

### `VirtualList`

`VirtualList` is the low-level virtualized-content component. A caller provides:

- the item source;
- stable item keys;
- a render callback;
- a layout policy;
- optional realization and scroll policy.

Vyne owns:

- mounting and disposal;
- stable cell identity and state;
- viewport and projected-viewport handling;
- bounded realization and overscan;
- measurement feedback;
- transactional scroll commands;
- native view recycling;
- accepted versus pending render state.

### `List`

`List` is a small convenience API for vertical and horizontal fixed-extent
lists. It shares the source adapter, key registry, single public controller,
and the generic engine with `VirtualList`: `List` renders on the generic
engine with the public `FixedLinearLayout`, so there is exactly one list
engine and one window policy. The dedicated fixed engine that predated M4
was removed; the benchmark gate now compares the `List` surface against its
previous fixed-engine baseline.

Vyne will not initially provide `SectionList`, `GridList`, `StaggeredList`, or a
masonry placement algorithm.

## Data source contract

A small public data-source contract should support normal sequences and lazy or
paged sources without copying every item and key into tuples:

```python
class VirtualData(Protocol):
    @property
    def item_count(self) -> int: ...

    def item_at(self, index: int) -> object: ...
    def key_at(self, index: int) -> object: ...
```

A normal `Sequence` receives an automatic adapter.

## Layout contract

A custom layout receives the viewport, item count, and known measurements. It
returns the total content extent and the cells that must be placed:

```python
@dataclass(frozen=True)
class StickyConstraint:
    edge: Literal["start", "end"]
    boundary_start: float
    boundary_end: float


@dataclass(frozen=True)
class VirtualPlacement:
    index: int
    x: float
    y: float
    width: float
    height: float
    sticky: StickyConstraint | None = None


@dataclass(frozen=True)
class LayoutResult:
    content_width: float
    content_height: float
    placements: tuple[VirtualPlacement, ...]
```

The final API does not have to use these exact names. It must support:

- two-dimensional cell placement;
- estimated geometry for unmeasured cells;
- measurement updates keyed by stable cell identity;
- scroll targets for an index or key;
- cells retained outside the normal visible window;
- optional leading and trailing sticky constraints for headers and footers;
- sticky movement bounded to a section or other layout-defined interval;
- a strict realization budget.

The current `offset interval -> contiguous index range` contract is not enough
for custom grids or staggered layouts.

A layout may use derived or incremental caches (for example cached lane
heights in a masonry layout) to avoid rescanning the full source on every
viewport update.  A cache must be derived purely from request data and must
never change deterministic results or transaction semantics: the same request
must produce the same placements and the same content extent regardless of
cache state.

## Native responsibilities

Native code should perform frame-sensitive work:

- report the current and projected viewport;
- measure mounted cells;
- place virtual children;
- apply sticky constraints during scrolling;
- recycle views by compatible cell type;
- implement platform nested-scroll behavior.

Python should own data, keys, rendering callbacks, realization policy, and state
identity. This hybrid boundary avoids frame-by-frame Python callbacks while
keeping layout policy extensible and testable.

## Layouts built by users

### Sections

A user can flatten sections into one logical stream containing headers, items,
footers, and separators. A header becomes sticky at the leading viewport edge,
and a footer becomes sticky at the trailing viewport edge, by returning sticky
placement metadata. Each sticky placement includes layout-defined boundaries so
it cannot escape its section. Native code applies the constraint during a
scroll and handles push-off at the next section boundary. A separate section
virtualizer is not required.

### Uniform grids

A custom layout maps item indices into rows and columns and returns positioned
cells.

### Staggered or masonry layouts

A custom layout can cache lane heights and place an item in the shortest lane.
Vyne supplies measurements and positioned virtual cells. Vyne does not supply
the lane-placement algorithm.

### Nested lists

A cell may contain another `VirtualList` with independent identity, viewport
state, and controller. Cross-axis nesting is the first supported target.
Same-axis nested scrolling remains unsupported or platform-dependent until a
specific use case defines gesture ownership and sizing rules.

## Existing implementation

The pre-consolidation fixed list contained useful concepts that were retained
or redesigned:

- viewport metrics;
- overscan and projected rendering;
- stable keys;
- a layout strategy;
- retained cells;
- controller binding;
- accepted render state.

The following implementation details should not be preserved:

- duplicate public and private controllers;
- forced copies of the complete data and key sequences;
- configuration fields that the public API always sets to zero;
- dead planner APIs;
- duplicate binding and viewport state;
- an unbounded render-ahead default;
- the assumption that every rendered cell belongs to one contiguous range.

The reverse-projection cap bug in the old fixed engine was fixed before this
redesign. The public fixed list now uses a lazy random-access source adapter
(no full-data copies), a bounded render-ahead default of 3 viewports, and a
symmetric forward/reverse projection cap.

## Complexity budget

A reusable virtualization foundation is expected to require about 1,900 to
3,000 lines of production Python, plus native integration and focused tests.
The fixed-only package was about 1,478 lines before M1 (the M0 baseline).
The generic contracts initially increased that total; the post-M4 cleanup
then removed the old fixed engine and planner. Complexity is justified only
when it belongs to a working public primitive.

No abstraction should be added without:

1. a built-in use in the fixed linear `List`, or
2. a small conformance fixture proving that an external layout can use it.

## Performance requirements

The generic foundation must not move frame-sensitive scrolling into Python.
The fixed linear `List` must retain an O(1) window calculation plus work
proportional to the realized cells. Custom layouts must operate on the bounded
realization set or use incremental caches rather than scan the full data source
on every viewport update.

Sticky headers and footers are native placement constraints. Scrolling them
must not require a Python callback or a render commit per frame. Measurement
updates must be coalesced, and unchanged measurements must not trigger another
layout pass. The fixed-list migration requires before-and-after benchmarks; a
material regression blocks adoption of the generic path.

## Implementation status

### M0 — fixed-list performance (implemented)

The public fixed list now uses a lazy random-access source adapter (no full-data
or full-key copies; keys are computed only for realized cells, and duplicates
are rejected per mounted list via a key registry).  `max_render_ahead_viewports`
defaults to a bounded 3 viewports, and the projection cap is symmetric for
forward and reverse flings.  `_mask_contains_viewports` clamps out-of-range
viewport offsets to the current scroll bounds so a shrink to a shorter source
replans to the real end window.

### M1 — contracts and realization filter (implemented)

`vyne.lists` now exposes the generic-list contracts:

- `VirtualData` (random-access source protocol; `index_for_key` optional);
- `ViewportRect`, `CellMeasurement`, `StickyConstraint` (start/end edges with
  layout-defined boundaries), `VirtualPlacement`, `LayoutResult`, `LayoutRequest`;
- `VirtualLayout` (layout protocol with `place` and `offset_for_index`);
- `FixedLinearLayout` (public O(1) fixed-extent linear layout);
- `select_placements` (pure host-independent realization filter).

The filter marks actual-viewport placements mandatory, retains bounded sticky
headers and footers whose section interval intersects the viewport, requires and
retains the requested target, bounds offscreen extras to the realization
viewport plus a strict nearest-first allowance, and never drops mandatory
placements.  Conformance fixtures for grids, staggered/masonry content, and
flattened sections live in `tests/support/list_conformance.py`.

### M2 — generic Python engine (implemented)

`vyne.lists.VirtualList` is the generic engine: it consumes the M1 contracts
and a `VirtualLayout` strategy, composes positioned realized cells from
ordinary primitives (a Scroll hosting a canonical Box with keyed, sized,
translated cell wrappers), and feeds per-cell `layout_metrics` back into
the layout.  Imperative `scroll_to_offset`/`index`/`key` run through the
single public `vyne.ListController`, which owns the private generic engine
controller.

- window policy retains the framework seams established by the old fixed engine: staged imperative bindings,
  native effects, one-in-flight commits, rollback, reset, and
  acknowledgements; no Python runs per native frame beyond coalesced
  `scroll_metrics` and per-cell `layout_metrics` events;
- the no-frame path requires the clamped actual viewport to stay inside the
  accepted safe coverage **and** the clamped capped-planning viewport to stay
  inside the accepted realization viewport.  The safe coverage is derived
  from the accepted render by set membership: when every candidate
  intersecting the realization was selected it is the realization rect;
  otherwise it narrows to the local overscan band around the actual viewport
  (only if every candidate there was selected) or to the exact actual
  viewport.  No exact geometric coverage heuristic is used, so a strict
  offscreen budget can never leave the actual viewport blank while its cells
  were dropped;
- observed actual and projected main offsets are clamped to the accepted
  content scroll bounds before anchor resolution and layout planning, so a
  fling past the content end never feeds out-of-range offsets to a layout;
- measurements are cached by stable source key in a bounded 4096-entry
  insertion-order cache (reads do not refresh recency; a re-measured key is
  re-inserted newest; identical measurements are no-ops; off-window sizes
  survive round trips);
- anchor preservation is optional: a layout that exposes `index_near_offset`
  keeps the anchored cell's viewport fraction stable across measurement
  drift.  An optional `index_near_offset` returning `None` simply disables
  the anchor; a malformed result (non-integer or out of range) raises a
  clear error instead of reaching `offset_for_index`;
- sticky placements are retained and composed at their natural positions;
  the native start/end sticky movement and section push-off are implemented
  in M3.  The layout contract requires a sticky candidate whenever its
  boundary interval intersects the realization viewport (half-open), and
  the filter and the safe-coverage decision both use that relevance
  predicate, so a scroll into a section never finds its sticky header or
  footer unmounted;
- a pending scroll target is retained only while the current data is the
  same accepted source it was computed against and its index is still in
  range: any sequence or custom-source replacement cancels it even at an
  unchanged item count, and a stale target is dropped from the render
  request and cleared by the next scroll observation — it never wedges the
  list and can never silently retarget a different item on new data;
- controller commands prefer the latest native physical viewport observation
  and fall back to immutable snapshots carried by the accepted binding. A
  candidate programmatic destination does not update that observation before
  acknowledgement, and every explicit alignment is clamped to the content
  scroll bounds;
- `scroll_to_key` never scans the source: a plain `Sequence` with default
  index keys resolves in O(1) through `SequenceDataSource.index_for_key`, a
  custom `VirtualData` source answers through its optional `index_for_key`,
  and an explicit `key_for_item` consults the key registry of
  already-realized keys; any other key raises without a scan;
- historical benchmark evidence showed the generic path tracking the old
  fixed engine with a modest constant overhead while composing only realized
  cells. The current harness measures the consolidated `List` and
  `VirtualList` paths with no full-source copies or scans.

### M3 — native positioning and sticky constraints (implemented)

Native sticky headers and footers are implemented without a new public
primitive or concept.  Three architecture options were considered:

1. **New native virtual-content primitive.**  A dedicated positioned-child
   container owned by the host.  Correct and native-per-frame, but it adds a
   new wire kind, a new reconciliation path, and a parallel API surface.
2. **Commit-time Python translation updates.**  Python re-publishes cell
   translations on every scroll frame.  Zero host work, but every frame
   becomes a bridge round-trip plus a render commit — precisely what the
   framework boundary forbids for frame-sensitive work.
3. **Ordinary Box positioning plus minimal private host metadata applied by
   existing scroll hosts.** `Box` gives canonical positioned children;
   semantic content extents and per-frame sticky displacement are implemented
   mechanically by each platform host from small private props.

**Selected: option 3.**  The generic engine keeps composing ordinary Boxes;
Python owns realization and publishes, per sticky cell, its natural
`translation_x`/`y` (unchanged from M2) plus a private boundary interval and
edge; the native scroll hosts move the wrapper per frame.

Authority split (unchanged boundary, one addition):

- **Python owns** data, keys, rendering, window policy, and *what* is
  sticky: it publishes `_virtual_sticky_edge` +
  `_virtual_sticky_boundary_start/end` (dp, from the layout's
  `StickyConstraint`) on sticky cell wrappers, and marks the content Box
  (`_virtual_content`) only when the accepted window includes a sticky
  placement.  Non-sticky virtual lists therefore carry no marker and the
  native host pays only an O(1) marker check per scroll frame; the
  realization contract guarantees a sticky candidate is composed in the
  same commit that first needs it, so a future active sticky re-emits the
  marker before it is used.  The private props are Box-only schema props
  with underscore names, so they never appear in generated public
  constructor stubs, and they are dropped at default so ordinary Boxes and
  non-sticky cells carry nothing.
- **Each platform host owns** the per-frame displacement: Android scroll
  hosts run an O(realized) pass over a marked content's direct children on
  native `onScrollChanged` and after layout (initial offset, deferred scrolls,
  child changes). Unmarked content returns immediately. No bridge event is
  emitted and no Python commit is required; translation-only changes never
  trigger `layout_metrics`, so measurement feedback is untouched. A future
  iOS adapter implements this same host contract with UIKit mechanics.

Positioning formula (content coordinates, half-open activation): a sticky
cell is displaced only while the viewport overlaps its boundary interval
`[boundaryStart, boundaryEnd)`; outside that overlap it sits at its natural
placed position.  Start/header cells clamp `max(natural, viewportStart)`
into `[boundaryStart, boundaryEnd - extent]` (pin to the viewport top, push
off at the section end); end/footer cells clamp
`min(natural, viewportEnd - extent)` into the same range (pin to the
viewport bottom, push off when the next section arrives).  Both a header
and a footer of the same section can be active simultaneously.  Degenerate
cases (inverted/empty bounds, a cell larger than its section, unmeasured
zero extent) keep the natural position.  A displaced cell gets a small
`translationZ` so it paints above ordinary cells; the user's `elevation`
prop is never modified.  Vertical uses y/height/scrollY; horizontal uses
x/width/scrollX with increasing content coordinates as `start` (LTR).

Lifecycle: prop set/update/remove and pooled Box reuse go through the
normal transaction/memento machinery, so a reused or rolled-back cell
clears sticky metadata and natural translation correctly.  The translation
applicators keep the visible and natural translations consistent and
re-displace immediately after a prop update using the viewport the host
last published to the content Box.  Per-axis removal is strict: removing
`translation_x` resets only the X natural/visible axis and re-applies any
active sticky displacement (and vice versa), never clobbering the other
axis or the paint Z.  The `_virtual_sticky_edge` and boundary setters and
removers all re-displace on a stationary viewport, so a measurement-driven
boundary change alone updates the pinned position without waiting for a
scroll or layout.  Removing or false-setting `_virtual_content` restores
every realized direct child to its natural position before the native pass
is disabled, and an unrecognized sticky edge (defensively, the schema
already rejects it) is treated as natural flow.

Test evidence (Android host): 35 JVM tests — 20 positioning-math tests
(activation, start/end, push-off, before/after, degenerate, unknown-edge
fallback, axis equivalence), 11 driver tests proving the marker gate, the
O(realized) index loop, boundary-only stationary re-displacement, per-axis
reset semantics, marker-removal restoration, and the unknown-edge
fallback with fakes (the exact functions the views call), and 4
contract/applicator tests on the regenerated `ElementContracts` and
`PropertyTable`.  `:host:testDebugUnitTest` runs green, and `vyne build`
assembles the debug APK.

Device evidence (API-35 emulator, Pixel_9_API35 AVD): a targeted
instrumentation test (`VirtualStickyBindingInstrumentationTest`) builds a
real `RoundedScrollView`/`RoundedHorizontalScrollView` hosting a marked
`RoundedFrameLayout` with sticky children on the main thread, lays the
host out, and verifies header/footer per-frame displacement, restoration
when the viewport leaves the section, the unmarked-content gate, marker
removal restoration, and that translation-only scrolls never trigger a
layout callback.  Production-composition tests additionally apply the exact generic-list wire
shape through the real `Renderer` and prove the content Box reaches its
semantic extent on both axes, the host has a real scroll range, sticky
movement works through that composition, and a scrollbar thumb can drag far
across a 10,000-unit range, including transactional seek/reveal and rejection
recovery — all 9 focused tests pass on the emulator.  A CI test
(`tests/test_kotlin_contracts_generation.py`) runs
`tools/generate_schema.py --check` to pin the Kotlin contract drift.

Content extent (portable host contract): Python publishes semantic private
`_virtual_content_width`/`_virtual_content_height` values on the positioned
content Box. Android enforces them during `RoundedFrameLayout` measurement,
which avoids FrameLayout collapsing to its tallest realized child under
ScrollView's UNSPECIFIED main-axis measurement. No inert sentinel or other
Android workaround appears in the Python tree. A future iOS adapter maps the
same values to its native content-size mechanism. Android rejects a semantic
positioned-content extent above `View.MEASURED_SIZE_MASK` device pixels rather
than silently truncating it; a future segmented/rebased host tool is required
for larger Android ranges. This density-dependent adapter limit does not set a
cross-platform logical maximum. `List` uses the same semantic Box path as
`VirtualList` (its fixed-extent cells are positioned children, not spacers).

Limitations:

- RTL horizontal: `start`/`end` map to increasing x (LTR) only.  RTL is
  unsupported: the host has no layout-direction handling, and horizontal
  sticky math plus the projection assume LTR `scrollX >= 0`.
- Same-axis nested scrolling remains unsupported or platform-dependent, as
  documented under nested lists.
- Sticky and interactive-scrollbar mechanics are implemented by Android now;
  an iOS host adapter remains required, using the shared fixture semantics.

## Platform-neutral list host contract

The production split is explicit:

- Python owns sources, keys, layout, realization, anchor correction, accepted
  controller state, semantic content extent, and sticky constraints.
- A host registry maps canonical kinds to platform views. The canonical
  `KindSpec` has no Android class names; `NativeWidgets.kt` is Android's sole
  factory map. A future iOS registry supplies UIKit factories independently.
- Native hosts provide generic frame-sensitive tools only: scroll physics,
  measurement, view reuse, sticky displacement, and interactive scrollbar
  drawing/touch. They never inspect list items, keys, or layouts.

`tests/fixtures/list_host_contract.json` is the canonical cross-language
fixture consumed by Android JVM tests; the pure-Python reference module
(`vyne._lists.host_contract`) was removed with the fixed-engine cleanup, and
a future iOS test target must consume the same file. Native deceleration
curves do not need to match: `projected_offset` means only the host's best
clamped estimate of its own final landing position.

`List` and `VirtualList` default `interactive_scrollbar=True`; a plain `Scroll`
opts in explicitly. When content is scrollable, the host keeps a 7-unit visual
thumb visible on the right (vertical) or bottom (horizontal), uses a 32-unit
edge touch target and a minimum 40-unit main-axis thumb, preserves an in-thumb
grab, and centers the thumb for a track tap. The pointer that starts a drag
retains ownership until release; additional pointers cannot move the thumb.
A plain `Scroll` updates its native position directly. `List` and `VirtualList`
install an internal latest `scroll_seek` handler instead: the thumb follows the
finger, while actual content remains at its accepted window until Python
publishes bounded destination cells and the existing non-animated `scroll_to`
effect reveals them after acceptance. Non-final crossings are throttled to 32
ms, final release bypasses throttling, and only the newest pending handler event
survives existing Runtime backpressure. Two 750 ms final retries recover a
rejected/lost reveal without an acknowledgement latch. The crossing still has
latency; this ordering prevents blank destinations without changing the commit,
revision, scheduler, or public controller architecture. A future iOS host must
implement the same fixture-pinned handshake. RTL horizontal placement remains
deferred.

## Implementation status — M4 (public migration, controller unification, gate)

### Public API

- Two components remain because they serve distinct layers: `List` is
  fixed-extent convenience, and `VirtualList` is the custom-layout
  foundation.  They share the lazy source adapter, the per-list key
  registry, one public controller, and one engine: `List` renders on the
  generic engine with the public `FixedLinearLayout`.  The dedicated fixed
  engine was removed in the post-M4 cleanup.
- One public `ListController` drives both components.  It owns the private
  generic engine controller and dispatches every command to the mounted
  list.  The private engine stays internal machinery; a controller
  accidentally bound to two mounted lists raises a clear error on every
  command.  Accepted binding staging, rejection, unknown reset, unmount,
  keyed sibling swap, and one-in-flight behavior are unchanged.
- The temporary public `VirtualListController` is removed — there is one
  controller type.  The `vyne.experimental.lists` alias namespace was
  removed with the cleanup.
- Root exports: `List`, `ListController`, `VirtualList`.  The M1 layout/data
  contracts stay under `vyne.lists`.
- `scroll_to_key` works on both public components with no source scan: default index
  keys resolve in O(1) (`SequenceDataSource.index_for_key`), realized custom
  keys resolve through the accepted key registry, and `VirtualData` sources
  answer through the optional `index_for_key`.  Unknown, non-canonical, or
  out-of-range keys raise clearly.

### Planner cleanup (intentional private breaking change)

- The old interval planner (`model.py`, `window.py`, `select_window`, and
  `plan_mask`) was deleted after `List` moved to `FixedLinearLayout` on the
  generic engine. The benchmark now measures the live public paths only.
- Small shared helpers (`_lists/_shared.py`) remove genuine duplication:
  `derive_candidate_key_registry` and `resolve_alignment_offset`/`resolve_key_index`
  handle key registration and scroll-target math for the remaining generic
  engine. The post-M4 cleanup removed the fixed planner and routes `List`
  through `FixedLinearLayout`.
- The engine carries immutable `actual_viewport`/`planning_viewport`
  snapshots on promoted bindings and keeps a separate physical viewport cache
  updated only by native scroll observations or an accepted binding change.
  Commands prefer the latest physical observation and fall back to the
  promoted snapshots. An in-flight or rejected programmatic jump therefore
  cannot leak its destination, while a native scroll inside existing coverage
  remains visible to `nearest` and path-coverage commands without forcing a
  render.

### Performance gate

The `benchmarks/list_baseline_bench.py` harness (25 samples / 3 warmups)
was run on the M3 tree (pre-M4, `/tmp/m3_bench.json`) and the M4 tree.  The
fixed cases are flat: mount, same-window no-commit, window-moving scroll,
fling (unbounded and capped), data update, and reorder all stay within
noise of the pre-M4 medians (see the final table below).  Planner cases
included planner cases that were later removed with the fixed engine. The
generic cases record their cells and source-size flatness.

| case | pre-M4 (M3 tree) med | M4 med | Δmed |
|---|---|---|---|
| R1 mount List n=1000 | 6.7435 ms | 6.7103 ms | −0.5% |
| R1 mount List n=100000 | 6.7738 ms | 6.7610 ms | −0.2% |
| R2 same-window no-commit n=1000 | 0.0949 ms | 0.0928 ms | −2.2% |
| R3 window-moving n=1000 | 8.1207 ms | 8.1453 ms | +0.3% |
| R3 window-moving n=100000 | 8.1679 ms | 8.2396 ms | +0.9% |
| R4 fling unbounded n=100k | 1394.4 ms | 1397.0 ms | +0.2% |
| R5 fling cap=3 n=100k | 13.3735 ms | 13.3333 ms | −0.3% |
| R6 data update n=100000 | 6.9895 ms | 6.9938 ms | +0.1% |
| R7 reorder n=100000 | 5.5027 ms | 5.5340 ms | +0.6% |
| G1 generic mount n=100000 | 8.7774 ms | 9.0069 ms | +2.6% |
| G3 generic window-move n=100000 | 9.4093 ms | 9.5709 ms | +1.7% |

(The `--compare` gate compares only cases present in both runs; the removed
`plan_window`/prediction cases are reported by name change, not regression.
Sub-microsecond source-construction cases (S1, baselines below 5 µs) are
exempted through the harness's absolute-noise floor `noise_floor_ms=0.005`,
where timer granularity dominates any percentage threshold.)

## Deferred work

1. expose a packaged conformance kit beyond the current public-contract test
   fixtures;
2. RTL horizontal sticky semantics (see the M3 limitations).

Generic cell wrappers use the same native kind-based view pool as other Vyne
views. Removed wrapper and content views are reset and reused; this needs no
separate list-specific recycler.

## Complexity budget

The post-M4 cleanup reduced the list package to about 2,725 production lines
by deleting the fixed engine and routing `List` through the generic placement
engine with `FixedLinearLayout`. The native M3 host work remains shared by
both public components.

## Maintainability decision (M4)

M4 considered three options for the controller layer:

1. **Permanent dual public controllers.**  Zero risk, but two public
   concepts for one capability and every future feature fixed twice.
2. **Unify on one public controller now.**  One `ListController` owning both
   private engine controllers, dispatching to whichever is bound.  The
   private engines keep their specialized planners; only the public concept
   is unified.  No public-API churn later because backward compatibility is
   explicitly not required.
3. **Full engine consolidation.**  One engine for both components.  Largest
   change; would force `List` onto the generic path and risk the fixed
   performance baseline for no user-visible benefit.

M4 first selected option 2. The post-M4 breaking cleanup then selected
**option 3**: `List` now uses the generic engine with `FixedLinearLayout`.
One public controller owns one private engine. Candidate destinations still
never update the native viewport observation before acknowledgement. No
compatibility promise is made: `VirtualListController`, the fixed engine, and
planner internals were removed rather than deprecated.
