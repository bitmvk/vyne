"""TimerRing example extension — Python side.

The Python side declares NO kinds, props, or events: the Kotlin ElementSpec
(in android/TimerRingExtension.kt) is the single source of truth, and the
host registry is queried at startup. This module provides the widget
constructor and an exported ``on_launch`` capture function — the APP
composes it into its own pre_launch hook (ordering is app-owned).
"""

from __future__ import annotations

import logging

from vyne.elements import Element
from vyne.launch import LaunchData

_logger = logging.getLogger("vyne.ext.timer_ring")


def TimerRing(
    progress: float = 0.0,
    ring_color: str = "#6750E8",
    track_color: str = "#E7DEFF",
    **base_props,
) -> Element:
    """A circular progress ring (native view from this extension)."""
    return Element("TimerRing", props={
        "progress": progress,
        "ring_color": ring_color,
        "track_color": track_color,
        **base_props,
    })


def on_launch(context) -> None:
    """Capture function: call from the app's pre_launch hook if desired."""
    _logger.info(
        "timer_ring on_launch: origin=%s action=%r uri=%r sequence=%s",
        context.launch.origin,
        context.launch.action,
        context.launch.uri,
        context.launch.sequence,
    )
