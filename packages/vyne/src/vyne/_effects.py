"""Private commands for accepted native effects.

Effects travel through the Runtime commit coordinator but do not become part
of the declarative render snapshot.  This module is internal until imperative
APIs and their public names are designed.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from vyne.protocol import JsonObject, OP_SCROLL_TO
from vyne.refs import ViewHandle


def _finite_non_negative(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


@dataclass(frozen=True)
class ScrollToEffect:
    """Set one native Scroll offset after its transaction is accepted."""

    target: ViewHandle
    offset_x: float
    offset_y: float
    animated: bool

    def __post_init__(self) -> None:
        if not isinstance(self.target, ViewHandle):
            raise TypeError("target must be a ViewHandle")
        if self.target.kind not in {"Scroll", "HorizontalScroll"}:
            raise ValueError("scroll_to target must be a scroll container")
        object.__setattr__(
            self,
            "offset_x",
            _finite_non_negative(self.offset_x, name="offset_x"),
        )
        object.__setattr__(
            self,
            "offset_y",
            _finite_non_negative(self.offset_y, name="offset_y"),
        )
        if type(self.animated) is not bool:
            raise TypeError("animated must be a boolean")

    @property
    def expected_kind(self) -> str:
        return self.target.kind

    def to_wire_op(self) -> JsonObject:
        return {
            "op": OP_SCROLL_TO,
            "id": self.target.node_id,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "animated": self.animated,
        }
