"""Immutable application launch data delivered by the Android host."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from vyne.values import FrozenMap


def _freeze_launch_value(value: Any, *, path: str) -> Any:
    """Freeze the deliberately small value domain accepted from an Intent."""
    if value is None or type(value) in (bool, int, float, str, bytes):
        return value
    if isinstance(value, Mapping):
        items: list[tuple[str, Any]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"{path} keys must be strings, got {type(key).__name__}"
                )
            items.append(
                (key, _freeze_launch_value(item, path=f"{path}.{key}"))
            )
        return FrozenMap(items)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_launch_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    raise TypeError(
        f"{path} contains unsupported value {type(value).__name__}"
    )


@dataclass(frozen=True, slots=True)
class LaunchData:
    """The Android launch which selected the current root application view.

    ``sequence`` is monotonic within one hosted runtime.  ``extras`` is deeply
    immutable so a later Android or user-side mutation cannot change the input
    observed by an already completed render.

    ``origin`` is derived from the session sequence (1 = ``"cold"``, later
    = ``"warm"``).
    """

    action: str | None = None
    uri: str | None = None
    extras: FrozenMap = field(default_factory=FrozenMap)
    sequence: int = 0
    origin: str = "cold"

    def __post_init__(self) -> None:
        if self.action is not None and not isinstance(self.action, str):
            raise TypeError("LaunchData.action must be a string or None")
        if self.uri is not None and not isinstance(self.uri, str):
            raise TypeError("LaunchData.uri must be a string or None")
        if type(self.sequence) is not int or self.sequence < 0:
            raise TypeError("LaunchData.sequence must be a non-negative integer")
        if self.origin not in ("cold", "warm"):
            raise TypeError(
                f"LaunchData.origin must be 'cold' or 'warm', got {self.origin!r}"
            )

        frozen_extras = _freeze_launch_value(self.extras, path="LaunchData.extras")
        if not isinstance(frozen_extras, FrozenMap):
            raise TypeError("LaunchData.extras must be a string-key mapping")
        object.__setattr__(self, "extras", frozen_extras)

    @classmethod
    def from_native(
        cls,
        action: Any,
        uri: Any,
        extras: Any,
        sequence: Any,
    ) -> "LaunchData":
        """Construct a launch after the JNI adapter has decoded Java values.

        ``origin`` is derived from the session sequence: sequence 1 is the
        entry that started the session (``"cold"``), every later entry is
        ``"warm"``. The Android host resets the sequence per session.
        """
        if extras is None:
            extras = {}
        return cls(
            action=None if action is None else str(action),
            uri=None if uri is None else str(uri),
            extras=extras,
            sequence=int(sequence),
            origin="cold" if int(sequence) <= 1 else "warm",
        )
