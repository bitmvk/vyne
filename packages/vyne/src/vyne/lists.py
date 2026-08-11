"""Public list surface: the fixed ``List``, the generic ``VirtualList``, and contracts.

The fixed ``List`` renders a windowed fixed-extent list on the private
virtualization engine, which owns window selection, projection, and
rendering.

``VirtualList`` is the generic engine (M2): it consumes the M1 contracts and a
``VirtualLayout`` strategy, composes positioned realized cells from ordinary
primitives, feeds per-cell measurements back into the layout, and supports
imperative scrolling.

One public :class:`ListController` drives either component.  It owns the two
private engine controllers (the O(1) fixed planner and the generic placement
engine) and dispatches every command to whichever one is currently bound, so
a single controller can drive a ``List`` or a ``VirtualList`` with the same
API.  The private engines are internal machinery, not public concepts; a
controller bound to more than one mounted list raises clearly.

``VirtualData``, ``ViewportRect``, ``CellMeasurement``,
``StickyConstraint``, ``VirtualPlacement``, ``LayoutResult``,
``LayoutRequest``, ``VirtualLayout``, ``FixedLinearLayout``, and
``select_placements`` are pure and host-independent building blocks for custom
2D layouts.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import math
from typing import Any, Literal

from vyne._lists.contracts import (
    CellMeasurement,
    FixedLinearLayout,
    LayoutRequest,
    LayoutResult,
    StickyConstraint,
    ViewportRect,
    VirtualData,
    VirtualLayout,
    VirtualPlacement,
    select_placements,
)
from vyne._lists.fixed import (
    FixedVirtualListController,
    FixedVirtualListSpec,
    render_fixed_virtual_list,
)
from vyne._lists.generic import (
    GenericVirtualListController,
    VirtualListSpec,
    render_generic_virtual_list,
)
from vyne._lists.model import IndexRange, RenderMask, WindowConfig
from vyne._lists.source import SequenceDataSource
from vyne.component import component
from vyne.elements import Element
from vyne.state import current_runtime, state
from vyne.values import FrozenMap


class ListController:
    """Imperative control for one mounted :class:`List` or :class:`VirtualList`.

    A controller attaches to the component it is passed to. It binds on mount
    and reports an error when the component is not mounted. One controller may
    drive exactly one mounted list at a time: when it is accidentally bound to
    two mounted lists (for example the same controller passed to both a
    ``List`` and a ``VirtualList`` in one tree), every command raises a clear
    error instead of acting on one of them. Use ``key=...`` when sibling lists
    can reorder so the controller follows the logical list.
    """

    def __init__(self) -> None:
        self._fixed = FixedVirtualListController()
        self._generic = GenericVirtualListController()

    def _bound_engine(
        self,
    ) -> FixedVirtualListController | GenericVirtualListController:
        """Return the single bound engine; raise if zero or multiple bind."""
        fixed_bound = self._fixed.is_mounted
        generic_bound = self._generic.is_mounted
        if fixed_bound and generic_bound:
            raise RuntimeError(
                "This ListController is bound to more than one mounted list. "
                "Use a separate controller per list, or pass key=... so a "
                "shared controller can follow a reordering list."
            )
        if fixed_bound:
            return self._fixed
        if generic_bound:
            return self._generic
        raise RuntimeError("List controller is not mounted to a list")

    def scroll_to_offset(self, offset: float, *, animated: bool) -> None:
        """Scroll to an explicit main-axis offset."""
        self._bound_engine().scroll_to_offset(offset, animated=animated)

    def scroll_to_index(
        self,
        index: int,
        *,
        alignment: Literal["start", "center", "end", "nearest"],
        animated: bool,
    ) -> None:
        """Scroll one item into an explicitly aligned viewport position."""
        self._bound_engine().scroll_to_index(
            index, alignment=alignment, animated=animated
        )

    def scroll_to_key(
        self,
        key: Any,
        *,
        alignment: Literal["start", "center", "end", "nearest"],
        animated: bool,
    ) -> None:
        """Scroll a stable source key into the viewport.

        Resolution never scans the source: a plain ``Sequence`` with default
        index keys answers in O(1), the per-list key registry answers for
        already-realized keys, and an optional ``VirtualData.index_for_key``
        answers for the rest.  Any other key raises without a scan.
        """
        self._bound_engine().scroll_to_key(key, alignment=alignment, animated=animated)


@component
def _list_component(
    list_key: Any,
    data: Sequence[Any],
    render_item: Callable[[Any, int], Element],
    key_for_item: Callable[[Any, int], Any] | None,
    item_extent: float,
    axis: Literal["vertical", "horizontal"],
    initial_item_count: int,
    overscan: float,
    max_render_ahead_viewports: float,
    controller: ListController | None,
    scroll_props: FrozenMap,
) -> Element:
    """Render one List: wrap data lazily, own the window, delegate to engine.

    The adapter is O(1) to construct and reads items/keys only for realized
    cells, so a window update never copies or scans the data.
    """
    owned_controller = (
        state(ListController()).value
        if current_runtime() is not None
        else ListController()
    )
    selected_controller = controller or owned_controller
    source = SequenceDataSource(data, key_for_item)
    initial_stop = min(initial_item_count, source.item_count)
    initial_mask = RenderMask.from_ranges(IndexRange(0, initial_stop))
    spec = FixedVirtualListSpec(
        source=source,
        controller=selected_controller._fixed,
        render_item=lambda item, index, _key: render_item(item, index),
        item_extent=item_extent,
        axis=axis,
        initial_mask=initial_mask,
        retained_mask=RenderMask(),
        window_config=WindowConfig(
            overscan_viewports=overscan,
            max_render_ahead_viewports=max_render_ahead_viewports,
        ),
        scroll_props=scroll_props,
        key_for_item=key_for_item,
    )
    return render_fixed_virtual_list(spec)


@component(key=lambda list_key, *_args: list_key)
def _keyed_list_component(
    list_key: Any,
    data: Sequence[Any],
    render_item: Callable[[Any, int], Element],
    key_for_item: Callable[[Any, int], Any] | None,
    item_extent: float,
    axis: Literal["vertical", "horizontal"],
    initial_item_count: int,
    overscan: float,
    max_render_ahead_viewports: float,
    controller: ListController | None,
    scroll_props: FrozenMap,
) -> Element:
    """Keep hook and controller identity with a keyed list occurrence."""
    return _list_component(
        list_key,
        data,
        render_item,
        key_for_item,
        item_extent,
        axis,
        initial_item_count,
        overscan,
        max_render_ahead_viewports,
        controller,
        scroll_props,
    )


@component
def _virtual_list_component(
    list_key: Any,
    data: Sequence[Any] | VirtualData,
    render_item: Callable[[Any, int], Element],
    layout: VirtualLayout,
    key_for_item: Callable[[Any, int], Any] | None,
    axis: Literal["vertical", "horizontal"],
    initial_item_count: int,
    overscan: float,
    max_render_ahead_viewports: float,
    max_offscreen_items: int,
    controller: ListController | None,
    scroll_props: FrozenMap,
) -> Element:
    """Render one VirtualList: wrap data lazily, own the window, delegate.

    The adapter is O(1) to construct and reads items/keys only for realized
    cells, so a window update never copies or scans the data.
    """
    owned_controller = (
        state(ListController()).value
        if current_runtime() is not None
        else ListController()
    )
    selected_controller = controller or owned_controller
    source = (
        SequenceDataSource(data, key_for_item) if isinstance(data, Sequence) else data
    )
    spec = VirtualListSpec(
        source=source,
        controller=selected_controller._generic,
        render_item=lambda item, index, _key: render_item(item, index),
        layout=layout,
        axis=axis,
        initial_item_count=initial_item_count,
        overscan=overscan,
        max_render_ahead_viewports=max_render_ahead_viewports,
        max_offscreen_items=max_offscreen_items,
        scroll_props=scroll_props,
        key_for_item=key_for_item,
    )
    return render_generic_virtual_list(spec)


@component(key=lambda list_key, *_args: list_key)
def _keyed_virtual_list_component(
    list_key: Any,
    data: Sequence[Any] | VirtualData,
    render_item: Callable[[Any, int], Element],
    layout: VirtualLayout,
    key_for_item: Callable[[Any, int], Any] | None,
    axis: Literal["vertical", "horizontal"],
    initial_item_count: int,
    overscan: float,
    max_render_ahead_viewports: float,
    max_offscreen_items: int,
    controller: ListController | None,
    scroll_props: FrozenMap,
) -> Element:
    """Keep hook and controller identity with a keyed list occurrence."""
    return _virtual_list_component(
        list_key,
        data,
        render_item,
        layout,
        key_for_item,
        axis,
        initial_item_count,
        overscan,
        max_render_ahead_viewports,
        max_offscreen_items,
        controller,
        scroll_props,
    )


def VirtualList(
    data: Sequence[Any] | VirtualData,
    *,
    render_item: Callable[[Any, int], Element],
    layout: VirtualLayout,
    key_for_item: Callable[[Any, int], Any] | None = None,
    axis: Literal["vertical", "horizontal"] = "vertical",
    overscan: float = 1.0,
    max_render_ahead_viewports: float = 3.0,
    max_offscreen_items: int = 64,
    initial_item_count: int = 5,
    controller: ListController | None = None,
    key: Any | None = None,
    interactive_scrollbar: bool = True,
    **scroll_props: Any,
) -> Element:
    """Render a generic virtualized list driven by a custom layout.

    Only the cells the layout places and the framework selects are composed,
    positioned inside a canonical content Box by ``translation_x``/``y``.
    The window follows the viewport, extends ahead of fast flings using the
    native projection (bounded by ``max_render_ahead_viewports``), and keeps
    reorders/resizes stable through item keys.

    Args:
        data: The items to render: a plain ``Sequence`` (adapted lazily) or a
            ``VirtualData`` implementation. Pass state-derived data to update
            the list (see the framework state docs).
        render_item: ``(item, index) -> Element`` cell content.
        layout: A ``VirtualLayout`` strategy mapping a ``LayoutRequest`` to
            positioned ``VirtualPlacement`` cells. It may read measurements
            through ``request.measurement_for_index`` and may expose an
            optional ``index_near_offset`` to receive anchor preservation.
        key_for_item: ``(item, index) -> key`` identity per cell. Required for
            correct state/identity across reorders and resizes, and for rows
            that hold state. Keys are validated lazily: only realized cells
            are read, and a key that maps to two different indices of the
            same data raises ``ValueError`` the second time it is realized,
            even across windows. The key must be a pure function of ``item``
            and ``index``; replace state-derived data with a new sequence
            rather than mutating it in place. Rejected for custom
            ``VirtualData`` sources, which own their keys.
        axis: Scroll axis.
        overscan: Extra window margin in viewports on both sides.
        max_render_ahead_viewports: Caps how far ahead (or behind) of the
            current viewport the projected window may reach, bounding the
            size of one commit. Default 3 bounds fast-fling commits to a few
            viewports; pass 0 explicitly to opt back into an unbounded
            projection.
        max_offscreen_items: Strict allowance of offscreen cells kept beyond
            the visible viewport (nearest first). Default 64.
        initial_item_count: Cells to render before native metrics arrive, used
            only when no numeric main-axis size is declared.
        controller: Optional controller for imperative scrolling.
        key: List identity for sibling reorder.
        interactive_scrollbar: Enable the always-visible host-native draggable
            scrollbar when content exceeds the viewport. Default True.
        scroll_props: Scroll-view props (``height``, ``width``,
            ``background_color``, margins, ...).
    """
    if isinstance(data, str | bytes | bytearray | Mapping) or not isinstance(
        data,
        (Sequence, VirtualData),
    ):
        raise TypeError("data must be a non-string Sequence or VirtualData")
    if not callable(render_item):
        raise TypeError("render_item must be callable")
    if not isinstance(layout, VirtualLayout):
        raise TypeError("layout must implement VirtualLayout")
    if key_for_item is not None:
        if not callable(key_for_item):
            raise TypeError("key_for_item must be callable or None")
        if not isinstance(data, Sequence):
            raise TypeError(
                "custom VirtualData sources own their keys; "
                "key_for_item is not supported"
            )
    if axis not in {"vertical", "horizontal"}:
        raise ValueError("axis must be 'vertical' or 'horizontal'")
    if isinstance(overscan, bool) or not isinstance(overscan, int | float):
        raise TypeError("overscan must be a number")
    overscan_value = float(overscan)
    if not math.isfinite(overscan_value) or overscan_value < 0:
        raise ValueError("overscan must be a finite non-negative number")
    if isinstance(max_render_ahead_viewports, bool) or not isinstance(
        max_render_ahead_viewports,
        int | float,
    ):
        raise TypeError("max_render_ahead_viewports must be a number")
    render_ahead_value = float(max_render_ahead_viewports)
    if not math.isfinite(render_ahead_value) or render_ahead_value < 0:
        raise ValueError(
            "max_render_ahead_viewports must be a finite non-negative number"
        )
    if type(max_offscreen_items) is not int:
        raise TypeError("max_offscreen_items must be an integer")
    if max_offscreen_items < 0:
        raise ValueError("max_offscreen_items must be non-negative")
    if type(initial_item_count) is not int:
        raise TypeError("initial_item_count must be an integer")
    if initial_item_count < 0:
        raise ValueError("initial_item_count must be non-negative")
    if controller is not None and not isinstance(controller, ListController):
        raise TypeError("controller must be ListController or None")
    if type(interactive_scrollbar) is not bool:
        raise TypeError("interactive_scrollbar must be a boolean")
    reserved = {
        "on_scroll_metrics",
        "on_scroll_seek",
        "ref",
        "_virtual_list_initial_offset",
    }.intersection(scroll_props)
    if reserved:
        names = ", ".join(sorted(reserved))
        raise ValueError(f"The virtual-list controller owns {names}")

    scroll_props["interactive_scrollbar"] = interactive_scrollbar
    if key is None:
        component: Callable[..., Element] = _virtual_list_component
    else:
        component = _keyed_virtual_list_component
    return component(
        key,
        data,
        render_item,
        layout,
        key_for_item,
        axis,
        initial_item_count,
        overscan,
        max_render_ahead_viewports,
        max_offscreen_items,
        controller,
        FrozenMap(scroll_props.items()),
    )


def List(
    data: Sequence[Any],
    *,
    render_item: Callable[[Any, int], Element],
    item_extent: float,
    key_for_item: Callable[[Any, int], Any] | None = None,
    axis: Literal["vertical", "horizontal"] = "vertical",
    overscan: float = 1.0,
    max_render_ahead_viewports: float = 3.0,
    initial_item_count: int = 5,
    controller: ListController | None = None,
    key: Any | None = None,
    interactive_scrollbar: bool = True,
    **scroll_props: Any,
) -> Element:
    """Render a fixed-extent virtualized list.

    Only items inside the selected window are composed; the rest are blank
    spacers. The window follows the viewport, extends ahead of fast flings
    using the native projection, and keeps reorders/resizes stable through
    item keys.

    Args:
        data: The items to render. Pass state-derived data to update the
            list (see the framework state docs).
        render_item: ``(item, index) -> Element`` cell content.
        item_extent: Fixed main-axis size of every cell.
        key_for_item: ``(item, index) -> key`` identity per cell. Required for
            correct state/identity across reorders and resizes, and for rows
            that hold state. Keys are validated lazily: only realized cells
            are read, and a key that maps to two different indices of the
            same data raises ``ValueError`` the second time it is realized,
            even across windows. The key must be a pure function of ``item``
            and ``index``; replace state-derived data with a new sequence
            rather than mutating it in place.
        axis: Scroll axis.
        overscan: Extra window margin in viewports on both sides.
        max_render_ahead_viewports: Caps how far ahead (or behind) of the
            current viewport the projected window may reach, bounding the
            size of one commit. Default 3 bounds fast-fling commits to a few
            viewports; the window follows the scroll in bounded steps instead
            of rendering the full fling path in one commit. Pass 0 explicitly
            to opt back into an unbounded projection.
        initial_item_count: Cells to render before native metrics arrive, used
            only when no numeric main-axis size is declared.
        controller: Optional controller for imperative scrolling.
        key: List identity for sibling reorder.
        interactive_scrollbar: Enable the always-visible host-native draggable
            scrollbar when content exceeds the viewport. Default True.
        scroll_props: Scroll-view props (``height``, ``width``,
            ``background_color``, margins, ...).
    """
    if isinstance(data, str | bytes | bytearray | Mapping) or not isinstance(
        data,
        Sequence,
    ):
        raise TypeError("data must be a non-string Sequence")
    if not callable(render_item):
        raise TypeError("render_item must be callable")
    if key_for_item is not None and not callable(key_for_item):
        raise TypeError("key_for_item must be callable or None")
    if isinstance(item_extent, bool) or not isinstance(item_extent, int | float):
        raise TypeError("item_extent must be a number")
    item_extent_value = float(item_extent)
    if not math.isfinite(item_extent_value) or item_extent_value < 1:
        raise ValueError("item_extent must be finite and at least 1 logical unit")
    if axis not in {"vertical", "horizontal"}:
        raise ValueError("axis must be 'vertical' or 'horizontal'")
    if isinstance(overscan, bool) or not isinstance(overscan, int | float):
        raise TypeError("overscan must be a number")
    overscan_value = float(overscan)
    if not math.isfinite(overscan_value) or overscan_value < 0:
        raise ValueError("overscan must be a finite non-negative number")
    if isinstance(max_render_ahead_viewports, bool) or not isinstance(
        max_render_ahead_viewports,
        int | float,
    ):
        raise TypeError("max_render_ahead_viewports must be a number")
    render_ahead_value = float(max_render_ahead_viewports)
    if not math.isfinite(render_ahead_value) or render_ahead_value < 0:
        raise ValueError(
            "max_render_ahead_viewports must be a finite non-negative number"
        )
    if type(initial_item_count) is not int:
        raise TypeError("initial_item_count must be an integer")
    if initial_item_count < 0:
        raise ValueError("initial_item_count must be non-negative")
    if controller is not None and not isinstance(controller, ListController):
        raise TypeError("controller must be ListController or None")
    if type(interactive_scrollbar) is not bool:
        raise TypeError("interactive_scrollbar must be a boolean")
    reserved = {
        "on_scroll_metrics",
        "on_scroll_seek",
        "ref",
        "_virtual_list_initial_offset",
    }.intersection(scroll_props)
    if reserved:
        names = ", ".join(sorted(reserved))
        raise ValueError(f"The virtual-list controller owns {names}")

    scroll_props["interactive_scrollbar"] = interactive_scrollbar
    if key is None:
        component: Callable[..., Element] = _list_component
    else:
        component = _keyed_list_component
    return component(
        key,
        data,
        render_item,
        key_for_item,
        item_extent,
        axis,
        initial_item_count,
        overscan,
        max_render_ahead_viewports,
        controller,
        FrozenMap(scroll_props.items()),
    )


__all__ = [
    "CellMeasurement",
    "FixedLinearLayout",
    "LayoutRequest",
    "LayoutResult",
    "List",
    "ListController",
    "StickyConstraint",
    "ViewportRect",
    "VirtualData",
    "VirtualLayout",
    "VirtualList",
    "VirtualPlacement",
    "select_placements",
]
