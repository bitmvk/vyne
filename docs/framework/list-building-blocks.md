# List building blocks

This document records the planned direction for Vyne lists. It is a design note,
not a commitment to implement the work in the current cleanup.

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

`List` remains a small convenience API backed by `VirtualList` and a fixed
linear layout. It supports vertical and horizontal axes and fixed item extent.

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
class VirtualPlacement:
    index: int
    x: float
    y: float
    width: float
    height: float
    sticky: str | None = None


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
- optional sticky constraints;
- a strict realization budget.

The current `offset interval -> contiguous index range` contract is not enough
for custom grids or staggered layouts.

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
footers, and separators. A header becomes sticky by returning sticky placement
metadata. A separate section virtualizer is not required.

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

The current fixed list contains useful concepts that should be retained or
redesigned:

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

The reverse-projection cap bug in the current fixed engine must be fixed before
this redesign.

## Complexity budget

A reusable virtualization foundation is expected to require about 1,900 to
3,000 lines of production Python, plus native integration and focused tests.
The current fixed-only package is about 1,478 lines. The foundation may
therefore add code, but the complexity is justified only when it belongs to a
working public primitive.

No abstraction should be added without:

1. a built-in use in the fixed linear `List`, or
2. a small conformance fixture proving that an external layout can use it.

## Deferred work

This cleanup does not implement the design above. Future list work should be
staged:

1. fix the current render-ahead cap bug;
2. define the placement, measurement, and data-source contracts;
3. move the fixed linear list onto those contracts;
4. expose a conformance test kit for custom layouts;
5. add native sticky and positioned-child primitives when required.
