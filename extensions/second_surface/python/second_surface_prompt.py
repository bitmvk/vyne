"""second_surface example — Python side of the lock-screen prompt surface.

A second attach point for the same portable Renderer machinery: this module
is mounted into its own Runtime and rendered into a showWhenLocked
Activity (fullscreen over the keyguard, screen wakes, phone stays locked,
main app stays closed).
"""

from __future__ import annotations

import logging

from vyne import Box, Column, Row, Text, run_app, state
from vyne.elements import Element
from vyne_material import Button

_logger = logging.getLogger("vyne.ext.second_surface_prompt")


def PromptHost(
    dismiss_requested: bool = False,
    children: tuple = (),
    **base_props,
) -> Element:
    """Container whose dismissal finishes the hosting prompt Activity."""
    return Element(
        "PromptHost",
        props={"dismiss_requested": dismiss_requested, **base_props},
        children=children,
    )


def App(context):
    """The lock-screen prompt: approve or deny without unlocking."""
    data = dict(context.launch.extras)
    sender = str(data.get("sender", "visitor"))
    body = str(data.get("body", "is at the gate"))

    decided = state(False)
    # State persists across warm deliveries by design; the decision only
    # applies to the delivery that made it, so a fresh prompt reopens.
    decided_on_sequence = state(0)

    def decide() -> None:
        decided.set(True)
        decided_on_sequence.set(int(context.launch.sequence))

    fresh_decision = int(context.launch.sequence) == decided_on_sequence.value
    if fresh_decision and decided.value:
        return PromptHost(dismiss_requested=True)

    return PromptHost(
        children=[
            Box(
                Column(
                    [
                        Text(
                            text="Someone is at the gate",
                            font_size=14,
                            text_color="#6750E8",
                            include_font_padding=False,
                        ),
                        Text(
                            text=sender,
                            font_size=28,
                            text_color="#111111",
                            include_font_padding=False,
                            margin_top=6,
                        ),
                        Text(
                            text=body,
                            font_size=16,
                            text_color="#333333",
                            include_font_padding=False,
                            margin_top=10,
                        ),
                        Row(
                            [
                                Button(
                                    "Approve",
                                    on_click=decide,
                                    margin_top=24,
                                ),
                                Button(
                                    "Deny",
                                    on_click=decide,
                                    variant="outlined",
                                    margin_top=24,
                                    margin_start=12,
                                ),
                            ],
                        ),
                    ],
                    padding=24,
                ),
                background_color="#FFFFFF",
                corner_radius=16,
                margin_top=24, margin_bottom=24, margin_start=24, margin_end=24,
            ),
        ],
    )


run_app(App)
