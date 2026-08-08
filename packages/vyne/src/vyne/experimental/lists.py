"""Deprecated alias for the public list surface.

``VirtualList`` and ``VirtualListController`` were the temporary experimental
names. The final API is :class:`vyne.List` and :class:`vyne.ListController`;
this module keeps the old imports working without changes.
"""

from __future__ import annotations

from vyne.lists import List, ListController

VirtualList = List
VirtualListController = ListController

__all__ = ["VirtualList", "VirtualListController"]
