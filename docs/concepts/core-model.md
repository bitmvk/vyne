# Core Model

This page defines the data types in the render pipeline and where they
live in the code.

## Element

`vyne.elements.Element` — the user-facing UI node.

- frozen (deeply immutable)
- holds `kind`, a `FrozenMap` of props, a tuple of children
- has **no runtime identity**

User constructors (`Box`, `Text`, `Row`, ...) build Elements. The same
Element object can be reused many times. Each occurrence gets its own
runtime node.

Details:

- `Row` and `Column` lower to `Layout` with `orientation`.
- Scalar children (`"hello"`, `42`) become `Text` elements.
- Nested lists of children are flattened. `None` children are dropped.
- Path `d` strings and Canvas `draw` lists are compiled at creation time,
  so malformed input fails fast, off the UI thread.
- Keys must be strings, non-bool ints, or tuples of those (canonical key
  domain). Mutable keys reject.

## CanonicalElement

`vyne.lowering.CanonicalElement` — the fully lowered element.

- immutable, deeply frozen props (MODEL-03)
- flat props: aliases and shorthands resolved
- Style/Decoration layers merged
- validated against the schema
- `native_props` precomputed: props minus refs and event handlers

Equality and hashing are structural. This powers the identity cache: a
component that returns the exact same Element object reuses its lowered
canonical subtree without re-walking descendants.

## RenderNode

`vyne.render_model.RenderNode` — the runtime mirror of one native view.

Fields:

- `id` — monotonic integer, the wire identity
- `kind`, `key`
- `props` — canonical prop values
- `listeners` — event name -> handler id
- `latest_events` — events with `latest` delivery
- `listener_callbacks` — the Python callables
- `ref` — attached Ref
- `children`, `parent_id`
- `element` — the immutable blueprint
- `intent_element` — the canonical element whose intents were bound

Accepted `RenderNode`s are treated as immutable by the planner.

## RenderSnapshot

`vyne.render_model.RenderSnapshot` — the complete tree state at one
revision.

- `root` — root RenderNode or None
- `node_index` — id -> RenderNode
- `revision`

It is the accepted baseline for the next reconciliation pass.

## Commit

A commit is a logical message Python sends to native:

```json
{
  "type": "commit",
  "revision": 7,
  "origin_event_seq": 42,
  "ops": [ ... ]
}
```

- `revision` — monotonic, one per commit
- `origin_event_seq` — the native event that caused this render
- `ops` — the ordered tree-patch operations

See [framework/protocol.md](../framework/protocol.md) for the op list.

## Values

All values that cross the bridge must be bridge-safe:

- scalars: bool, int (signed 64-bit), float (finite), str
- containers: string-key mappings, sequences
- no cycles, no NaN/Infinity

Public props are recursively frozen into `FrozenMap` / tuples at Element
construction (MODEL-03). Unknown mutable objects reject.

## Node identity rules

- Node ids are allocated by the reconciliation planner, monotonic.
- Identity across renders is `(kind, key)`.
- Refs are attached to node ids at promotion; invalidated on removal.
- A Ref cannot be used by multiple mounted occurrences, or across Runtimes.

## Related

- [lowering.md](../framework/lowering.md) — how Elements become CanonicalElements
- [reconciliation.md](../framework/reconciliation.md) — how RenderNodes are diffed
- [coordinator.md](../framework/coordinator.md) — who owns the snapshots
