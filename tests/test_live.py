"""Live hot-reload loader tests.

Covers the host-independent parts of ``vyne.live``: enable detection, the
swappable-module eviction policy, REV change detection, and the CLI push
source collection. The Android side (watcher -> Activity recreate) is
exercised on-device, not here.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import types
import unittest

from vyne import live


class _File:
    def __init__(self, path: Path) -> None:
        self._path = str(path)

    def getAbsolutePath(self) -> str:  # noqa: N802 - Java method name
        return self._path


class _Context:
    def __init__(self, files_dir: Path) -> None:
        self._files_dir = _File(files_dir)

    def getFilesDir(self):  # noqa: N802 - Java method name
        return self._files_dir


class _Host:
    def __init__(self, files_dir: Path) -> None:
        self._context = _Context(files_dir)

    def getActivity(self):  # noqa: N802 - Java method name
        return self._context


def _module(name: str, file: str | None) -> types.SimpleNamespace:
    module = types.SimpleNamespace(__name__=name)
    if file is not None:
        module.__file__ = file
    return module


class EnableTests(unittest.TestCase):
    def test_disabled_without_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            live_dir = Path(tmp) / "vyne-live"
            live_dir.mkdir()
            self.assertFalse(live._enabled(live_dir))
            self.assertFalse(live.install(_Host(Path(tmp)), module_name="app"))

    def test_enabled_with_marker_and_armed_sys_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            live_dir = Path(tmp) / "vyne-live"
            live_dir.mkdir()
            (live_dir / "ENABLED").touch()
            previous = list(sys.path)
            try:
                self.assertTrue(live.install(_Host(Path(tmp)), module_name="app"))
                self.assertEqual(sys.path[0], str(live_dir))
            finally:
                if str(live_dir) in sys.path:
                    sys.path.remove(str(live_dir))
                live._watcher_stop.set()

    def test_no_host_activity_is_off(self) -> None:
        class Bare:
            pass

        self.assertFalse(live.install(Bare(), module_name="app"))


class EvictionTests(unittest.TestCase):
    def test_evicts_app_module_by_name_always(self) -> None:
        live_dir = Path("/device/files/vyne-live")
        modules = {
            "app": _module("app", "/apk/assets/app.py"),  # frozen, not under live
            "vyne": _module("vyne", "/apk/assets/site-packages/vyne/__init__.py"),
        }
        live.evict_swappable("app", live_dir, sys_modules=modules)
        self.assertNotIn("app", modules)
        self.assertIn("vyne", modules)

    def test_evicts_submodules_under_live_tree_only(self) -> None:
        live_dir = Path("/device/files/vyne-live")
        modules = {
            "app": _module("app", "/device/files/vyne-live/app.py"),
            "app.ui": _module("app.ui", "/device/files/vyne-live/ui/__init__.py"),
            "material": _module("material", "/apk/assets/material/__init__.py"),
            "os": _module("os", None),
        }
        live.evict_swappable("app", live_dir, sys_modules=modules)
        self.assertEqual(set(modules), {"material", "os"})

    def test_unique_prefix_does_not_evict_sibling_live_dirs(self) -> None:
        live_dir = Path("/device/files/vyne-live")
        modules = {
            "other": _module(
                "other", "/device/files/vyne-live-something/app.py"
            ),
        }
        live.evict_swappable("app", live_dir, sys_modules=modules)
        self.assertIn("other", modules)


class RevTests(unittest.TestCase):
    def test_rev_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            live_dir = Path(tmp) / "vyne-live"
            live_dir.mkdir()
            self.assertIsNone(live._read_rev(live_dir))
            (live_dir / "REV").write_text("  123  ", encoding="utf-8")
            self.assertEqual(live._read_rev(live_dir), "123")


class CollectTests(unittest.TestCase):
    def test_collect_mirrors_app_and_extension_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_dir = root / "app"
            app_dir.mkdir()
            (app_dir / "app.py").write_text("", encoding="utf-8")
            (app_dir / "ui").mkdir()
            (app_dir / "ui" / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "tests").mkdir()
            (app_dir / "tests" / "test_app.py").write_text("", encoding="utf-8")

            ext_dir = root / "ext" / "python"
            ext_dir.mkdir(parents=True)
            (ext_dir / "timer_ring.py").write_text("", encoding="utf-8")

            project = types.SimpleNamespace(
                app_source=app_dir / "app.py",
                extensions=(
                    types.SimpleNamespace(python_dir=ext_dir),
                ),
            )
            from vyne.cli.live import _collect

            files = _collect(project)
            rels = {rel for _, rel in files}
            self.assertEqual(
                rels,
                {
                    "app.py",
                    "ui/__init__.py",
                    "timer_ring.py",  # extension module flattened into live tree
                },
            )
            self.assertNotIn("tests/test_app.py", rels)


if __name__ == "__main__":
    unittest.main()
