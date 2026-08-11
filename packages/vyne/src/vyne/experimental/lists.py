"""Deprecated alias for the public list surface.

``VirtualList`` and ``ListController`` were introduced through this module
while the list API stabilized. The final API is :class:`vyne.List`,
:class:`vyne.VirtualList`, and the single :class:`vyne.ListController`; this
module keeps old imports of those names working. The temporary
``VirtualListController`` name is gone: there is one controller type.
"""

from __future__ import annotations

from vyne.lists import ListController, VirtualList

__all__ = ["VirtualList", "ListController"]
