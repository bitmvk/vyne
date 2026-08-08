"""Private virtualized-list planning primitives.

The public list API is intentionally not defined here.  These types model the
host-independent part of list virtualization: viewport metrics, item layout,
render masks, and pure window plans.
"""

from vyne._lists.fixed import (
    FixedVirtualListController,
    FixedVirtualListSpec,
    compose_fixed_window,
    render_fixed_virtual_list,
)
from vyne._lists.model import (
    FixedExtentLayout,
    IndexRange,
    ItemRangeSegment,
    RenderMask,
    SpacerSegment,
    ViewportMetrics,
    WindowConfig,
    WindowPlan,
    WindowSelection,
)
from vyne._lists.source import TupleDataSource, VirtualizedDataSource
from vyne._lists.window import plan_mask, plan_window, select_window

__all__ = [
    "FixedExtentLayout",
    "FixedVirtualListController",
    "FixedVirtualListSpec",
    "IndexRange",
    "ItemRangeSegment",
    "RenderMask",
    "SpacerSegment",
    "ViewportMetrics",
    "WindowConfig",
    "WindowPlan",
    "WindowSelection",
    "TupleDataSource",
    "VirtualizedDataSource",
    "compose_fixed_window",
    "plan_mask",
    "plan_window",
    "select_window",
    "render_fixed_virtual_list",
]
