# Recovery (CORE-02)

Sources: `vyne/recovery.py`, `vyne/runtime.py`.

The recovery state machine tracks native synchronization health. It gates
incremental commits on acknowledged apply results and handles
native-reported failures with snapshot resets.

## States

| state | meaning |
|---|---|
| `SYNCED` | Python and native trees match |
| `AWAITING_APPLY` | commit sent, waiting for native confirmation |
| `NEEDS_RESET` | native tree unknown or desynchronized |
| `FAULTED` | native irrecoverably failed |
| `DISPOSED` | renderer disposed |

## The transition matrix

The only legal directed transitions:

```text
SYNCED -> AWAITING_APPLY | NEEDS_RESET
AWAITING_APPLY -> SYNCED | NEEDS_RESET
NEEDS_RESET -> AWAITING_APPLY | SYNCED
any non-disposed -> FAULTED
FAULTED -> NEEDS_RESET
any -> DISPOSED
```

Self-transitions are idempotent. `_FrameworkTransaction.transition_to()`
is the one authorized way to change state: illegal transitions fail loudly
instead of drifting (design-pattern #5).

## Policies

### Malformed inbound events

Malformed events never clear a known-good tree. They are discarded.

### Unknown native state

A native `unknown` result means the native tree is unknown. The candidate
remains the desired Python state, and the next publication is a complete
snapshot — never incrementals.

### Known rejection

`rejected_known` / `verified_rollback` / `partial` discard the candidate,
roll back the framework (state journal, component checkpoint, animation
registrations), and return to `SYNCED` with the accepted baseline intact.
A deferred render replans.

### Error commits

RE-1: if an accepted UI exists, it is preserved. The error is logged, the
journal rolls back, the staged candidate is discarded.

When no accepted UI exists (cold start or already reset), the fallback
error commit is emitted so the user sees something actionable.

### Terminal fault bounding (RE-6)

A consecutive-fault counter bounds repeated failures. After 5 consecutive
faults the runtime transitions to `FAULTED` and stops emitting error
commits — no retry storms.

## The complete snapshot

`build_snapshot_commit(root, revision)` builds a self-contained commit:

- `clear` (id 0) wipes any unknown native state
- create ops for every node
- `set_props` for all resolved props (sorted, deterministic)
- listener ops for all active listeners (sorted)
- `insert_child` ops in order

The output is deterministic: the same tree always produces the same
commit bytes.

The snapshot is sent when the recovery state is `NEEDS_RESET`. In that
state, animation ops are not merged into snapshot commits.

## Related

- [coordinator.md](coordinator.md) — the commit lifecycle
- [protocol.md](protocol.md) — apply results
- [android-host/renderer.md](../android-host/renderer.md) — native rollback
