from __future__ import annotations

import vyne

from vyne import Ref, Text
from vyne._effects import ScrollToEffect
from vyne.elements import _horizontal_scroll
from vyne.runtime import Runtime
from vyne.state import current_runtime
from vyne.transport import MemoryTransport


def test_private_horizontal_scroll_wraps_multiple_children_in_a_row() -> None:
    element = _horizontal_scroll(Text(text="a"), Text(text="b"))

    assert element.kind == "HorizontalScroll"
    assert len(element.children) == 1
    assert element.children[0].kind == "Layout"
    assert element.children[0].props["orientation"] == "horizontal"
    assert not hasattr(vyne, "HorizontalScroll")


def test_horizontal_scroll_uses_generic_effect_lane() -> None:
    scroll_ref = Ref()

    def scroll(event) -> None:
        current_runtime()._queue_native_effect(
            ScrollToEffect(
                scroll_ref.current,
                offset_x=120,
                offset_y=0,
                animated=False,
            )
        )

    runtime = Runtime(
        lambda: _horizontal_scroll(
            Text(text="scroll", on_click=scroll),
            ref=scroll_ref,
            width=100,
        ),
        transport=MemoryTransport(),
    )
    runtime.mount()
    target = next(
        node for node in runtime._coordinator.accepted_index.values()
        if "click" in node.listeners
    )
    runtime.dispatch_event({
        "type": "event",
        "seq": 1,
        "target": target.id,
        "event": "click",
        "handler": target.listeners["click"],
        "payload": {},
    })

    assert runtime.latest_commit["ops"] == [{
        "op": "scroll_to",
        "id": scroll_ref.current.node_id,
        "offset_x": 120.0,
        "offset_y": 0.0,
        "animated": False,
    }]
