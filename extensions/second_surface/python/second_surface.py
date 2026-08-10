"""second_surface example — Python side of the SMS overlay surface.

The overlay is a normal registered app module: it is mounted by
``start_surface`` into its OWN Runtime (separate commit stream, separate
single-owner loop), driven entirely by data deliveries. The window itself
(WindowManager, permission flow) is extension-owned Kotlin; Python drives
teardown through the ``dismiss_requested`` prop on the custom OverlayHost
kind.

The overlay works when the main app is closed: the SMS receiver cold-starts
the process, and this module mounts with no Activity ever existing.
"""

from __future__ import annotations

import logging

from vyne import Box, Column, Row, Text, run_app, state
from vyne.elements import Element
from vyne_material import Button

_logger = logging.getLogger("vyne.ext.second_surface")


def OverlayHost(
    dismiss_requested: bool = False,
    children: tuple = (),
    **base_props,
) -> Element:
    """Full-screen container whose dismissal is handled by the extension."""
    return Element(
        "OverlayHost",
        props={"dismiss_requested": dismiss_requested, **base_props},
        children=children,
    )


def App(context):
    """The SMS overlay root: shows the sender/body with Approve/Dismiss."""
    data = dict(context.launch.extras)
    show = bool(data.get("show", True))
    sender = str(data.get("sender", "unknown"))
    body = str(data.get("body", ""))

    dismissed = state(False)
    approved = state(False)
    # The delivery sequence the decision belongs to. State persists across
    # warm deliveries by design, so the terminal flag is only effective for
    # the delivery that produced it — the next SMS resets the overlay.
    decided_on_sequence = state(0)

    def decide(kind: bool) -> None:
        dismissed.set(kind)
        approved.set(not kind)
        decided_on_sequence.set(int(context.launch.sequence))

    fresh_decision = int(context.launch.sequence) == decided_on_sequence.value
    decided = fresh_decision and (dismissed.value or approved.value)

    # Any terminal state tears the attach point down via the prop; the next
    # SMS delivery resets the tree with show=True.
    if not show or decided:
        return OverlayHost(dismiss_requested=True)

    return OverlayHost(
        children=[
            Box(
                Column(
                    [
                        Text(
                            text="SMS received",
                            font_size=12,
                            text_color="#6750E8",
                            include_font_padding=False,
                        ),
                        Text(
                            text=sender,
                            font_size=24,
                            text_color="#111111",
                            include_font_padding=False,
                            margin_top=4,
                        ),
                        Text(
                            text=body,
                            font_size=16,
                            text_color="#333333",
                            include_font_padding=False,
                            margin_top=12,
                        ),
                        Row(
                            [
                                Button(
                                    "Approve",
                                    on_click=lambda: decide(False),
                                    margin_top=20,
                                ),
                                Button(
                                    "Dismiss",
                                    on_click=lambda: decide(True),
                                    variant="outlined",
                                    margin_top=20,
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
