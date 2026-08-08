"""Minimal hook-style state for user components.

Vyne state uses a React-like pattern: each ``state(initial)`` call during a
render allocates a mutable ``State`` cell backed by an ordered list in its
owning component scope. On re-render, calls are matched to cells by index — so
hooks must not be conditional or reordered within that component.

The runtime is propagated via ``ContextVar`` (thread/async-safe TLS pattern)
so that ``state()`` can find the current Runtime at CREATION time; every
cell is then permanently bound to that owner, so writes never re-lookup.

Render-phase mutation guard (SCHED-03): State.set() checks the Runtime's
current phase and raises RenderPhaseMutationError if called during render.
This prevents accidental infinite loops and partial publication.

State journal (COORD-05): during a flush (event dispatch + render pass),
State.set() records mutations in the Runtime's StateJournal.  On flush
failure (handler error, render error, encode error, or transport error),
the journal rolls back all mutated State cells to their pre-flush values.
On flush success, the journal is committed.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Generic, Iterator, Protocol, TypeVar

T = TypeVar("T")

_CURRENT_RUNTIME: ContextVar[Any] = ContextVar("vyne_runtime", default=None)


class StateHost(Protocol):
    """The narrow interface a State cell needs from its owning Runtime.

    Every cell is bound to exactly one owner at creation; writes go through
    ``set_state`` — no ContextVar lookup, no attribute probes.
    """

    def set_state(self, cell: "State[Any]", value: Any) -> None: ...

    def render_phase(self) -> str | None: ...


def current_runtime() -> Any:
    """Return the Runtime active on this execution context, if any."""
    return _CURRENT_RUNTIME.get()


@dataclass
class State(Generic[T]):
    """Mutable state cell with automatic re-render on change.

    ``.value`` is read-only; call ``.set(new_value)`` to update.  Setting
    the same value (by equality) is a no-op — no re-render is triggered.
    The re-render callback and the owning Runtime are bound at creation
    time (``Runtime.use_state`` passes itself as the ``owner``), so state
    changes always flow back to the correct Runtime instance.

    Render-phase mutation guard: ``.set()`` during a render pass raises
    ``RenderPhaseMutationError``.  State mutations must be driven by event
    handlers or animation callbacks.

    State journal (COORD-05): when the owner Runtime's StateJournal is
    active, the write is recorded in the journal.  If the flush fails, the
    journal rolls back all mutations.
    """
    _value: T
    _request_render: Any
    _owner: StateHost | None = None

    @property
    def value(self) -> T:
        """The current state value."""
        return self._value

    def set(self, value: T) -> None:
        """Set a new value, triggering a re-render.

        Delegates to the owning Runtime's ``set_state`` (phase guard, async
        callback fast path, state journal) — one write path, no probes.
        """
        if value == self._value:
            return
        owner = self._owner
        if owner is None:
            raise RuntimeError("State cell has no owning Runtime")
        owner.set_state(self, value)


def state(initial: T) -> State[T]:
    """Create or reuse a reactive state cell.

    Must be called inside a component function while the Runtime is rendering.
    The Runtime is retrieved from the ``CURRENT_RUNTIME`` ContextVar — set
    by ``runtime_context()`` at the render boundary.
    """
    runtime = _CURRENT_RUNTIME.get()
    if runtime is None:
        raise RuntimeError("state() can only be used while rendering a component")
    return runtime.use_state(initial)


@contextmanager
def runtime_context(runtime: Any) -> Iterator[None]:
    """Temporarily set the current Runtime so hooks can find it.

    Used by the Runtime itself before calling user components, and by the
    Android host before dispatching events.
    """
    token = _CURRENT_RUNTIME.set(runtime)
    try:
        yield
    finally:
        _CURRENT_RUNTIME.reset(token)
