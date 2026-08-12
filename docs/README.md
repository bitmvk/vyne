# Vyne Developer Documentation

This is the developer documentation for the Vyne codebase. It explains the
principles, the algorithms, and everything a first-time contributor needs.

Each file covers one concern. Read the index below, then follow the reading
order in [contributing/getting-started.md](contributing/getting-started.md).

## Concepts (start here)

| file | concern |
|---|---|
| [concepts/principles.md](concepts/principles.md) | what Vyne is, the core principle, who owns what |
| [concepts/data-flow.md](concepts/data-flow.md) | end-to-end data flow, threads, ordering |
| [concepts/core-model.md](concepts/core-model.md) | Element, CanonicalElement, RenderNode, RenderSnapshot, Commit |

## Python framework

| file | concern |
|---|---|
| [framework/lowering.md](framework/lowering.md) | Element -> CanonicalElement: precedence, aliases, validation |
| [framework/reconciliation.md](framework/reconciliation.md) | the diffing algorithm (CORE-01) |
| [framework/protocol.md](framework/protocol.md) | the wire contract: commit ops and events |
| [framework/events.md](framework/events.md) | event registry, delivery policies, acknowledgements |
| [framework/state.md](framework/state.md) | state cells, components, journal, guards |
| [framework/runtime.md](framework/runtime.md) | the orchestrator: render loop, dispatch, async |
| [framework/coordinator.md](framework/coordinator.md) | commit coordinator (COORD-05) |
| [framework/recovery.md](framework/recovery.md) | recovery state machine (CORE-02) |
| [framework/transport.md](framework/transport.md) | MemoryTransport and the direct typed transport |
| [framework/lists.md](framework/lists.md) | public virtualized list API, windowing, projection |
| [framework/networking.md](framework/networking.md) | app-owned networking: permissions, urllib/aiohttp, remote images |

## Animation

| file | concern |
|---|---|
| [animation/overview.md](animation/overview.md) | policy vs mechanics, lifecycle, ordering |
| [animation/python-api.md](animation/python-api.md) | slots, specs, retarget, handles, drivers |
| [animation/native-engine.md](animation/native-engine.md) | the Kotlin frame engine |

## Drawing and styling

| file | concern |
|---|---|
| [drawing/canvas-path.md](drawing/canvas-path.md) | Canvas display list, Path commands, stable op ids |
| [drawing/style-decoration.md](drawing/style-decoration.md) | Style and Decoration tiers |

## Material and extensions

| file | concern |
|---|---|
| [material/material3.md](material/material3.md) | the Python-owned Material 3 catalog |
| [extensions.md](extensions.md) | the extension contract |

## Android host

| file | concern |
|---|---|
| [android-host/overview.md](android-host/overview.md) | Activity, threads, backpressure, transactions |
| [android-host/renderer.md](android-host/renderer.md) | preflight, journal, rollback, digest |
| [android-host/registry.md](android-host/registry.md) | ElementRegistry, widgets, prop applicators |
| [android-host/input.md](android-host/input.md) | input routing and pointer sessions |

## CLI and tooling

| file | concern |
|---|---|
| [cli/commands.md](cli/commands.md) | the `vyne` command line |
| [cli/generation.md](cli/generation.md) | empty-target atomic project generation |

## Testing and contributing

| file | concern |
|---|---|
| [testing/testing.md](testing/testing.md) | all test suites and how to run them |
| [contributing/getting-started.md](contributing/getting-started.md) | first-time contributor checklist |
| [contributing/design-rules.md](contributing/design-rules.md) | numbered invariants and design patterns |
| [glossary.md](glossary.md) | terms used across the docs |

## Related documents (pre-existing)

| file | concern |
|---|---|
| [canonical-ui-spec.md](canonical-ui-spec.md) | the platform-neutral UI model (design baseline) |
| [extensions.md](extensions.md) | the extension guide (contract details) |
| [material3-expressive.md](material3-expressive.md) | the Material catalog and usage guide |
| [rn-parity-roadmap.md](rn-parity-roadmap.md) | React Native core parity: what to add, what to leave to the ecosystem |
