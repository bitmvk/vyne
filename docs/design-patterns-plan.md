# Vyne Design-Pattern Improvement Plan

Status: accepted after a design-pattern audit; all ten findings below
are implemented and verified.

## Status: ALL 10 IMPLEMENTED

Every finding below is implemented and verified: pytest 1531 passed,
JVM 181 passed, instrumentation 90/90, generated-project smoke 10/10
gates. Files named in each finding show the final shape.

## 1. Session Facade — one aggregate, one slot, atomic swap

- **Pattern**: Facade + lifecycle State Machine + transaction-scoped
  Correlation Identifier.
- **Files**: `android.py`, `bootstrap.py`, `runtime.py`,
  `direct_transport.py`, `DirectRenderHost.kt`, `RenderTransaction.kt`,
  `Renderer.kt`, `MainActivity.kt`, tests.
- **Anti-pattern**: one direct Android session is spread across five module
  globals (`_host`, `_runtime`, `_transport`, `_runtime_dispatcher`,
  `_runtime_dispatcher_owner`) with snapshot/restore around candidate
  promotion, and the session identity literal `"vyne-runtime-session"` is
  duplicated (`runtime.py:453`, `MainActivity.kt:484`).
- **Change**: generate `uuid4().hex` in `start_direct()` before mount;
  thread it through `_start_registered_app(session_id=...)` into
  `Runtime.__init__` (optional, defaulting to a fresh uuid so
  MemoryTransport/CLI paths are unchanged) and into
  `DirectTransport(host, session_id)`; set it on the host before the first
  commit. Add an internal `on_runtime_created` hook so candidate promotion
  swaps ONE session aggregate atomically.
- **Why**: replaces five globals + two restore paths with one aggregate and
  one swap; receipts become session-scoped (stale-session rejection
  becomes real).

**[IMPLEMENTED]** ## 2. PropMemento — one accepted-prop authority

- **Pattern**: Memento (dual-slot) + Single Source of Truth + defensive
  Immutability.
- **Files**: `NativeTree.kt`, `Renderer.kt`, `PropertyApplicators.kt`,
  `PresentationEngine.kt`, `docs/extensions.md`, instrumentation tests.
- **Anti-pattern**: rollback capture has two property authorities — core
  props via `capturePropValue()`'s hand-maintained live-view when-switch,
  extension props via the `appliedProps` shadow.
- **Change**: replace both with one `NativeTree`-owned
  `PropMemento(present, acceptedWireValue, livePresentationValues)` with
  `snapshot()/restore()`; deep-copy every JSON bridge container on storage
  and retrieval; `livePresentationValues` is slot-keyed so Canvas keeps
  several live values per slot.
- **Why**: the deferred authoritative-wire-props model; one rollback
  algorithm for all kinds, exact null/absent presence, digest-consistent.

**[IMPLEMENTED]** ## 3. Composite Command rollback — no silent erasure

- **Pattern**: Composite Command + Result-vs-exception boundary.
- **Files**: `Renderer.kt`, `RenderTransactionApplier.kt`,
  instrumentation tests.
- **Anti-pattern**: nine `catch (_: Throwable)` blocks inside transaction
  undo closures erase rollback failures below the boundary that interprets
  them.
- **Change**: remove every silent catch inside undo closures. Add
  `restoreAll(actions)`: run all local restoration actions, retain the
  first failure, attach later failures as suppressed exceptions, throw
  after all run. Single-step undo commands throw directly.
- **Why**: rollback failures become `UNKNOWN` with the true cause instead
  of being swallowed; the digest check stays authoritative.

**[IMPLEMENTED]** ## 4. StateHost — cells bound to their owner

- **Pattern**: Typed Mediator/Observer + one Command journal with a parked
  tier.
- **Files**: `state.py`, `runtime.py`, `scheduler.py`, tests.
- **Anti-pattern**: `State.set()` discovers mutation policy from whichever
  Runtime happens to be in the `_CURRENT_RUNTIME` ContextVar via `getattr`
  probes.
- **Change**: bind every State cell to its owning Runtime at creation —
  `Runtime.use_state` passes `self` into `State(initial, request_render,
  owner)` behind a narrow `StateHost` Protocol (`set_state(cell, value)`,
  `render_phase()`). `State.set()` does the equality fast path then calls
  `owner.set_state(...)` — no ContextVar lookup, no `getattr`.
- **Why**: every write reaches the real owner in every caller context;
  removes the getattr-probe polymorphism.

**[IMPLEMENTED]** ## 5. Transaction lifecycle — one authority, checked transitions

- **Pattern**: Template Method + enforced State Machine + table-driven
  outcome Strategy.
- **Files**: `runtime.py`, `recovery.py`, `scheduler.py`,
  `test_runtime_recovery.py`.
- **Anti-pattern**: the safety-critical commit/publish sequence is
  duplicated with verified drift (`_send_render_commit` vs
  `_send_animation_only_commit`), and `recovery_state` has a permissive
  setter.
- **Change**: keep `_FrameworkTransaction` as the sole lifecycle owner; add
  `transition_to(next_state, cause=...)` enforcing the recovery matrix
  (`SYNCED→AWAITING_APPLY|NEEDS_RESET`,
  `AWAITING_APPLY→SYNCED|NEEDS_RESET`, `NEEDS_RESET→AWAITING_APPLY|SYNCED`,
  non-disposed→`FAULTED`, `FAULTED→NEEDS_RESET`, any→`DISPOSED`) with an
  idempotent self-transition.
- **Why**: one publish pipeline with strategy hooks; illegal transitions
  fail loudly instead of drifting.

**[IMPLEMENTED]** ## 6. PropLayer — key-presence provenance in lowering

- **Pattern**: Layered Template Method with per-source-layer key presence.
- **Files**: `lowering.py`, `test_lowering_precedence.py`,
  `test_lowering_edges.py`.
- **Anti-pattern**: the `defaults < style/decoration < explicit props`
  precedence is enforced by ~10 scattered membership checks with
  inconsistent variants.
- **Change**: a small `PropLayer(values, present_keys)` per source layer
  (defaults; Style fields; Style.decoration; top-level Decoration; explicit
  props). `_lower_style()`/`_lower_decoration()` validate and return
  canonical entries WITHOUT consulting `explicit_props` or mutating the
  final map; aliases/shorthands normalize by key presence with the
  equal-values-collapse rule.
- **Why**: one precedence pipeline; fixes the current
  duplicate-key-inconsistency class of bugs.

**[IMPLEMENTED]** ## 7. Event contract — one authority per side of the mirror

- **Pattern**: Registry with per-kind applicability + explicit
  namespace/collision policy.
- **Files**: `schema_v2.py`, `extensions_registry.py`, `lowering.py`,
  `tools/generate_schema.py`, `ElementContracts.kt`, `ElementRegistry.kt`,
  `Renderer.kt`, tests.
- **Anti-pattern**: per-kind event data exists on both sides and neither
  validation path uses it (`EventSpec.applies_to` exists; the generator
  already emits per-kind event sets but preflight ignores them).
- **Change**: derive `CORE_EVENT_PROPS` from `EVENT_SPECS`; check
  `EventSpec.applies_to` whenever a kind is supplied; delete
  `_TEXT_INPUT_EVENT_PROPS`. Generate `ALL_EVENTS_BY_KIND` and
  `ALL_EVENT_NAMES` in `ElementContracts` and use them in
  `ElementRegistry.isValidEvent`. Explicit collision set: `GENERIC_PROPS`
  redeclaration, core event names, `__vyne_` prefix.
- **Why**: per-kind event validation on both sides; generator drift
  disappears.

**[IMPLEMENTED]** ## 8. Bridge adapter — one foreign-shape conversion point

- **Pattern**: Adapter + immutable Value Object with enforced invariants +
  Single Source of Truth.
- **Files**: `android.py`, `extensions_registry.py`, tests.
- **Anti-pattern**: `DirectRenderHost.extensionKinds()` emits a three-entry
  list per kind `[props, events, [container]]`, but `sync_from_host`'
  permissive parser accepts malformed shapes (and `bool([False])` parses
  wrong).
- **Change**: `ExtensionKindInfo.from_bridge(value)` as the ONLY foreign-
  shape adapter, validating the whole decoded value: exactly three entries;
  props/events lists of exact strings; third entry a singleton list holding
  an exact bool; enforced invariants in `__post_init__`.
- **Why**: one adapter; malformed bridge data fails loudly at the boundary.

**[IMPLEMENTED]** ## 9. Protocol registry — frozen per-operation specs

- **Pattern**: Immutable Registry + validator Strategy.
- **Files**: `protocol.py`, `test_protocol_validation.py`,
  `test_extensions_protocol.py`.
- **Anti-pattern**: `_validate_operation()` combines a required-field
  table, shared checks, a name-based if-chain, and a separate
  `_validate_motion_operation` — two coupled places per operation.
- **Change**: a frozen `_OperationSpec(required_fields, optional_fields,
  validator)` registry keyed by operation name, built with a
  `_simple_op_validator` factory for the twelve plain operations and the
  existing strict validators for the four motion operations; one
  dispatcher.
- **Why**: shape and semantics become one immutable declaration per
  operation; adding an operation edits one place.

**[IMPLEMENTED]** ## 10. ProjectRepository — expected failures as data

- **Pattern**: Repository + Result Object + shared preflight Strategy.
- **Files**: `cli/project.py`, `cli/doctor.py`, `cli/android.py`,
  `cli/extensions.py`, `cli/generation.py`, CLI tests.
- **Anti-pattern**: `run_doctor()` starts with
  `project = project or load_project()`, and `load_project()` raises
  `RuntimeError` for a missing project — doctor can crash before reporting.
- **Change**: `ProjectRepository.inspect(start)` returns a frozen
  `ProjectInspection(project | None, issues, extensions)` that does not
  throw for expected discovery/TOML/config/path/manifest failures
  (unexpected programming errors still propagate); issues are stable
  code/path/message values. `load_project()` calls
  `inspect().require_valid()` for execution commands; one-pass discovery
  publishes the single extension tuple into the Project.
- **Why**: doctor always reports; execution commands still fail fast; one
  discovery source.

## Implementation order (suggested)

1. **#8 bridge adapter + #9 protocol registry** — small, isolated, testable
   first.
2. **#6 PropLayer + #7 event contract** — correctness fixes in validation.
3. **#4 StateHost + #3 restoreAll** — runtime internals with strong test
   coverage.
4. **#2 PropMemento + #5 transaction transitions** — the deferred model
   rewrites (rollback authority, lifecycle authority).
5. **#1 Session Facade + #10 ProjectRepository** — structural end-state
   (globals → aggregate; load → inspect).

## Risks

- #1 touches candidate promotion (the most delicate lifecycle); land last,
  keep snapshot/restore until the aggregate swap is proven.
- #2/#3 change rollback semantics on the hot path — the full emulator
  suite (77 instrumentation tests) is the safety net.
- #6 may change error messages/ordering in lowering tests — expect test
  churn, not behavior change.
- #7 changes the generated `ElementContracts.kt` — regenerate + drift-check.
