"""Package boundary tests for the vyne / vyne-material split.

Proves:
- The `vyne` core imports without `vyne_material` and without exposing
  Material names or the legacy `AnimatedValue`.
- The `vyne-material` distribution imports as `vyne_material` and re-exports
  the Material components when installed in the workspace.
- Both distributions can be imported in the same process without a cycle.
"""

from __future__ import annotations

import importlib
import sys
import unittest


class CoreBoundaryTests(unittest.TestCase):
    """Core must not depend on or re-export the Material package."""

    def test_core_import_does_not_load_vyne_material(self):
        """Importing vyne must not pull vyne_material into sys.modules.

        Runs in a subprocess because other test modules import vyne_material
        in the shared interpreter before this assertion runs.
        """
        import subprocess
        import sys

        script = (
            "import sys; import vyne; "
            "sys.exit(1 if 'vyne_material' in sys.modules else 0)"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"vyne core import loaded vyne_material: {result.stderr}",
        )

    def test_core_has_no_material_attribute(self):
        """vyne.material no longer exists on the core package."""
        import vyne
        self.assertFalse(hasattr(vyne, "material"))

    def test_core_does_not_re_export_material_names(self):
        """Material component names are not in the core __all__."""
        import vyne
        for name in ("Button", "Slider", "Switch", "TextField",
                     "MaterialTheme", "ColorScheme"):
            self.assertNotIn(name, vyne.__all__)
            self.assertFalse(hasattr(vyne, name))

    def test_core_keeps_animation_and_element_api(self):
        """Animated/animate and primitive widgets remain on core."""
        import vyne
        for name in ("Animated", "AnimatedNode", "animate", "AnimationEvent",
                     "Box", "Text", "Column", "Canvas", "state", "component"):
            self.assertIn(name, vyne.__all__)

    def test_core_no_longer_exports_legacy_animated_value(self):
        """AnimatedValue was removed from the core API."""
        import vyne
        self.assertNotIn("AnimatedValue", vyne.__all__)
        self.assertFalse(hasattr(vyne, "AnimatedValue"))


class MaterialDistributionTests(unittest.TestCase):
    """The vyne-material workspace member must import and function."""

    def test_material_imports_and_exposes_components(self):
        import vyne_material
        self.assertTrue(callable(vyne_material.Button))
        self.assertTrue(callable(vyne_material.Slider))
        self.assertTrue(callable(vyne_material.Switch))
        self.assertTrue(callable(vyne_material.TextField))
        self.assertTrue(callable(vyne_material.MaterialTheme))
        self.assertNotIn("MATERIAL3_CATALOG", vyne_material.__all__)
        self.assertNotIn("Divider", vyne_material.__all__)

    def test_material_theme_types_are_exported(self):
        import vyne_material
        for name in ("ColorScheme", "Typography", "TypeStyle", "ShapeScale",
                     "DEFAULT_THEME"):
            self.assertIn(name, vyne_material.__all__)

    def test_material_all_names_are_importable(self):
        """Everything in vyne_material.__all__ can be imported."""
        import vyne_material
        for name in vyne_material.__all__:
            self.assertTrue(
                hasattr(vyne_material, name),
                f"vyne_material.__all__ claims {name!r} but it's not importable",
            )

    def test_material_components_render_to_core_primitives(self):
        """Material composites lower to core primitives (no new kinds)."""
        import vyne_material

        core_kinds = {"Box", "Layout", "Text", "TextInput", "Canvas", "Scroll"}
        button = vyne_material.Button(label="Press")
        self.assertIn(button.kind, core_kinds)
        slider = vyne_material.Slider(0.5)
        self.assertIn(slider.kind, core_kinds)
        switch = vyne_material.Switch(True)
        self.assertIn(switch.kind, core_kinds)

    def test_material_and_core_import_together(self):
        """Both distributions can coexist in one process without a cycle."""
        importlib.import_module("vyne")
        importlib.import_module("vyne_material")
        self.assertIn("vyne", sys.modules)
        self.assertIn("vyne_material", sys.modules)


if __name__ == "__main__":
    unittest.main()
