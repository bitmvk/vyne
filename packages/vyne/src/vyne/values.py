"""Canonical immutable value types for Vyne.

Provides FrozenMap (an immutable, hashable ordered mapping with string-only
keys), recursive freeze/thaw, and exact scalar rules for colors, dimensions,
dash arrays, and finite numeric values that cross the Pyothon/native boundary.
"""

from __future__ import annotations

import math
import re
from collections.abc import ItemsView, KeysView, Mapping, ValuesView
from dataclasses import is_dataclass
from typing import Any, Iterator


# ---------------------------------------------------------------------------
# Canonical key domain
# ---------------------------------------------------------------------------

def is_canonical_key(value: Any) -> bool:
    """Return True if *value* is a valid canonical Element key.

    Accepted keys: exact strings, exact integers excluding bool, and
    recursively immutable tuples of canonical key atoms.
    """
    if type(value) is str:
        return True
    if type(value) is int:
        return True
    if type(value) is tuple:
        return all(is_canonical_key(item) for item in value)
    return False


def validate_canonical_key(value: Any, *, path: str = "key") -> None:
    """Raise TypeError if *value* is not a valid canonical Element key."""
    if not is_canonical_key(value):
        raise TypeError(
            f"{path} must be a string, non-bool int, or recursively immutable "
            f"tuple of such keys, got {type(value).__name__}: {value!r}"
        )


# ---------------------------------------------------------------------------
# FrozenMap — immutable, string-key-only ordered mapping
# ---------------------------------------------------------------------------

class FrozenMap(Mapping[str, Any]):
    """An immutable, hashable ordered mapping with string-only keys.

    Construction accepts an iterable of (str, value) pairs.  Duplicate keys
    are rejected.  Keys, values, and items iterate in insertion order.
    Equality is order-independent (like a frozen dict).
    """

    __slots__ = ("_keys", "_values", "_hash")

    def __init__(self, items: Any = ()) -> None:
        if isinstance(items, FrozenMap):
            self._keys = items._keys
            self._values = items._values
            self._hash = items._hash
            return
        keys: list[str] = []
        values: list[Any] = []
        for k, v in items:
            if not isinstance(k, str):
                raise TypeError(f"FrozenMap keys must be strings, got {type(k).__name__}")
            keys.append(k)
            values.append(v)
        self._check_duplicate_keys(keys)
        self._keys: tuple[str, ...] = tuple(keys)
        self._values: tuple[Any, ...] = tuple(values)
        self._hash: int | None = None

    @staticmethod
    def _check_duplicate_keys(keys: list[str]) -> None:
        seen: set[str] = set()
        for i, k in enumerate(keys):
            if k in seen:
                raise ValueError(f"Duplicate key {k!r} in FrozenMap")
            seen.add(k)

    def __getitem__(self, key: str) -> Any:
        try:
            idx = self._keys.index(key)
        except ValueError:
            raise KeyError(key) from None
        return self._values[idx]

    def __len__(self) -> int:
        return len(self._keys)

    def __iter__(self) -> Iterator[str]:
        return iter(self._keys)

    def keys(self) -> KeysView[str]:  # type: ignore[override]
        return KeysView(self)

    def values(self) -> ValuesView[Any]:  # type: ignore[override]
        return ValuesView(self)

    def items(self) -> ItemsView[str, Any]:  # type: ignore[override]
        return ItemsView(self)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: object) -> bool:
        return key in self._keys

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FrozenMap):
            if len(self) != len(other):
                return False
            for k in self._keys:
                if k not in other or self._values[self._keys.index(k)] != other[k]:
                    return False
            return True
        if isinstance(other, Mapping):
            if len(self) != len(other):
                return False
            for k, v in self.items():
                if k not in other or other[k] != v:
                    return False
            return True
        return NotImplemented

    def __hash__(self) -> int:
        if self._hash is None:
            h = 0
            for k, v in self.items():
                h ^= hash((k, _make_hashable(v)))
            object.__setattr__(self, "_hash", h)
        return self._hash

    def __repr__(self) -> str:
        items = ", ".join(f"{k!r}: {v!r}" for k, v in self.items())
        return f"FrozenMap({{{items}}})"

    def with_item(self, key: str, value: Any) -> FrozenMap:
        """Return a new FrozenMap with *key* set to *value* (add or replace)."""
        new_items = [(k, v) for k, v in self.items() if k != key]
        new_items.append((key, value))
        return FrozenMap(new_items)

    def without(self, key: str) -> FrozenMap:
        """Return a new FrozenMap with *key* removed."""
        if key not in self:
            return self
        return FrozenMap([(k, v) for k, v in self.items() if k != key])

    @staticmethod
    def from_dict(d: Mapping[str, Any], *, deep: bool = False) -> FrozenMap:
        """Create a FrozenMap from a plain dict.

        When *deep* is True, nested dicts and lists are recursively frozen
        so the entire value tree is immutable (MODEL-03).
        """
        if deep:
            return FrozenMap((k, freeze(v)) for k, v in d.items())
        return FrozenMap(d.items())


def _make_hashable(value: Any) -> Any:
    """Recursively convert a value to something hashable."""
    if isinstance(value, dict):
        return tuple(sorted((k, _make_hashable(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_make_hashable(v) for v in value)
    if isinstance(value, set):
        return tuple(sorted(_make_hashable(v) for v in value))
    return value


# ---------------------------------------------------------------------------
# Recursive freeze / thaw
# ---------------------------------------------------------------------------

def freeze(value: Any) -> Any:
    """Return a recursively immutable, caller-independent public value.

    Only callbacks, ``Ref``/``ViewHandle`` tokens, and frozen framework
    dataclasses are opaque.  Unknown objects are rejected rather than retained
    by reference, because their later mutation would invalidate Element hashes
    and reconciliation output.
    """
    if value is None or type(value) in (bool, int, float, str, bytes):
        return value
    if callable(value):
        return value
    if isinstance(value, FrozenMap):
        return FrozenMap((k, freeze(v)) for k, v in value.items())
    if isinstance(value, Mapping):
        return FrozenMap((k, freeze(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    if isinstance(value, (set, frozenset, bytearray, memoryview)):
        raise TypeError(
            f"Unsupported public value container {type(value).__name__}; "
            "use a string-key mapping or sequence"
        )

    # Avoid a module-level import cycle (refs imports no value helpers today,
    # but Element/value construction should not depend on that remaining so).
    from vyne.refs import Ref, ViewHandle

    if isinstance(value, (Ref, ViewHandle)):
        return value

    params = getattr(type(value), "__dataclass_params__", None)
    if (
        is_dataclass(value)
        and params is not None
        and params.frozen
        and type(value).__module__.startswith("vyne.")
    ):
        return value

    raise TypeError(
        f"Unsupported mutable or opaque public value {type(value).__name__}"
    )


def thaw(value: Any) -> Any:
    """Recursively convert an immutable structure back to mutable Python objects.

    - FrozenMap → dict (recurse on values)
    - tuple → list (recurse on items)
    - str, int, float, bool, None → pass through
    """
    if isinstance(value, FrozenMap):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [thaw(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Exact scalar rules
# ---------------------------------------------------------------------------

_COLOR_HEX_RE = re.compile(r"^#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?$")

# Known dimension special tokens for later protocol use.
_DIMENSION_TOKENS = frozenset({"wrap_content", "match_parent"})


def is_valid_color(value: Any) -> bool:
    """Return True if *value* is a canonical ``#RRGGBB`` or ``#RRGGBBAA`` string."""
    if not isinstance(value, str):
        return False
    return bool(_COLOR_HEX_RE.match(value))


def is_finite_number(value: Any) -> bool:
    """Return True if *value* is an int or finite float (not bool)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def validate_finite(value: Any, *, name: str = "value") -> float | int:
    """Raise if *value* is not a finite number; return the value."""
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a finite int or float, got bool")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite, got {value}")
        return value
    raise TypeError(f"{name} must be a finite int or float, got {type(value).__name__}")


def validate_positive(value: Any, *, name: str = "value") -> float | int:
    """Raise if *value* is not a positive finite number."""
    validate_finite(value, name=name)
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


def validate_non_negative(value: Any, *, name: str = "value") -> float | int:
    """Raise if *value* is not a non-negative finite number."""
    validate_finite(value, name=name)
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value}")
    return value


def is_valid_dash_array(value: Any) -> bool:
    """Return True if *value* is a tuple of positive finite numbers, even length.

    Empty tuple is accepted as a valid "no dash" state.
    """
    if not isinstance(value, (list, tuple)):
        return False
    if len(value) % 2 != 0:
        return False
    return all(is_finite_number(v) and v > 0 for v in value)


def validate_dash_array(value: Any, *, name: str = "dash") -> tuple[float | int, ...]:
    """Raise if *value* is not a valid canonical dash array.

    Empty tuple is accepted as a valid "no dash" state.
    """
    if not isinstance(value, tuple):
        raise TypeError(f"{name} must be a tuple, got {type(value).__name__}")
    if len(value) % 2 != 0:
        raise ValueError(f"{name} must have even length, got {len(value)}")
    for i, v in enumerate(value):
        if not is_finite_number(v) or v <= 0:
            raise ValueError(f"{name}[{i}] must be a positive finite number, got {v}")
    return value
