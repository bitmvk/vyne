# Networking

Vyne core ships **no network API and no permissions**. The runtime is a
standard asyncio loop, so any Python networking approach works; which one is
the app's choice.

## Permissions

Networking requires the app to declare the permission it uses. Add it to the
generated `android/.../AndroidManifest.xml`:

```xml
<uses-permission android:name="android.permission.INTERNET" />
```

Without it, sockets fail immediately (DNS errors like `[Errno 7] No address
associated with hostname`).

## The stdlib path: urllib

`urllib` is bundled and works on-device. Its API is blocking, so run it in a
thread from an async handler:

```python
import asyncio
import urllib.request

async def fetch(url: str) -> bytes:
    def _get() -> bytes:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.read()
    return await asyncio.to_thread(_get)
```

HTTPS, TLS certificate verification, redirects, and timeouts all work with the
bundled runtime. `to_thread` spawns a thread per call — fine for occasional
fetches; bound concurrency with a shared `ThreadPoolExecutor` or a semaphore
when loading many resources at once.

### Mobile gotcha: IPv6-first timeouts

Python's `socket.create_connection` tries addresses in `getaddrinfo` order
with one socket timeout per address (no Happy Eyeballs). On networks where
DNS returns unroutable IPv6 records first — common on mobile and Wi-Fi —
the first connect blocks until the timeout before falling back to IPv4, and
every redirect pays it again (a two-hop redirect can cost 30s+). Resolve
IPv4-first and keep the connect timeout short:

```python
import socket
import urllib.parse
import urllib.request

def _resolve_ipv4(host: str, port: int):
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return sorted(infos, key=lambda info: 0 if info[0] == socket.AF_INET else 1)

def _connect(host: str, port: int):
    failures = []
    for info in _resolve_ipv4(host, port):
        try:
            return socket.create_connection(info[4], timeout=5)
        except OSError as exc:
            failures.append(str(exc))
    raise ConnectionError(f"connect failed: {failures}")
```

Or, for occasional fetches, a bounded timeout alone caps the worst case:
`urllib.request.urlopen(url, timeout=5)`.

## Recommended: aiohttp

For real async networking — concurrent loads, streaming, WebSocket — install
`aiohttp` in the generated project's Gradle build (`chaquopy` pip config).
aiohttp is coroutine-based: no threads, real cancellation, and it drops
directly into async handlers:

```python
import aiohttp

async with aiohttp.ClientSession() as session:
    async with session.get(url) as response:
        data = await response.read()
```

`httpx` (async client, HTTP/2) and `websockets` are good alternatives. All
third-party networking packages are ecosystem: installed per app, never part
of Vyne core.

## Remote images

The `Image` widget accepts a data URI (`data:image/png;base64,...`) as its
`source`. The app fetches the bytes, base64-encodes them, and passes the URI —
one commit, no files, no framework network code:

```python
import asyncio
import base64
import urllib.request

async def load_image(url: str) -> None:
    data = await asyncio.to_thread(_fetch, url)
    image_source.set("data:image/png;base64," + base64.b64encode(data).decode())

# render
Image(source=image_source.value, width=120, height=120)
```

The previous bitmap stays visible until the new one lands; decodes run off the
UI thread and are cached in memory by source, so re-renders and list cells
that reuse a source never re-decode.
