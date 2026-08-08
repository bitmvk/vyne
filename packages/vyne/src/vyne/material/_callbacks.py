"""One-time callback inspection and adapter for Material value handlers.

Every component that accepts ``on_change`` / ``on_select`` / ``on_click``
etc. inspects the callback signature **once** at construction time and reuses
the same adapter for every gesture.  This avoids repeated ``inspect.signature``
calls and ensures unsupported signatures fail fast.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

Callback = Callable[..., Any]


class CallbackAdapter:
    """Inspects a callback signature once, then routes values efficiently.

    Construction-time behaviour:
    * Tries ``signature.bind(value)`` first to confirm the callback can
      accept a single positional argument.
    * If that fails, tries ``signature.bind()`` for zero-argument callbacks.
    * If neither succeeds, raises TypeError at construction time so
      unsupported signatures fail fast.
    * Built-ins and objects without a valid ``__signature__`` are treated as
      value-accepting (defensive / ``inspect.signature`` raises).
    * Inspection happens exactly once; the resolved flags are immutable.
    """

    __slots__ = ("_callback", "_accepts_positional")

    def __init__(self, callback: Callback) -> None:
        self._callback = callback
        try:
            sig = inspect.signature(callback)
        except (TypeError, ValueError):
            # Built-ins and objects without inspectable signatures:
            # treat as value-accepting.
            self._accepts_positional = True
            return

        sentinel = object()
        try:
            sig.bind(sentinel)
        except TypeError:
            try:
                sig.bind()
            except TypeError as no_value_error:
                raise TypeError(
                    "Callback must accept exactly one positional value or no arguments"
                ) from no_value_error
            self._accepts_positional = False
        else:
            self._accepts_positional = True

    def invoke(self, value: Any) -> None:
        """Call the wrapped callback with or without *value*."""
        if self._accepts_positional:
            self._callback(value)
        else:
            self._callback()


def prepare_handler(callback: Callback | None, value: Any) -> Callable[[Any], None] | None:
    """Create an event handler that invokes *callback* with *value*.

    The adapter is inspected once; the returned closure delegates every
    subsequent gesture to the adapter.
    """
    if callback is None:
        return None
    adapter = CallbackAdapter(callback)

    def handler(_event: Any) -> None:
        adapter.invoke(value)

    return handler


def prepare_value_binding(callback: Callback) -> CallbackAdapter:
    """Inspect *callback* once, then use ``adapter.invoke(value)`` inline.

    Designed for components that calculate a different value per event
    (sliders, date cells) and need to call the adapter directly.
    """
    return CallbackAdapter(callback)


# ---------------------------------------------------------------------------
# Selection normalizer (MATERIAL-02)
# ---------------------------------------------------------------------------


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
