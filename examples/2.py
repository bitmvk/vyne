"""Demo user app for the Vyne framework."""

from __future__ import annotations

from vyne import (
    Box,
    Column,
    Image,
    Layout,
    Row,
    Scroll,
    Text,
    TextInput,
    run_app,
    state,
)


def App():
    name = state("test")
    clicks = state(0)
    accepted = state(False)
    enabled = state(True)

    def update_name(event):
        name.set(event.get("text", ""))

    def increment():
        clicks.set(clicks.value + 1)

    return Box(
        Layout(
            Text(text="Vyne Demo"),
            Text(text="Python owns state and emits JSON patches into native Android Views."),
            Row(
                Text(text="Name"),
                TextInput(
                    text=name.value,
                    hint="Type your name",
                    on_text_change=update_name,
                    on_editor_action=update_name,
                ),
            ),
            Row(
                Box(
                    Text(text="Increment", text_color="#ffffff"),
                    background_color="#2563eb",
                    corner_radius=8,
                    padding=12,
                    on_click=lambda event: increment(),
                ),
                Text(text=f"Clicked {clicks.value} times", margin_start=12),
            ),
            Text(text=f"Hello, {name.value or 'stranger'}"),
            Row(
                Box(
                    Text(text="x" if accepted.value else ""),
                    width=24,
                    height=24,
                    border_width=1,
                    border_color="#64748b",
                    background_color="#dcfce7" if accepted.value else "#ffffff",
                    on_click=lambda event: accepted.set(not accepted.value),
                ),
                Text(text="Accept terms", margin_start=8),
            ),
            Row(
                Text(text="Enabled"),
                Box(
                    Text(text="ON" if enabled.value else "OFF", text_color="#ffffff"),
                    background_color="#16a34a" if enabled.value else "#64748b",
                    corner_radius=12,
                    padding=8,
                    margin_start=8,
                    on_click=lambda event: enabled.set(not enabled.value),
                ),
            ),
            Image(source="demo_image"),
            Text(text=f"Accepted: {accepted.value}, enabled: {enabled.value}"),
            orientation="vertical",
        ),
    )


run_app(App)
