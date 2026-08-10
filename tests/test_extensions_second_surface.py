"""Real-import tests for the second_surface extension modules.

Both modules are example app modules mounted by name into a separate
Runtime/transport pair. They must import cleanly against the split
distributions: core primitives from ``vyne``, Material components from
``vyne_material``. These tests execute the real module files inside a
host registration attempt (the same context ``_start_registered_app`` uses)
so an unresolved import — for example a ``Button`` left on ``vyne`` — fails
here instead of only on device.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

from vyne import bootstrap
from vyne_material import Button as MaterialButton

_EXTENSIONS_ROOT = Path(__file__).resolve().parents[1] / "extensions"

_SURFACE_PATH = (
    _EXTENSIONS_ROOT / "second_surface" / "python" / "second_surface.py"
)
_PROMPT_PATH = (
    _EXTENSIONS_ROOT / "second_surface" / "python" / "second_surface_prompt.py"
)


def _load_module(name: str, path: Path):
    """Import one module inside an active host registration attempt."""
    attempt = bootstrap._RegistrationAttempt(name)
    bootstrap._registration_attempt.set(attempt)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, attempt
    finally:
        # Mirror the host bootstrap: the next attempt replaces this value.
        bootstrap._registration_attempt.set(None)


class SecondSurfaceImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.overlay, cls.overlay_attempt = _load_module(
            "second_surface_test", _SURFACE_PATH
        )
        cls.prompt, cls.prompt_attempt = _load_module(
            "second_surface_prompt_test", _PROMPT_PATH
        )

    def test_module_files_exist(self) -> None:
        self.assertTrue(_SURFACE_PATH.is_file())
        self.assertTrue(_PROMPT_PATH.is_file())

    def test_modules_import_and_resolve_button_to_vyne_material(self) -> None:
        for module, host_name in ((self.overlay, "OverlayHost"),
                                  (self.prompt, "PromptHost")):
            with self.subTest(module=host_name):
                self.assertTrue(callable(module.App))
                self.assertTrue(callable(getattr(module, host_name)))
                self.assertIs(module.Button, MaterialButton)

    def test_modules_registered_app_during_import(self) -> None:
        for module, attempt in ((self.overlay, self.overlay_attempt),
                                (self.prompt, self.prompt_attempt)):
            with self.subTest(module=module.__name__):
                # run_app(App) executed at module scope inside the attempt.
                registered = [fn for _, fn in attempt.records]
                self.assertIn(module.App, registered)

    def test_vyne_core_does_not_export_button(self) -> None:
        # Guards the exact regression this file exists for: a core re-export
        # would let these modules pass without vyne_material installed.
        import vyne
        self.assertNotIn("Button", vyne.__all__)
        self.assertFalse(hasattr(vyne, "Button"))

    def test_overlay_host_builds(self) -> None:
        host = self.overlay.OverlayHost()
        self.assertEqual(host.kind, "OverlayHost")
        self.assertEqual(host.props["dismiss_requested"], False)


if __name__ == "__main__":
    unittest.main()
