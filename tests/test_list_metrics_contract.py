from __future__ import annotations

import unittest

from vyne import Box, Scroll
from vyne.events import latest
from vyne.lowering import lower_element


class InternalListMetricsContractTests(unittest.TestCase):
    def test_scroll_metrics_listener_is_scroll_only(self) -> None:
        callback = latest(lambda event: None)
        canonical = lower_element(Scroll(on_scroll_metrics=callback))

        self.assertIs(canonical.props["on_scroll_metrics"], callback)
        with self.assertRaisesRegex(ValueError, "Unsupported prop"):
            lower_element(Box(on_scroll_metrics=callback))

    def test_layout_metrics_listener_is_available_to_cell_wrappers(self) -> None:
        callback = latest(lambda event: None)

        canonical = lower_element(Box(on_layout_metrics=callback))

        self.assertIs(canonical.props["on_layout_metrics"], callback)


if __name__ == "__main__":
    unittest.main()
