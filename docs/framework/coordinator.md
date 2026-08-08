# The Commit Coordinator (COORD-05)

Source: `vyne/scheduler.py` (CommitCoordinator) and
`vyne/runtime.py` (_FrameworkTransaction).

The coordinator owns the accepted/candidate/in-flight commit lifecycle.

## Three states

| state | meaning |
|---|---|
| **accepted** | the last exactly acknowledged snapshot; read-only for planning |
| **candidate** | staged by a completed render, not yet sent or promoted |
| **in-flight** | one revision sent, awaiting the native receipt |

## Rules

- At most one revision is in flight at a time.
- Planning and validation happen on a deep-copied working snapshot. The
  accepted state is never mutated before transport acknowledgement.
- Matching `ok` atomically promotes the candidate.
- Known rejection discards the candidate and preserves the accepted
  baseline.
- Unknown native state keeps the candidate as desired state and requires
  a complete snapshot for resynchronization.

## The publish pipeline

One shared pipeline serves render commits and animation-only commits
(design-pattern #5):

1. `stage_candidate()` — planned tree, node index, ref map, event
   registry
2. `reserve_send()` / `reserve_animation_send()` — provisional in-flight
   reservation, so a transport that answers synchronously inside `send()`
   can be captured
3. transport sends the commit
4. `finish_send()` — on a held synchronous `ok`, promote immediately
5. `acknowledge_native_apply(revision)` — promote on the matching async
   receipt
6. `report_native_failure(revision, unknown=...)` — reject or reset

Failure paths:

- `abort_send()` — transport raised; candidate discarded, framework
  rolled back
- `reject_known()` — preflight/rollback rejected; candidate discarded,
  accepted preserved
- `report_unknown()` — in-flight identity cleared; recovery state selects
  a complete snapshot

## Promotion

On promotion:

- the candidate becomes the accepted state
- the candidate event registry becomes the accepted registry
- pending Ref attachments and invalidations apply (old refs invalidate,
  new refs attach `ViewHandle`s)
- animation registrations for that revision are marked running

## Stale receipts

Receipts are matched by revision. A stale acknowledgement (wrong
revision) is ignored. Receipts are also session-scoped: `handle_native_apply_result`
ignores receipts whose session id does not match the runtime's.

## Deferred work

- Renders requested while a commit is in flight are deferred; the ack
  handler schedules them.
- Animation-only work deferred while in flight is flushed after the ack
  if no render is pending.
- Async callback writes are parked as deferred mutations and adopted on
  resolution (baseline preserved for rejection).

## Ref lifecycle

- `Ref.attach()` happens on mount, gated on commit acknowledgement.
- `Ref.invalidate()` happens on removal, replacement, and disposal.
- `ViewHandle` validity is respected by animation and imperative access
  paths.
- The ref map always reflects accepted state.

## Related

- [recovery.md](recovery.md) — the state machine that gates commits
- [runtime.md](runtime.md) — the render loop that feeds candidates
- [events.md](events.md) — receipts arriving as system events
