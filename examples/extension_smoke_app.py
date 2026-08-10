"""Extension smoke app — renders the TimerRing extension end to end.

Used by the emulator smoke test with ``-Pvyne.appSource`` pointing here.
Exercises, on a real device:
1. extension discovery + registrant/bootstrap generation (vyne build)
2. Kotlin ElementSpec registration + the host registry query (sync_from_host)
3. lowering of an extension kind with generic + widget props
4. the native TimerRing view rendering
5. async event handler → state change → native prop update →
   extension `complete` event → Python label update
6. pre_launch capture (origin is displayed)
"""

from __future__ import annotations

import asyncio
import logging

from vyne import (
    Column,
    Row,
    Text,
    component,
    run_app,
    state,
)
from vyne import AppContext
from vyne_material import Button
from timer_ring import TimerRing

logging.basicConfig(level=logging.INFO)

_launch_info: dict = {}


def _pre_launch(context: AppContext) -> None:
    """Capture hook (app-side): remember the entry for display."""
    _launch_info["origin"] = context.launch.origin
    _launch_info["sequence"] = context.launch.sequence


@component
def SmokeApp(context: AppContext):
    ring_progress = state(0.75)
    status = state("idle")
    driving = state(False)

    async def drive(event=None) -> None:
        if driving.value:
            return
        driving.set(True)
        status.set("driving...")
        await asyncio.sleep(1.0)
        # Progress 1.0 makes the native view fire its `complete` event,
        # which round-trips to on_complete below.
        ring_progress.set(1.0)

    def on_complete(event) -> None:
        status.set("complete!")

    launch_text = (
        f"launch: origin={_launch_info.get('origin', '?')} "
        f"seq={_launch_info.get('sequence', '?')}"
    )
    return Column(
        [
            Text(text=launch_text, text_color="#666666", font_size=12),
            Row(
                [
                    TimerRing(
                        progress=ring_progress.value,
                        width=200,
                        height=200,
                        on_complete=on_complete,
                    ),
                    Column(
                        [
                            Text(
                                text=status.value,
                                text_color="#000000",
                                font_size=16,
                            ),
                            Button(label="start", on_click=drive),
                        ],
                        padding=16,
                    ),
                ],
                align_items="center",
            ),
        ],
        padding=24,
        background_color="#FFFFFF",
        safe_area=True,
    )


run_app(SmokeApp, pre_launch=_pre_launch)
