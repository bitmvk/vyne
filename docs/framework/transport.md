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

Publishes logical commits through one JSON bridge call per commit. There is
no message envelope, opcode table, or binary codec.

Key properties:

- `preflights_commits = True` — the Kotlin transaction builder and
  Renderer preflight validate the stream, so the runtime skips the legacy
  JSON-envelope validation pass
- session id published on the host before the first commit, so native
  receipts carry the real session id (design-pattern #1)

### One JSON commit call

`DirectTransport.send` serializes the whole ordered op stream with
`json.dumps` into one compact document — `{"revision": N, "ops": [...]}` —
and hands it to a single `commitJson` entry point. One JNI crossing carries
an entire commit, whatever its size or shape: fresh mounts, dense property
updates, and mixed streams all use the same call.

The Kotlin side decodes the document with org.json into a
`RenderTransaction` and posts it to the UI thread. Any decode error aborts
the transaction and propagates to Python, which rolls back the framework
(stateful values like `set_prop` scalars, nested containers, and animation
payloads cross the boundary as plain JSON).

### Host method surface

`DirectRenderHost` exposes a small stable surface:

- `commitJson(json)` — one commit per call
- `setSessionId`, `extensionKinds`, `createCallback`, `getActivity`

`commitJson` posts one immutable `RenderTransaction` to the UI
thread. Python-side calls never touch Views.

## Related

- [protocol.md](protocol.md) — the logical messages being transported
- [android-host/overview.md](../android-host/overview.md) — DirectRenderHost
- [android-host/renderer.md](../android-host/renderer.md) — what happens on the UI thread
