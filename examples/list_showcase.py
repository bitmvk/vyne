"""Interactive showcase for the experimental virtual-list surface."""

from __future__ import annotations

from vyne import AppContext, Column, List, ListController, Row, Text, run_app, state


_vertical_controller = ListController()
_horizontal_controller = ListController()
_dynamic_controller = ListController()


def _button(label: str, description: str, on_click):
    return Text(
        text=label,
        content_description=description,
        on_click=on_click,
        padding=9,
        margin_end=8,
        background_color="#DDE8FF",
        corner_radius=8,
        text_color="#17396B",
    )


def _vertical_item(item: int, index: int):
    return Text(
        text=f"Row {item}",
        content_description=f"vertical-item-{item}",
        padding_start=12,
        padding_top=9,
        background_color="#F5F7FB" if index % 2 == 0 else "#E8EEF8",
        text_color="#182238",
    )


def _horizontal_item(item: int, index: int):
    return Column(
        Text(
            text=f"Card {item}",
            content_description=f"horizontal-item-{item}",
            text_color="#FFFFFF",
        ),
        Text(
            text="Swipe sideways",
            font_size=11,
            text_color="#DDE8FF",
            margin_top=5,
        ),
        padding=12,
        margin_end=4,
        background_color="#315FAD" if index % 2 == 0 else "#694CB1",
        corner_radius=10,
    )


def _dynamic_item(item: int, index: int):
    return Text(
        text=f"Key {item} · position {index}",
        content_description=f"dynamic-item-{item}",
        padding_start=12,
        padding_top=9,
        background_color="#FFF4DD" if index % 2 == 0 else "#FBE5BD",
        text_color="#503500",
    )


def App(context: AppContext):
    dynamic_data = state(tuple(range(100)))
    reversed_order = state(False)
    short_data = state(False)

    def reverse_data():
        reversed_order.set(not reversed_order.value)
        dynamic_data.set(tuple(reversed(dynamic_data.value)))

    def toggle_size():
        next_short = not short_data.value
        short_data.set(next_short)
        values = tuple(range(20 if next_short else 100))
        dynamic_data.set(tuple(reversed(values)) if reversed_order.value else values)

    def jump_dynamic():
        _dynamic_controller.scroll_to_index(
            min(50, len(dynamic_data.value) - 1),
            alignment="center",
            animated=False,
        )

    return Column(
        Text(
            text="Vyne List Lab",
            font_size=25,
            text_color="#172033",
            content_description="list-showcase-title",
        ),
        Text(
            text="Three virtual-list scenarios on the native Android host",
            font_size=13,
            text_color="#58657A",
            margin_top=3,
            margin_bottom=8,
        ),
        Row(
            _button(
                "Vertical: item 500",
                "jump-vertical",
                lambda: _vertical_controller.scroll_to_index(
                    500,
                    alignment="start",
                    animated=False,
                ),
            ),
            _button(
                "Back to top",
                "reset-vertical",
                lambda: _vertical_controller.scroll_to_offset(0, animated=False),
            ),
            margin_bottom=6,
        ),
        Text(text="1 · Vertical list · 1,000 rows", text_color="#23314D"),
        List(
            tuple(range(1000)),
            render_item=_vertical_item,
            key_for_item=lambda item, index: item,
            item_extent=42,
            controller=_vertical_controller,
            key="vertical-list",
            width="match_parent",
            height=170,
            margin_top=5,
            margin_bottom=9,
            background_color="#E8EEF8",
            content_description="vertical-virtual-list",
        ),
        Row(
            Text(text="2 · Horizontal list · 200 cards", text_color="#23314D"),
            _button(
                "Card 100",
                "jump-horizontal",
                lambda: _horizontal_controller.scroll_to_index(
                    100,
                    alignment="center",
                    animated=True,
                ),
            ),
            margin_bottom=5,
        ),
        List(
            tuple(range(200)),
            render_item=_horizontal_item,
            key_for_item=lambda item, index: item,
            item_extent=126,
            axis="horizontal",
            controller=_horizontal_controller,
            key="horizontal-list",
            width="match_parent",
            height=82,
            margin_bottom=9,
            content_description="horizontal-virtual-list",
        ),
        Text(
            text=f"3 · Dynamic keyed list · {len(dynamic_data.value)} rows",
            text_color="#23314D",
            content_description="dynamic-list-status",
        ),
        Row(
            _button("Reverse", "reverse-dynamic", reverse_data),
            _button("20 / 100", "resize-dynamic", toggle_size),
            _button("Jump", "jump-dynamic", jump_dynamic),
            margin_top=5,
            margin_bottom=5,
        ),
        List(
            dynamic_data.value,
            render_item=_dynamic_item,
            key_for_item=lambda item, index: item,
            item_extent=42,
            controller=_dynamic_controller,
            key="dynamic-list",
            width="match_parent",
            height=155,
            background_color="#FBE5BD",
            content_description="dynamic-virtual-list",
        ),
        width="match_parent",
        height="match_parent",
        padding=12,
        background_color="#FFFFFF",
        content_description="list-showcase-root",
    )


run_app(App)
