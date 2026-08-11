"""Small private helpers shared by the fixed and generic list engines.

M4 extracted these from duplicated controller/render code in
``_lists/fixed.py`` and ``_lists/generic.py``.  Both engines keep their own
planning, composition, and binding machinery: the fixed engine is the O(1)
benchmark specialization and the generic engine accepts arbitrary placements.
Only the genuinely identical pieces live here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from vyne._lists.source import KeyRegistry, VirtualizedDataSource


def derive_candidate_key_registry(
    accepted: KeyRegistry | None,
    seed: KeyRegistry | None,
    source: VirtualizedDataSource,
    key_for_item: Callable[[Any, int], Any] | None,
) -> KeyRegistry | None:
    """Build the candidate registry without mutating accepted state.

    An explicit ``seed`` (used by direct composition tests) is returned as-is
    and owned by the caller.  Otherwise the accepted registry is cloned when
    it still describes the current data, and a fresh registry is seeded from
    the source otherwise.  Sources with default index keys need no registry:
    their keys are unique by construction.
    """
    if seed is not None:
        return seed
    if getattr(source, "uses_index_keys", False):
        return None
    item_count = source.item_count
    data = getattr(source, "data", source)
    if accepted is not None and not accepted.stale(data, key_for_item, item_count):
        return accepted.copy()
    fresh = KeyRegistry()
    fresh.data = data
    fresh.key_for_item = key_for_item
    fresh.item_count = item_count
    return fresh


def resolve_alignment_offset(
    *,
    alignment: Literal["start", "center", "end", "nearest"],
    main_start: float,
    main_end: float,
    viewport_offset: float,
    viewport_extent: float,
    max_offset: float,
) -> float | None:
    """Main-axis scroll target for one alignment, or None when already there.

    ``None`` means no scroll is needed: the item is already fully visible
    (``nearest``) or the target equals the current offset.  ``max_offset`` is
    the content scroll bound (``max(0, content - viewport)``); every target
    is clamped into ``[0, max_offset]`` so a target near the content end
    never plans beyond the declared extent.
    """
    if alignment == "start":
        return min(max(0.0, main_start), max_offset)
    if alignment == "center":
        return min(max(0.0, (main_start + main_end - viewport_extent) / 2), max_offset)
    if alignment == "end":
        return min(max(0.0, main_end - viewport_extent), max_offset)
    viewport_end = viewport_offset + viewport_extent
    if main_start >= viewport_offset and main_end <= viewport_end:
        return None
    start_target = min(main_start, max_offset)
    end_target = min(max(0.0, main_end - viewport_extent), max_offset)
    target = (
        start_target
        if abs(start_target - viewport_offset) <= abs(end_target - viewport_offset)
        else end_target
    )
    if target == viewport_offset:
        return None
    return target


def resolve_key_index(
    *,
    key: Any,
    source: VirtualizedDataSource,
    key_registry: KeyRegistry | None,
) -> int | None:
    """Resolve one stable key to its current index without scanning.

    The accepted per-occurrence key registry answers for already-realized
    keys, and an optional source ``index_for_key`` answers for the rest.
    ``None`` means the key cannot be resolved; no full-source scan is ever
    performed.  A malformed ``index_for_key`` result raises a clear error.
    """
    index: int | None = None
    if key_registry is not None:
        index = key_registry.key_to_index.get(key)
    if index is None:
        index_for_key = getattr(source, "index_for_key", None)
        if callable(index_for_key):
            candidate = index_for_key(key)
            if candidate is not None:
                if type(candidate) is not int:
                    raise TypeError(
                        "source index_for_key must return an integer or None"
                    )
                if candidate < 0 or candidate >= source.item_count:
                    raise IndexError(
                        f"source index_for_key returned out-of-range index "
                        f"{candidate}"
                    )
                index = candidate
    return index
