"""Long-running cross-layer tests for the complete Python framework pipeline.

Each generated case repeatedly builds a materially different public Element
tree, lowers it, reconciles it, validates the emitted protocol commit, and
applies that commit to the strict native reference model.  The independently
lowered desired tree must match the accumulated native state after every
transition.
"""

from __future__ import annotations

import random
import unittest

from vyne import Box, Canvas, Column, Image, Layout, Path, Row, Scroll, Text, TextInput, latest
from vyne.elements import event_name_for_prop
from vyne.events import event_delivery
from vyne.lowering import CanonicalElement, lower_element
from vyne.protocol import validate_message
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport

from tests.support.native_model import NativeModel


def _ignore_event(*_args):
    return None


def _scene(seed: int, step: int):
    rng = random.Random((seed + 1) * 1_000_003 + step)
    keys = list("abcdef")
    rng.shuffle(keys)
    keys = keys[: rng.randint(1, len(keys))]

    keyed_children = []
    for index, key in enumerate(keys):
        if (index + step) % 3 == 0:
            child = TextInput(
                key=key,
                text=f"{key}:{step}",
                hint=f"hint-{key}",
                on_text_change=(
                    latest(_ignore_event)
                    if (index + seed) % 2
                    else _ignore_event
                ),
                content_description=f"input-{key}",
            )
        elif (index + step) % 3 == 1:
            child = Box(
                Text(text=f"boxed-{key}-{step}"),
                key=key,
                width=20 + index,
                height=10 + step % 7,
                padding=(step + index) % 5,
                opacity=0.5 + (index % 3) * 0.2,
                on_click=_ignore_event if step % 2 else None,
            )
        else:
            child = Row(
                Text(text=key.upper()),
                Text(text=str(step)),
                key=key,
                on_pointer_move=(
                    latest(_ignore_event)
                    if step % 2
                    else _ignore_event
                ),
            )
        keyed_children.append(child)

    visual = (
        Canvas(
            width=24,
            height=24,
            view_box=[0, 0, 24, 24],
            draw=[
                {
                    "kind": "rect",
                    "x": step % 4,
                    "y": 1,
                    "width": 10,
                    "height": 11,
                    "fill": "#FF336699",
                }
            ],
        )
        if step % 2
        else Path(
            d=f"M0,0 L{5 + step % 10},10",
            stroke_color="#FF112233",
            stroke_width=1 + step % 3,
        )
    )

    return Column(
        Text(
            text=f"seed={seed};step={step}",
            font_size=12 + step % 8,
            text_color="#FF000000" if step % 2 else "#FFFFFFFF",
            on_click=_ignore_event if step % 4 else None,
            content_description="stress-header",
        ),
        Layout(
            *keyed_children,
            key="changing-row",
            orientation="horizontal" if step % 2 else "vertical",
            padding_start=step % 9,
            justify_content=("center" if step % 3 else "space_between"),
        ),
        Scroll(
            Column(
                Text(text=f"scroll-{step}"),
                Image(
                    source=f"asset-{step % 4}",
                    scale_type=("center_crop" if step % 2 else "fit_center"),
                ),
            ),
            key="scroll",
            height=80 + step % 6,
            safe_area=bool(step % 2),
        ),
        visual,
        Box(
            key="presentation",
            width=30 + step % 11,
            min_height=8,
            background_color="#FF445566",
            corner_radius=step % 6,
            translation_x=step % 5,
            rotation=step % 17,
            scale_x=0.8 + (step % 4) * 0.1,
            visible=step % 7 != 0,
            accessibility_role="button",
            accessibility_selected=step % 2 == 0,
        ),
        padding=seed % 5,
        align_items=("center" if step % 2 else "stretch"),
        content_description="stress-root",
    )


def _expected_node(element: CanonicalElement) -> dict:
    listeners: set[str] = set()
    latest_events: set[str] = set()
    for prop_name, prop_value in element.props.items():
        event_name = event_name_for_prop(prop_name)
        if event_name is None or prop_value is None:
            continue
        listeners.add(event_name)
        _, delivery = event_delivery(prop_value)
        if delivery == "latest":
            latest_events.add(event_name)
    return {
        "kind": element.kind,
        "props": dict(element.native_props),
        "listeners": listeners,
        "latest_events": latest_events,
        "children": [_expected_node(child) for child in element.children],
    }


def _actual_node(node: dict) -> dict:
    return {
        "kind": node["kind"],
        "props": node["props"],
        "listeners": set(node["listeners"]),
        "latest_events": set(node["latest_events"]),
        "children": [_actual_node(child) for child in node["children"]],
    }


class FrameworkStressMatrixTests(unittest.TestCase):
    def run_generated_case(self, seed: int) -> None:
        current = {"step": 0}
        transport = MemoryTransport()
        runtime = Runtime(
            lambda: _scene(seed, current["step"]),
            transport=transport,
        )
        native = NativeModel()
        try:
            runtime.mount()
            for step in range(50):
                if step:
                    current["step"] = step
                    runtime.request_render()

                commit = runtime.latest_commit
                self.assertIsNotNone(commit)
                validate_message(commit)
                native.apply_commit(commit)

                actual = [
                    _actual_node(node)
                    for node in native.tree()["children"]
                ]
                expected = [_expected_node(lower_element(_scene(seed, step)))]
                self.assertEqual(
                    actual,
                    expected,
                    f"seed={seed}, step={step}, commit={commit}",
                )
                self.assertEqual(runtime.revision, step + 1)
        finally:
            runtime.dispose()


def _generated_test(seed: int):
    def test(self):
        self.run_generated_case(seed)

    test.__name__ = f"test_generated_framework_lifecycle_seed_{seed:02d}"
    return test


for _seed in range(12):
    setattr(
        FrameworkStressMatrixTests,
        f"test_generated_framework_lifecycle_seed_{_seed:02d}",
        _generated_test(_seed),
    )


if __name__ == "__main__":
    unittest.main()
