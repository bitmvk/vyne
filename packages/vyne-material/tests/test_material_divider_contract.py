"""MaterialDivider lowering and mount contract tests.

Verifies that the MaterialDivider composite lowers to core primitives
(Box) with the correct geometry, rejects invalid orientations, and
commits through the Runtime like any other component.
"""

from __future__ import annotations

import unittest

from vyne import Column
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport
from vyne_material import MaterialDivider


class MaterialDividerContractTests(unittest.TestCase):
    def test_horizontal_lowers_to_thin_box(self):
        element = MaterialDivider(thickness=2, inset=8)
        self.assertEqual(element.kind, "Box")
        self.assertEqual(element.props["height"], 2)
        self.assertEqual(element.props["margin_start"], 8)
        self.assertEqual(element.props["margin_end"], 8)
        self.assertNotIn("margin_top", element.props)
        self.assertIn("background_color", element.props)

    def test_vertical_lowers_to_wide_box(self):
        element = MaterialDivider(orientation="vertical", thickness=3)
        self.assertEqual(element.props["width"], 3)
        self.assertNotIn("height", element.props)

    def test_invalid_orientation_rejected(self):
        with self.assertRaises((TypeError, ValueError)):
            MaterialDivider(orientation="diagonal")

    def test_divider_mounts_and_commits(self):
        transport = MemoryTransport()
        runtime = Runtime(lambda: Column(MaterialDivider()), transport=transport)
        runtime.mount()
        kinds = [
            op["kind"] for op in transport.latest["ops"] if op["op"] == "create"
        ]
        self.assertEqual(kinds, ["Layout", "Box"])
        runtime.dispose()


if __name__ == "__main__":
    unittest.main()
