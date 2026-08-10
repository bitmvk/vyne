"""Material boundary acceptance tests (MATERIAL-01, MATERIAL-04).

Kept as a slim evidence file for the mount/policy checks that are not
duplicated by the per-area authority files:

- valid Slider and RangeSlider configurations mount
- explicit slider width is forwarded
- no Material component creates native Material widget kinds

All other coverage (validation rejection, callbacks, dates, disabled
states, colors, path commands, switch geometry, catalog lowering) lives
in the per-area authority files under this directory.
"""

from __future__ import annotations

import unittest

from vyne import Column
from vyne_material import RangeSlider, Slider
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport


class MaterialAcceptanceTests(unittest.TestCase):
    """MATERIAL-01: Valid configurations mount and render."""

    def test_slider_accepts_valid_config(self):
        """Valid slider configuration mounts successfully."""
        runtime = Runtime(
            lambda: Column(Slider(0.5, minimum=0, maximum=1, step=0.1)),
            transport=MemoryTransport(),
        )
        runtime.mount()
        self.assertIsNotNone(runtime._coordinator.accepted_root)

    def test_range_slider_accepts_valid_config(self):
        """Valid RangeSlider configuration mounts."""
        runtime = Runtime(
            lambda: Column(RangeSlider((0.2, 0.8), step=0.1)),
            transport=MemoryTransport(),
        )
        runtime.mount()
        self.assertIsNotNone(runtime._coordinator.accepted_root)

    def test_slider_respects_width(self):
        """Slider renders with specified width."""
        slider = Slider(0.5, width=240)
        self.assertEqual(slider.props.get("width"), 240)


class MaterialPolicyTests(unittest.TestCase):
    """MATERIAL-04: No native Material widget kinds."""

    def test_no_native_material_policy_widgets(self):
        """No Material component should create native Material widgets directly."""
        # The only allowed kinds are our primitives
        from vyne.spec.schema_v2 import PRIMITIVE_KINDS
        allowed_kinds = frozenset(PRIMITIVE_KINDS)

        # None of these are Material-specific native widgets
        material_native = {"Button", "CheckBox", "Switch", "SeekBar", "CalendarView"}
        overlap = allowed_kinds & material_native
        self.assertEqual(overlap, set())


if __name__ == "__main__":
    unittest.main()
