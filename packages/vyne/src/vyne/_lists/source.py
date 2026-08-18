"""Private random-access data-source adapters for virtualized lists.

The source contract itself (``VirtualData``) lives in the public contracts
module; this file provides the key registry and the plain-Sequence adapter.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from vyne.values import validate_canonical_key


class KeyRegistry:
    """Per-mounted-list key tracking for lazy sources.

    Records ``key -> index`` as cells are realized so a duplicate key that
    appears at two different indices of the same data is rejected even when
    the two occurrences are never realized in the same window.  The registry
    is owned by one mounted list occurrence and is reset when the data
    object, the key callback, or the item count changes.  That keeps
    state-driven replacement and reordering valid without scanning the
    whole source, while preserving lazy O(realized) behavior.

    The registry is never mutated during a candidate render: the engine
    derives a ``copy()`` for the candidate and promotes it through the
    accepted controller binding, so a rejected or unknown commit leaves the
    accepted key mappings untouched.
    """

    __slots__ = ("data", "key_for_item", "item_count", "key_to_index")

    def __init__(self) -> None:
        self.data: Any = None
        self.key_for_item: Callable[[Any, int], Any] | None = None
        self.item_count: int | None = None
        self.key_to_index: dict[Any, int] = {}

    def copy(self) -> "KeyRegistry":
        """Return a detached clone for one candidate render."""
        clone = KeyRegistry()
        clone.data = self.data
        clone.key_for_item = self.key_for_item
        clone.item_count = self.item_count
        clone.key_to_index = dict(self.key_to_index)
        return clone

    def stale(
        self,
        data: Any,
        key_for_item: Callable[[Any, int], Any] | None,
        item_count: int,
    ) -> bool:
        """True when this registry belongs to different data or keys."""
        return (
            self.data is not data
            or self.key_for_item is not key_for_item
            or self.item_count != item_count
        )

    def reset(
        self,
        data: Any,
        key_for_item: Callable[[Any, int], Any] | None,
        item_count: int,
    ) -> None:
        """Re-point the registry at a new data object and clear its keys."""
        self.data = data
        self.key_for_item = key_for_item
        self.item_count = item_count
        self.key_to_index.clear()


class SequenceDataSource:
    """O(1)-construction lazy adapter over a plain ``Sequence``.

    The public list never copies the data or precomputes every key.  Items
    and keys are read only for the realized window, so mounting or scrolling
    a huge list costs work proportional to the visible cells instead of the
    whole sequence.  ``key_at`` validates the canonical-key domain on access;
    duplicate-key rejection happens at composition time for the realized set
    and, across windows, through a ``KeyRegistry`` owned by the mounted list.
    """

    __slots__ = ("_data", "_key_for_item")

    def __init__(
        self,
        data: Sequence[Any],
        key_for_item: Callable[[Any, int], Any] | None = None,
    ) -> None:
        self._data = data
        self._key_for_item = key_for_item

    @property
    def data(self) -> Sequence[Any]:
        """The wrapped sequence, used as the registry's data identity."""
        return self._data

    @property
    def item_count(self) -> int:
        return len(self._data)

    @property
    def uses_index_keys(self) -> bool:
        """True when keys default to the item index (unique by construction)."""
        return self._key_for_item is None

    def item_at(self, index: int) -> Any:
        return self._data[index]

    def key_at(self, index: int) -> Any:
        if self._key_for_item is None:
            return index
        key = self._key_for_item(self._data[index], index)
        validate_canonical_key(key, path=f"list key at index {index}")
        return key

    def index_for_key(self, key: Any) -> int | None:
        """Resolve one key to its index in O(1), or None.

        Default index keys are unique by construction, so the answer is a
        pure in-range check.  Custom key callbacks are never scanned: the
        per-list key registry and optional ``VirtualData.index_for_key``
        own those lookups, and ``key_for_item`` must be a pure function of
        the item and index (never the reverse).
        """
        if self._key_for_item is not None:
            return None
        if isinstance(key, bool) or not isinstance(key, int):
            return None
        if 0 <= key < len(self._data):
            return key
        return None
