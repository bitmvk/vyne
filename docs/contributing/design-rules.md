# Design Rules and Invariants

These codes appear in the source as comments. They are the contract.
If a change breaks one, the change needs a design discussion first.

## Numbered invariants

| code | rule | where |
|---|---|---|
| CORE-01 | pure reconciliation planner with mutable native-order shadow lists; sequential move ops use correct indices | `reconcile.py` |
| CORE-02 | recovery state machine; incremental commits gated on acknowledged apply results | `recovery.py`, `runtime.py` |
| COORD-05 | commit coordinator: accepted/candidate/in-flight, one revision in flight, atomic promotion, state journal rollback | `scheduler.py`, `runtime.py` |
| SCHED-01 | animation ops queue separately during dispatch and merge into the next commit; animation-only commits for pure animation work | `runtime.py` |
| SCHED-02 | native-value acknowledgements keyed by (node_id, prop); equal desired echoes suppress, transforms/resets still emit; extraction is schema-driven | `scheduler.py` |
| SCHED-03 | render-phase mutation guard raises on `State.set()` during render; bounded pass guard prevents infinite loops | `scheduler.py`, `state.py` |
| SCHED-04 | full-tree reconciliation with component output caching; component boundaries are an optimisation, not an isolation boundary | `runtime.py` |
| RP3-02 | `remove(id)` destroys the subtree root and every descendant; exactly one remove op per subtree root | `reconcile.py` |
| RE-1 | a failing handler or render never clears a known-good tree | `runtime.py` |
| RE-6 | terminal fault bounding: 5 consecutive faults -> `FAULTED`, no retry storms | `runtime.py` |
| MODEL-02 | unsupported features fail with a clear field path, never silently | `lowering.py`, `protocol.py` |
| MODEL-03 | elements, props, and canonical values are deeply immutable (FrozenMap / tuples) | `values.py`, `elements.py` |
| GEN-14 | generation is atomic: empty-target rule, temp-sibling staging, single `os.replace` publish | `cli/generation.py` |

## Cross-cutting design patterns

The two patterns that touch everything:

### Design-pattern #1 — session facade

One direct Android session is one aggregate object (`_DirectSession`),
swapped atomically on candidate promotion. The session id is a `uuid4`
threaded through transport and runtime; receipts are session-scoped, so
stale-session receipts are rejected.

### Design-pattern #5 — one authority, enforced transitions

- `_FrameworkTransaction` is the sole owner of commit publication,
  rollback, and recovery state.
- `transition_to()` enforces the recovery matrix; illegal transitions
  fail loudly.
- One publish pipeline serves render commits and animation-only commits —
  same reservation, same ack handling, no duplicated drift.

## Other implemented patterns

| # | pattern | shape |
|---|---|---|
| 2 | Memento | `PropMemento` — one accepted-prop authority (presence, wire value, live values), deep-copied |
| 3 | Composite Command | `restoreAll` — every undo runs, first failure rethrown, later ones suppressed |
| 4 | StateHost | State cells bound to their owning Runtime at creation; no ContextVar lookup on write |
| 6-10 | remaining | table-driven outcome strategy, snapshot/resync policy, bounded fault handling |

## Ownership rules

- Python owns policy; Kotlin owns mechanics. New native code must stay
  mechanical.
- The Kotlin `ElementRegistry` is the single source of truth for
  extension contracts. Python never declares extensions.
- The schema (`vyne/spec/schema_v2.py`) is the single semantic source
  for kinds, props, events, and animatability. Generated Kotlin contracts
  consume it.
- One canonical copy of the Android host lives in `android/`; `setup.py`
  packages it into `vyne/base_project`.

## Related

- [getting-started.md](getting-started.md) — the never-do list
- [../canonical-ui-spec.md](../canonical-ui-spec.md) — the platform-neutral model
