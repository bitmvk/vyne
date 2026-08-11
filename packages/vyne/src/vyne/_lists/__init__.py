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
from vyne._lists.generic import (
    GenericVirtualListController,
    VirtualListSpec,
    compose_generic_window,
    render_generic_virtual_list,
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
from vyne._lists.source import (
    KeyRegistry,
    SequenceDataSource,
    VirtualizedDataSource,
)
from vyne._lists.window import plan_mask, select_window

__all__ = [
    "FixedExtentLayout",
    "FixedVirtualListController",
    "FixedVirtualListSpec",
    "GenericVirtualListController",
    "IndexRange",
    "ItemRangeSegment",
    "KeyRegistry",
    "RenderMask",
    "SequenceDataSource",
    "SpacerSegment",
    "ViewportMetrics",
    "VirtualListSpec",
    "VirtualizedDataSource",
    "WindowConfig",
    "WindowPlan",
    "WindowSelection",
    "compose_fixed_window",
    "compose_generic_window",
    "plan_mask",
    "render_fixed_virtual_list",
    "render_generic_virtual_list",
    "select_window",
]
