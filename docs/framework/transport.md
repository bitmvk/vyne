# The Transport Layer

Sources: `vyne/transport.py`, `vyne/direct_transport.py`.

The transport layer is deliberately thin. The Runtime calls
`transport.send(message)` with a logical message dict; the transport
decides how to deliver it.

## The Transport protocol

```python
class Transport(Protocol):
    def send(self, message: JsonObject) -> None: ...
```

Any custom backend must satisfy exactly this.

## MemoryTransport

Used by tests, demos, and early host integration.

- stores messages in a list (`keep_history`)
- with a runtime attached, auto-acknowledges every commit, so the
  recovery state machine advances from `AWAITING_APPLY` to `SYNCED`
  without a real native round trip (CORE-02)

## DirectTransport (production Android path)

Publishes logical commits through direct Java method calls. There is no
message envelope, opcode table, or binary codec.

Key properties:

- `preflights_commits = True` — the Kotlin transaction builder and
  Renderer preflight validate the stream, so the runtime skips the legacy
  JSON-envelope validation pass
- session id published on the host before the first commit, so native
  receipts carry the real session id (design-pattern #1)

### Value encoding

Values are encoded into typed columns so one JNI crossing carries many
values:

| tag | value |
|---|---|
| 0 NULL | null |
| 1 BOOL | long 0/1 |
| 2 INT | signed 64-bit long |
| 3 FLOAT | double |
| 4 STRING | string |
| 5 JSON | compact JSON string |

Parallel arrays: names, tag bytes, longs, doubles, strings. The Kotlin
side decodes with a cursor and validates column lengths.

### Batching paths

The transport scans the op stream and chooses the cheapest call shape:

1. **Complete mount commit** (`commitMountNodes`) — a fresh tree is sent
   as one call: ids, kinds, prop counts, names, tagged values, parent
   ids, insertion modes/indices, post attachments, listeners.
2. **Pure prop batches** — runs of `set_prop` ops become `commitPropBatch`
   (typed arrays) or `commitStringPropBatch` (one repeated string prop).
3. **Contiguous string batches** — repeated string props on consecutive
   node ids compress to `(first_id, name, values)`.
4. **Mixed streams** — `beginCommit`, per-op typed calls, `finishCommit`;
   `abortCommit` discards on error.

Rationale: "a commit does not cross JNI once per operation." Mounts and
repeated property updates are the hot paths; they use semantic batching.

### Host method surface

`DirectRenderHost` exposes one method per operation:

- `clear`, `create`, `setProps`, `setProp`, `removeProp`
- `listen(id, event, handler, latest)`, `unlisten`
- `insertChild`, `moveChild`, `removeChild`, `remove`
- `motionSetTarget`, `motionCancel`, `motionDriverSetTarget`,
  `motionDriverCancel`
- `beginCommit(revision)`, `finishCommit()`, `abortCommit()`
- `setSessionId`, `extensionKinds`, `createCallback`, `getActivity`

`finishCommit()` posts one immutable `RenderTransaction` to the UI
thread. Python-side calls never touch Views.

## Related

- [protocol.md](protocol.md) — the logical messages being transported
- [android-host/overview.md](../android-host/overview.md) — DirectRenderHost
- [android-host/renderer.md](../android-host/renderer.md) — what happens on the UI thread
