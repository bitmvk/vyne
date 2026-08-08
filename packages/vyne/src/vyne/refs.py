"""Per-mount references and handles for imperative operations.

``Ref`` provides a stable per-occurrence reference to a mounted native view.
It is created by the user, passed to an Element via the ``ref`` prop, and
resolved by the Runtime when the element is mounted.

``ViewHandle`` is a read-only token that the Runtime issues after mounting.
It invalidates when the target view is replaced, removed, or disposed.

Neither Ref nor ViewHandle is stored on the Element itself.  Runtime identity
lives on the RenderNode exclusively.
"""

from __future__ import annotations

class Ref:
    """A per-occurrence, per-session reference to a native view.

    Usage::

        ref = Ref()
        element = Box(ref=ref)
        # After mount: ref.current returns a ViewHandle
    """

    __slots__ = ("_handle", "_mounted")

    def __init__(self) -> None:
        self._handle: ViewHandle | None = None
        self._mounted: bool = False

    @property
    def current(self) -> ViewHandle | None:
        """Return the current ViewHandle, or None if not mounted/invalidated."""
        return self._handle

    def attach(self, handle: ViewHandle) -> None:
        """Bind this Ref to a ViewHandle (called by Runtime)."""
        if self._mounted:
            raise RuntimeError("Ref is already attached to a live view")
        self._handle = handle
        self._mounted = True

    def invalidate(self) -> None:
        """Mark the Ref as no longer valid (called by Runtime)."""
        handle = self._handle
        if handle is not None:
            handle._invalidate()
        self._handle = None
        self._mounted = False

    def __repr__(self) -> str:
        state = "attached" if self._mounted else "unmounted"
        return f"Ref({state})"


class ViewHandle:
    """A read-only token representing a mounted native view.

    Issued by the Runtime and stored by the Ref.  The handle becomes
    invalid (stale) after the target node is removed, replaced, or
    the runtime is disposed.
    """

    __slots__ = ("_node_id", "_kind", "_valid")

    def __init__(self, node_id: int, kind: str) -> None:
        self._node_id: int = node_id
        self._kind: str = kind
        self._valid: bool = True

    @property
    def node_id(self) -> int:
        """The immutable node identifier (monotonic, not reused)."""
        return self._node_id

    @property
    def kind(self) -> str:
        """The primitive kind of the mounted view."""
        return self._kind

    @property
    def valid(self) -> bool:
        """True while the target node is still mounted and live."""
        return self._valid

    def _invalidate(self) -> None:
        self._valid = False

    def __repr__(self) -> str:
        state = "valid" if self._valid else "stale"
        return f"ViewHandle(node={self._node_id}, kind={self._kind!r}, {state})"
