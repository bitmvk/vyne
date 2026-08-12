"""Selection value normalization for Material selection components.

Controlled callbacks (``on_change`` / ``on_select`` / ``on_click``) are
invoked directly with their documented value argument; zero-argument event
callbacks are handled by the core event registry.  This module only owns
selection-value validation for ButtonGroup / SegmentedButtonGroup.
"""

from __future__ import annotations

from typing import Any


def normalize_selection(
    selected: Any,
    items: list[Any],
    *,
    multi: bool = False,
) -> frozenset[Any] | Any:
    """Normalize and validate selection values for ButtonGroup/SegmentedButtonGroup.

    Rules:
    * Item values must be unique and hashable.
    * Strings and bytes are never split into multi-character selections.
    * For scalar (non-multi) selection: returns the single selected value
      (or ``None``).
    * For multi selection: returns a ``frozenset`` of selected values.
    * Falsy values (``None``, ``0``, ``False``, empty container) are
      treated as empty selection — never as ``False == unselected``
      while ``True == selected`` for boolean item values.

    Raises TypeError or ValueError with a precise message on invalid input.
    """
    # Validate item values first.
    item_values = [item.value if hasattr(item, 'value') else item for item in items]
    seen: set[Any] = set()
    for val in item_values:
        if val in seen:
            raise ValueError(
                f"Duplicate item value {val!r}; selection values must be unique"
            )
        seen.add(val)
        if not _is_hashable(val):
            raise TypeError(
                f"Item value {val!r} is not hashable; "
                f"all selection values must be hashable"
            )

    if multi:
        return _normalize_multi_selection(selected, item_values)
    return _normalize_scalar_selection(selected, item_values)


def _is_hashable(value: Any) -> bool:
    try:
        hash(value)
        return True
    except TypeError:
        return False


def _normalize_scalar_selection(selected: Any, item_values: list[Any]) -> Any:
    """Normalize a single-selection value."""
    if selected is None:
        return None
    # Reject string/bytes that could be mistakenly split.
    if isinstance(selected, (str, bytes)):
        # Strings are valid item values (e.g. "a"); pass through if it
        # matches an item value exactly.
        if selected in item_values:
            return selected
        # A string that doesn't match any item is an error.
        raise ValueError(
            f"Selected value {selected!r} does not match any item value. "
            f"Valid values: {item_values}"
        )
    if isinstance(selected, bool):
        # bool is valid as an item value.
        if selected in item_values:
            return selected
        raise ValueError(
            f"Selected value {selected!r} does not match any item value"
        )
    if not _is_hashable(selected):
        raise TypeError(
            f"Selected value {selected!r} is not hashable"
        )
    if selected not in item_values:
        raise ValueError(
            f"Selected value {selected!r} does not match any item value. "
            f"Valid values: {item_values}"
        )
    return selected


def _normalize_multi_selection(selected: Any, item_values: list[Any]) -> frozenset[Any]:
    """Normalize a multi-selection value to an immutable frozenset."""
    if selected is None:
        return frozenset()
    if isinstance(selected, (str, bytes)):
        raise TypeError(
            "Multi-select does not accept strings; "
            f"pass an iterable of values instead. Got {selected!r}"
        )
    if isinstance(selected, bool):
        raise TypeError(
            "Multi-select does not accept bool; "
            "pass an iterable of values instead"
        )
    try:
        values = set(selected)
    except TypeError as exc:
        raise TypeError(
            f"Multi-select requires an iterable of values, got {type(selected).__name__}"
        ) from exc
    unknown = values - set(item_values)
    if unknown:
        raise ValueError(
            f"Selected values {sorted(unknown)} do not match any item value. "
            f"Valid values: {item_values}"
        )
    # Reject unhashable elements in the selection set.
    for val in values:
        if not _is_hashable(val):
            raise TypeError(f"Selected value {val!r} is not hashable")
    return frozenset(values)
