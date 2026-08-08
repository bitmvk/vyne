"""Public list components built on the private virtualization engine.

The engine owns window selection, prediction, and rendering; this module is
the stable public surface. ``List`` renders a fixed-extent virtualized list
(windowed cells + spacers), and ``ListController`` provides imperative
scrolling for one mounted list.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from vyne._lists.fixed import (
    FixedVirtualListController,
    FixedVirtualListSpec,
    render_fixed_virtual_list,
)
from vyne._lists.model import IndexRange, RenderMask, WindowConfig
from vyne._lists.source import TupleDataSource
from vyne.component import component
from vyne.elements import Element
from vyne.state import current_runtime, state
from vyne.values import FrozenMap


class ListController:
    """Imperative control for one mounted :class:`List`.

    A controller attaches to the list it is passed to. It binds on mount and
    reports an error when the list is not mounted. One controller may drive
    one mounted list at a time; use ``List(key=...)`` when sibling lists can
    reorder so the controller follows the logical list.
    """

    def __init__(self) -> None:
        self._engine = FixedVirtualListController()

    def scroll_to_offset(self, offset: float, *, animated: bool) -> None:
        """Scroll to an explicit main-axis offset."""
        self._engine.scroll_to_offset(offset, animated=animated)

    def scroll_to_index(
        self,
        index: int,
        *,
        alignment: Literal["start", "center", "end", "nearest"],
        animated: bool,
    ) -> None:
        """Scroll one item into an explicitly aligned viewport position."""
        self._engine.scroll_to_index(index, alignment=alignment, animated=animated)


def _index_key(item: Any, index: int) -> Any:
    return index


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
    """Render one List: snapshot data, own the window, delegate to the engine.

    The snapshot runs only when this component re-executes (data identity or
    other inputs changed), so a window update never re-copies the data.
    """
    items = tuple(data)
    if key_for_item is None:
        keys = tuple(range(len(items)))
    else:
        keys = tuple(
            key_for_item(item, index) for index, item in enumerate(items)
        )
    owned_controller = (
        state(ListController()).value
        if current_runtime() is not None
        else ListController()
    )
    selected_controller = controller or owned_controller
    source = TupleDataSource(items=items, keys=keys)
    initial_stop = min(initial_item_count, source.item_count)
    initial_mask = RenderMask.from_ranges(IndexRange(0, initial_stop))
    spec = FixedVirtualListSpec(
        source=source,
        controller=selected_controller._engine,
        render_item=lambda item, index, _key: render_item(item, index),
        item_extent=item_extent,
        axis=axis,
        initial_mask=initial_mask,
        retained_mask=RenderMask(),
        window_config=WindowConfig(
            overscan_before_viewports=overscan,
            overscan_after_viewports=overscan,
            prediction_horizon_seconds=0,
            max_prediction_viewports=0,
            reversal_retention_viewports=0,
            max_render_ahead_viewports=max_render_ahead_viewports,
        ),
        scroll_props=scroll_props,
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


def List(
    data: Sequence[Any],
    *,
    render_item: Callable[[Any, int], Element],
    item_extent: float,
    key_for_item: Callable[[Any, int], Any] | None = None,
    axis: Literal["vertical", "horizontal"] = "vertical",
    overscan: float = 1.0,
    max_render_ahead_viewports: float = 0.0,
    initial_item_count: int = 5,
    controller: ListController | None = None,
    key: Any | None = None,
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
            correct state/identity across reorders and resizes; defaults to
            the item index when omitted.
        axis: Scroll axis.
        overscan: Extra window margin in viewports on both sides.
        max_render_ahead_viewports: Caps how far ahead of the viewport the
            projected window may reach, bounding the size of one commit.
            Default 0 leaves the projection unbounded: the full fling path is
            rendered in one commit, which is the smoothest behavior. A finite
            cap makes the window follow in bounded steps instead; useful for
            very long lists where a single commit would be too large, at the
            cost of re-rendering during fast flings.
        initial_item_count: Cells to render before native metrics arrive, used
            only when no numeric main-axis size is declared.
        controller: Optional controller for imperative scrolling.
        key: List identity for sibling reorder.
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
    if axis not in {"vertical", "horizontal"}:
        raise ValueError("axis must be 'vertical' or 'horizontal'")
    if isinstance(overscan, bool) or not isinstance(overscan, int | float):
        raise TypeError("overscan must be a number")
    if isinstance(max_render_ahead_viewports, bool) or not isinstance(
        max_render_ahead_viewports,
        int | float,
    ):
        raise TypeError("max_render_ahead_viewports must be a number")
    if type(initial_item_count) is not int:
        raise TypeError("initial_item_count must be an integer")
    if initial_item_count < 0:
        raise ValueError("initial_item_count must be non-negative")
    if controller is not None and not isinstance(controller, ListController):
        raise TypeError("controller must be ListController or None")

    if key is None:
        component = _list_component
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


__all__ = ["List", "ListController"]
