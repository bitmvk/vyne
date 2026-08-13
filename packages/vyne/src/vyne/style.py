"""Typed styling helpers for Vyne elements.

These dataclasses provide a structured, auto-completable styling API that
compiles down to plain JSON dicts via ``to_props()``.  The Android renderer
never sees these Python types — it receives only the JSON representation.

This mirrors the Compose/SwiftUI approach of composition over inheritance:
each primitive (Fill, Stroke, Shadow, ...) is a frozen dataclass with named
factory constructors instead of subclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


class PropsMixin:
    def to_props(self) -> dict[str, Any]:
        return _to_props(self)


@dataclass(frozen=True)
class Fill(PropsMixin):
    kind: str = "solid"
    color: str | None = None

    @staticmethod
    def solid(color: str) -> "Fill":
        return Fill(kind="solid", color=color)


@dataclass(frozen=True)
class Stroke(PropsMixin):
    color: str
    width: int | float = 1


@dataclass(frozen=True)
class CornerRadius(PropsMixin):
    radius: int | float | None = None
    top_left: int | float | None = None
    top_right: int | float | None = None
    bottom_right: int | float | None = None
    bottom_left: int | float | None = None

    @staticmethod
    def all(radius: int | float) -> "CornerRadius":
        return CornerRadius(radius=radius)

    @staticmethod
    def only(
        *,
        top_left: int | float | None = None,
        top_right: int | float | None = None,
        bottom_right: int | float | None = None,
        bottom_left: int | float | None = None,
    ) -> "CornerRadius":
        return CornerRadius(
            top_left=top_left,
            top_right=top_right,
            bottom_right=bottom_right,
            bottom_left=bottom_left,
        )


@dataclass(frozen=True)
class Shape(PropsMixin):
    kind: str
    fill: Fill | str | None = None
    stroke: Stroke | None = None
    corners: CornerRadius | int | float | None = None

    @staticmethod
    def rectangle(
        *,
        fill: Fill | str | None = None,
        stroke: Stroke | None = None,
        corners: CornerRadius | int | float | None = None,
    ) -> "Shape":
        return Shape(kind="rectangle", fill=fill, stroke=stroke, corners=corners)


@dataclass(frozen=True)
class Shadow(PropsMixin):
    elevation: int | float = 0


@dataclass(frozen=True)
class Ripple(PropsMixin):
    color: str


@dataclass(frozen=True)
class Decoration(PropsMixin):
    shape: Shape | None = None
    shadow: Shadow | None = None
    ripple: Ripple | None = None

    @staticmethod
    def rectangle(
        *,
        fill: Fill | str | None = None,
        stroke: Stroke | None = None,
        corners: CornerRadius | int | float | None = None,
        shadow: Shadow | None = None,
        ripple: Ripple | None = None,
    ) -> "Decoration":
        return Decoration(
            shape=Shape.rectangle(fill=fill, stroke=stroke, corners=corners),
            shadow=shadow,
            ripple=ripple,
        )


def _to_props(value: Any) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for field in fields(value):
        field_value = getattr(value, field.name)
        if field_value is not None:
            props[field.name] = _to_json_value(field_value)
    return props


def _to_json_value(value: Any) -> Any:
    if hasattr(value, "to_props"):
        return value.to_props()
    if isinstance(value, list | tuple):
        return [_to_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_json_value(item) for key, item in value.items()}
    return value
