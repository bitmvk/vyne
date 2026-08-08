"""Application-level tests for the framework checkout showcase."""

from __future__ import annotations

from pathlib import Path
import sys
import time
import unittest

from vyne.bootstrap import _start_registered_app
from vyne.transport import MemoryTransport


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _node_with_description(runtime, description: str):
    return next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if node.props.get("content_description") == description
    )


def _click(runtime, description: str, sequence: int) -> None:
    node = _node_with_description(runtime, description)
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": sequence,
            "target": node.id,
            "event": "click",
            "handler": node.listeners["click"],
            "payload": {},
        }
    )


def _pointer(runtime, node, event: str, x: float, sequence: int) -> None:
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": sequence,
            "target": node.id,
            "event": event,
            "handler": node.listeners[event],
            "payload": {"x": x, "y": 24.0, "down_x": x, "down_y": 24.0},
        }
    )


class ShowcaseAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(EXAMPLES))

    @classmethod
    def tearDownClass(cls) -> None:
        if sys.path and sys.path[0] == str(EXAMPLES):
            sys.path.pop(0)
        sys.modules.pop("app", None)

    def setUp(self) -> None:
        self.transport = MemoryTransport()
        self.runtime = _start_registered_app(
            "app",
            transport=self.transport,
        )

    def tearDown(self) -> None:
        self.runtime.dispose()

    def test_showcase_mounts_on_motion_gallery(self):
        root = _node_with_description(self.runtime, "showcase-root")
        self.assertEqual(root.kind, "Layout")
        self.assertTrue(root.props["safe_area"])
        _node_with_description(self.runtime, "showcase-motion")
        _node_with_description(self.runtime, "motion-declarative-card")
        _node_with_description(self.runtime, "motion-canvas")

    def test_motion_gallery_emits_advanced_and_imperative_timelines(self):
        _click(self.runtime, "motion-reverse", 1)

        self.assertTrue(
            any(
                operation.get("op") == "motion_driver_set_target"
                for operation in self.runtime.latest_commit["ops"]
            )
        )

        _click(self.runtime, "motion-play-keyframes", 2)
        motion = next(
            operation
            for operation in self.runtime.latest_commit["ops"]
            if operation.get("op") == "motion_set_target"
        )
        self.assertEqual(motion["property"], "translation_x")
        self.assertEqual(motion["targets"], [210.0, 70.0, 185.0, 0.0])

    def test_async_gallery_commits_around_await_without_blocking_clicks(self):
        _click(self.runtime, "Async", 1)
        _node_with_description(self.runtime, "showcase-async")

        _click(self.runtime, "async-fetch", 2)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            stage = _node_with_description(self.runtime, "async-stage")
            if stage.props["text"] != "Idle":
                break
            time.sleep(0.01)
        self.assertNotEqual(
            _node_with_description(self.runtime, "async-stage").props["text"],
            "Idle",
        )

        _click(self.runtime, "async-side-action", 3)
        self.assertTrue(self.runtime.wait_for_async_callbacks(timeout=2))

        self.assertEqual(
            _node_with_description(self.runtime, "async-stage").props["text"],
            "Ready",
        )
        self.assertIn(
            "Dashboard payload #1",
            _node_with_description(self.runtime, "async-result").props["text"],
        )

    def test_style_and_control_sections_are_interactive(self):
        _click(self.runtime, "Style", 1)
        initial = _node_with_description(
            self.runtime, "style-composed-card"
        ).props["background_color"]
        _click(self.runtime, "style-palette", 2)
        changed = _node_with_description(
            self.runtime, "style-composed-card"
        ).props["background_color"]
        self.assertNotEqual(initial, changed)

        _click(self.runtime, "Controls", 3)
        _click(self.runtime, "Enable motion, not checked", 4)
        _node_with_description(self.runtime, "Enable motion, checked")

        _click(self.runtime, "Filter", 5)
        _node_with_description(self.runtime, "Filter, selected")

    def test_showcase_slider_drags_continuously(self):
        _click(self.runtime, "Controls", 1)
        slider = next(
            node
            for node in self.runtime._coordinator.accepted_index.values()
            if node.props.get("pointer_capture_axis") == "horizontal"
        )

        _pointer(self.runtime, slider, "pointer_down", 123.456, 2)
        self.assertEqual(
            _node_with_description(
                self.runtime, "controls-slider-value"
            ).props["text"],
            "Value 0.411",
        )

        _pointer(self.runtime, slider, "pointer_move", 177.3, 3)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if (
                _node_with_description(
                    self.runtime, "controls-slider-value"
                ).props["text"]
                == "Value 0.606"
            ):
                break
            time.sleep(0.01)
        self.assertEqual(
            _node_with_description(
                self.runtime, "controls-slider-value"
            ).props["text"],
            "Value 0.606",
        )


if __name__ == "__main__":
    unittest.main()
