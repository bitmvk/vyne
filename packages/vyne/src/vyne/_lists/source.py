"""Private random-access data-source contracts for virtualized lists."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from vyne.values import validate_canonical_key


@runtime_checkable
class VirtualizedDataSource(Protocol):
    """Random-access item and identity adapter used by the list engine."""

    @property
    def item_count(self) -> int: ...

    def item_at(self, index: int) -> Any: ...

    def key_at(self, index: int) -> Any: ...


@dataclass(frozen=True)
class TupleDataSource:
    """Strict immutable source used by internal tests and future adapters."""

    items: tuple[Any, ...]
    keys: tuple[Any, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple) or not isinstance(self.keys, tuple):
            raise TypeError("TupleDataSource items and keys must be tuples")
        if len(self.items) != len(self.keys):
            raise ValueError("TupleDataSource items and keys must have equal lengths")
        seen: set[Any] = set()
        for index, key in enumerate(self.keys):
            validate_canonical_key(key, path=f"list key at index {index}")
            if key in seen:
                raise ValueError(f"Duplicate list key {key!r} at index {index}")
            seen.add(key)

    @property
    def item_count(self) -> int:
        return len(self.items)

    def item_at(self, index: int) -> Any:
        return self.items[index]

    def key_at(self, index: int) -> Any:
        return self.keys[index]
