"""Immutable geometry helpers for Material components.

This module owns:
* One-time path-command dictionary construction for progress/wavy indicators
  (immutable, hashable, reusable across renders).
* Native-text-measurement intent so that Badge, Menu, TextField label,
  and Tooltip use wrap-content + padding/min/max constraints instead of
  ``len(text) * constant`` estimates.
"""

from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Immutable path command dictionaries (built once, reused everywhere)
# ---------------------------------------------------------------------------

# Progress indicator: 24×24 circle path used by CircularProgressIndicator.
# Built as a string once; callers create Canvas draw dicts around it.
_PROGRESS_PATH_D: str = (
    "M12 2 "
    "C17.523 2 22 6.477 22 12 "
    "C22 17.523 17.523 22 12 22 "
    "C6.477 22 2 17.523 2 12 "
    "C2 6.477 6.477 2 12 2"
)


def progress_path() -> str:
    """Return the canonical progress circle path string (24×24)."""
    return _PROGRESS_PATH_D


def wavy_path(width: float, height: float, cycles: int = 8) -> str:
    """Build a wavy-line SVG path string for the given dimensions.

    This is deliberately a function (not a constant) because *width* and
    *height* vary per use.  The returned string is intended to be stored
    by the caller and reused across renders for the same dimensions.
    """
    center = height / 2
    amplitude = max(1.0, height * 0.24)
    points: list[tuple[float, float]] = []
    steps = max(24, cycles * 8)
    for index in range(steps + 1):
        x = width * index / steps
        y = center + amplitude * math.sin(index / steps * cycles * math.tau)
        points.append((x, y))
    commands = [f"M{points[0][0]:.3f} {points[0][1]:.3f}"]
    commands.extend(f"L{x:.3f} {y:.3f}" for x, y in points[1:])
    return " ".join(commands)
