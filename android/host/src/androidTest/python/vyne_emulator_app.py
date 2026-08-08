"""Dedicated end-to-end application for tester-supplied emulator runs."""

from __future__ import annotations

import asyncio
import base64
import urllib.request

from vyne import (
    AppContext,
    Box,
    Column,
    Image,
    LaunchData,
    Row,
    Text,
    TextInput,
    animate,
    callback,
    run_app,
    state,
)
from vyne import List, ListController


_external = None
_latest_external = None
_list_controller = ListController()
_horizontal_controller = ListController()
_dynamic_controller = ListController()


def emit_external(value):
    if _external is None:
        raise RuntimeError("external callback is not initialized")
    _external.invoke(value)


def emit_latest_many(count):
    if _latest_external is None:
        raise RuntimeError("latest callback is not initialized")
    for value in range(int(count)):
        _latest_external.invoke(value)


def App(context: AppContext):
    global _external, _latest_external

    phase = state("idle")
    count = state(0)
    error_value = state(0)
    external_value = state("none")
    latest_value = state("-1")
    input_value = state("")
    order_reversed = state(False)
    pair_a = state(0)
    pair_b = state(0)
    animation_status = state("idle")
    dynamic_data = state(tuple(range(100)))
    dynamic_reversed = state(False)
    dynamic_short = state(False)
    image_source = state("")
    image_status = state("idle")
    back_guard = state(False)
    back_consumed = state(0)

    async def load_image():
        image_status.set("loading")
        try:
            def _fetch():
                with urllib.request.urlopen(
                    "http://127.0.0.1:9876/img.png",
                    timeout=10,
                ) as response:
                    return response.read()

            data = await asyncio.to_thread(_fetch)
            image_source.set(
                "data:image/png;base64," + base64.b64encode(data).decode()
            )
            image_status.set("loaded")
        except Exception as exc:  # noqa: BLE001 - surfaced via status
            image_status.set(f"error: {exc}")

    def reverse_dynamic():
        dynamic_reversed.set(not dynamic_reversed.value)
        dynamic_data.set(tuple(reversed(dynamic_data.value)))

    def resize_dynamic():
        next_short = not dynamic_short.value
        dynamic_short.set(next_short)
        values = tuple(range(20 if next_short else 100))
        dynamic_data.set(
            tuple(reversed(values)) if dynamic_reversed.value else values
        )

    async def slow():
        phase.set("waiting")
        await asyncio.sleep(0.35)
        phase.set("done")

    async def increment_after_await():
        await asyncio.sleep(0.02)
        count.set(count.value + 1)

    async def fail_after_await():
        error_value.set(1)
        await asyncio.sleep(0.08)
        error_value.set(2)
        raise ValueError("intentional emulator callback failure")

    async def update_pair():
        await asyncio.sleep(0.02)
        pair_a.set(pair_a.value + 1)
        pair_b.set(pair_b.value + 1)

    async def receive_external(value):
        await asyncio.sleep(0.04)
        external_value.set(str(value))

    async def receive_latest(value):
        await asyncio.sleep(0.04)
        latest_value.set(str(value))

    def start_animation(event):
        animation_status.set("running")
        animate(
            event.target,
            "opacity",
            to=0.25,
            duration=180,
            easing="linear",
            on_complete=lambda _event: animation_status.set("completed"),
        )

    def toggle_back_guard(event):
        back_guard.set(not back_guard.value)

    def _handle_back():
        if back_guard.value:
            back_consumed.set(back_consumed.value + 1)
            return True
        return False

    if _external is None:
        _external = callback(receive_external)
    if _latest_external is None:
        _latest_external = callback(receive_latest, delivery="latest")

    context.back_handler.addEventListener(_handle_back)

    ordered = ["b", "a"] if order_reversed.value else ["a", "b"]
    order_children = [
        Text(
            text=item.upper(),
            key=item,
            content_description=f"order-item-{item}",
        )
        for item in ordered
    ]

    return Column(
        Text(
            text=phase.value,
            content_description="phase-status",
        ),
        Text(
            text=str(count.value),
            content_description="count-status",
        ),
        Text(
            text=str(error_value.value),
            content_description="error-status",
        ),
        Text(
            text=external_value.value,
            content_description="external-status",
        ),
        Text(
            text=latest_value.value,
            content_description="latest-status",
        ),
        Text(
            text=f"{pair_a.value}:{pair_b.value}",
            content_description="pair-status",
        ),
        Text(
            text=f"{context.launch.sequence}:{context.launch.action or ''}",
            content_description="launch-status",
        ),
        Text(
            text=input_value.value,
            content_description="input-status",
        ),
        Text(
            text=animation_status.value,
            content_description="animation-status",
        ),
        Text(
            text=f"back consumed: {back_consumed.value}",
            content_description="back-status",
        ),
        Text(
            text="disable back guard" if back_guard.value else "enable back guard",
            content_description="back-guard-toggle",
            on_click=toggle_back_guard,
        ),
        Text(
            text="Jump list",
            content_description="virtual-list-jump",
            on_click=lambda: _list_controller.scroll_to_index(
                50,
                alignment="start",
                animated=False,
            ),
        ),
        List(
            tuple(range(100)),
            render_item=lambda item, index: Text(
                text=f"List {item}",
                content_description=f"virtual-list-item-{item}",
            ),
            key_for_item=lambda item, index: item,
            item_extent=30,
            axis="vertical",
            controller=_list_controller,
            width=240,
            height=90,
            content_description="public-virtual-list",
        ),
        List(
            tuple(range(200)),
            render_item=lambda item, index: Text(
                text=f"Card {item}",
                content_description=f"horizontal-item-{item}",
            ),
            key_for_item=lambda item, index: item,
            item_extent=126,
            axis="horizontal",
            controller=_horizontal_controller,
            width="match_parent",
            height=82,
            content_description="public-horizontal-list",
        ),
        Row(
            Text(
                text="Reverse",
                content_description="dynamic-reverse",
                on_click=reverse_dynamic,
            ),
            Text(
                text="20 / 100",
                content_description="dynamic-resize",
                on_click=resize_dynamic,
            ),
            margin_top=6,
            margin_bottom=2,
        ),
        List(
            dynamic_data.value,
            render_item=lambda item, index: Text(
                text=f"Key {item}",
                content_description=f"dynamic-item-{item}",
            ),
            key_for_item=lambda item, index: item,
            item_extent=30,
            axis="vertical",
            controller=_dynamic_controller,
            width=240,
            height=90,
            content_description="public-dynamic-list",
        ),
        Row(
            Text(
                text="Load image",
                content_description="load-image",
                on_click=load_image,
            ),
            Text(
                text=image_status.value,
                content_description="image-status",
            ),
            margin_top=6,
        ),
        Image(
            source=image_source.value,
            width=120,
            height=120,
            background_color="#EEEEEE",
            content_description="network-image",
        ),
        TextInput(
            text=input_value.value,
            hint="type here",
            content_description="input-control",
            on_text_change=lambda event: input_value.set(event.get("text", "")),
        ),
        Row(
            Text(
                text="Slow",
                content_description="slow-button",
                on_click=slow,
            ),
            Text(
                text="Increment",
                content_description="increment-button",
                on_click=lambda: count.set(count.value + 1),
            ),
            Text(
                text="Await increment",
                content_description="await-increment-button",
                on_click=increment_after_await,
            ),
        ),
        Row(
            Text(
                text="Animate",
                content_description="animation-target",
                on_click=start_animation,
            ),
            Text(
                text="Fail",
                content_description="fail-button",
                on_click=fail_after_await,
            ),
            Text(
                text="Pair",
                content_description="pair-button",
                on_click=update_pair,
            ),
            Text(
                text="Reverse",
                content_description="reverse-button",
                on_click=lambda: order_reversed.set(not order_reversed.value),
            ),
        ),
        Column(
            *order_children,
            content_description="order-container",
        ),
        Box(
            width=100,
            height=40,
            margin_start=7,
            padding=5,
            background_color="#336699",
            opacity=0.75,
            translation_x=3,
            content_description="layout-box",
        ),
        content_description="acceptance-root",
        padding=8,
    )


run_app(App)
