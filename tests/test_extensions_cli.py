"""Extension discovery, validation, and generation tests (EXT-04).

Covers the extension.toml contract (one field: android_register), convention
discovery, the journaled generation of the Kotlin registrant, gradle
property wiring, and doctor diagnostics.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from vyne.cli.extensions import (
    discover_extensions,
    generate_extension_files,
    registrant_content,
    registrant_target,
)
from vyne.cli.project import load_project

MANIFEST = """\
android_register = "dev.vyne.ext.timerring.TimerRingExtension"
"""


def _write_extension(
    root: Path,
    name: str = "timer_ring",
    manifest: str = MANIFEST,
) -> Path:
    ext_dir = root / "extensions" / name
    (ext_dir / "python").mkdir(parents=True)
    (ext_dir / "android").mkdir()
    (ext_dir / "python" / f"{name}.py").write_text(
        "def TimerRing(): ...\n", encoding="utf-8"
    )
    (ext_dir / "extension.toml").write_text(manifest, encoding="utf-8")
    return ext_dir


class DiscoveryTests(unittest.TestCase):
    def test_discovers_sorted_extensions(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_extension(root, "beta")
            _write_extension(root, "alpha")
            names = [e.name for e in discover_extensions(root)]
            self.assertEqual(["alpha", "beta"], names)

    def test_no_extensions_dir_is_empty(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual([], discover_extensions(Path(tmp)))

    def test_directory_name_is_the_identity(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ext = _write_extension(root, "timer_ring")
            discovered = discover_extensions(root)
            self.assertEqual("timer_ring", discovered[0].name)
            self.assertEqual(ext, discovered[0].root)

    def test_invalid_directory_name_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_extension(root, "bad-name")
            with self.assertRaisesRegex(RuntimeError, "valid Python identifier"):
                discover_extensions(root)

    def test_missing_android_register_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_extension(root, "timer_ring", "")
            with self.assertRaisesRegex(RuntimeError, "android_register"):
                discover_extensions(root)

    def test_invalid_register_fqn_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = MANIFEST.replace(
                "dev.vyne.ext.timerring.TimerRingExtension", "not-a-fqn"
            )
            _write_extension(root, "timer_ring", bad)
            with self.assertRaisesRegex(RuntimeError, "fully-qualified"):
                discover_extensions(root)

    def test_missing_dirs_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ext = _write_extension(root)
            import shutil
            shutil.rmtree(ext / "android")
            with self.assertRaisesRegex(RuntimeError, "android/"):
                discover_extensions(root)

    def test_broken_toml_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_extension(root, "timer_ring", "name = [broken")
            with self.assertRaisesRegex(RuntimeError, "Cannot parse"):
                discover_extensions(root)


class GenerationContentTests(unittest.TestCase):
    def test_empty_registrant(self):
        content = registrant_content([])
        self.assertIn("registerAppExtensions", content)
        self.assertNotIn(".register(context", content)

    def test_registrant_calls_extension(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_extension(root)
            ext = discover_extensions(root)[0]
            content = registrant_content([ext])
            self.assertIn(
                "dev.vyne.ext.timerring.TimerRingExtension.register(context, registry)",
                content,
            )

    def test_generation_writes_the_registrant(self):
        from vyne.cli.new import create_project
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "App"
            create_project(root, package="com.example.ext", module="app")
            _write_extension(root)
            extensions = discover_extensions(root)
            generate_extension_files(load_project(root), extensions)
            registrant = (root / "android" / "app" / "src" / "main" / "java"
                          / "dev" / "vyne" / "generated" / "ExtensionRegistrant.kt")
            self.assertIn("TimerRingExtension.register", registrant.read_text())

    def test_registrant_target_per_mode(self):
        for generated, expected in ((True, "app"), (False, "host")):
            project = type(
                "P",
                (),
                {"generated": generated, "root": Path("/tmp/x")},
            )()
            path = registrant_target(project)
            self.assertIn(expected, str(path))
            self.assertTrue(str(path).endswith("ExtensionRegistrant.kt"))


class GradlePropertyTests(unittest.TestCase):
    def test_gradle_properties_include_extension_dirs(self):
        from vyne.cli.new import create_project
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "App"
            create_project(root, package="com.example.ext", module="app")
            _write_extension(root)
            project = load_project(root)
            props = project.gradle_properties()
            kotlin = [p for p in props if p.startswith("-Pvyne.extensionKotlinDirs=")]
            self.assertEqual(1, len(kotlin))
            self.assertIn("extensions/timer_ring/android", kotlin[0])
            python = [p for p in props if p.startswith("-Pvyne.extensionPythonDirs=")]
            self.assertIn("extensions/timer_ring/python", python[0])
            # No extensions: empty dirs.
            import shutil
            shutil.rmtree(root / "extensions" / "timer_ring")
            project2 = load_project(root)
            empty = [p for p in project2.gradle_properties()
                     if p.startswith("-Pvyne.extensionKotlinDirs=")][0]
            self.assertTrue(empty.endswith("="))


class AddRemoveRebuildTests(unittest.TestCase):
    def test_add_and_remove_extension_rewires_the_registrant(self):
        from vyne.cli.new import create_project
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "App"
            create_project(root, package="com.example.ext", module="app")
            registrant = (root / "android" / "app" / "src" / "main" / "java"
                          / "dev" / "vyne" / "generated" / "ExtensionRegistrant.kt")

            # ADD: generation writes the registrant with the extension wired.
            _write_extension(root)
            generate_extension_files(load_project(root), discover_extensions(root))
            self.assertIn("TimerRingExtension.register", registrant.read_text())

            # REMOVE: generation restores the empty registrant.
            import shutil
            shutil.rmtree(root / "extensions" / "timer_ring")
            generate_extension_files(load_project(root), [])
            self.assertNotIn("TimerRingExtension", registrant.read_text())

            # Re-add: byte-identical regeneration is idempotent.
            _write_extension(root)
            generate_extension_files(load_project(root), discover_extensions(root))
            self.assertIn("TimerRingExtension.register", registrant.read_text())


class DoctorExtensionTests(unittest.TestCase):
    def test_doctor_reports_healthy_extensions(self):
        from vyne.cli.doctor import _checks
        from vyne.cli.new import create_project
        from vyne.cli.project import ProjectRepository
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "App"
            create_project(root, package="com.example.ext", module="app")
            _write_extension(root)
            inspection = ProjectRepository().inspect(root)
            checks = _checks(inspection, require_device=False)
            ext_check = [c for c in checks if c.name == "extensions"][0]
            self.assertTrue(ext_check.ok)
            self.assertIn("timer_ring", ext_check.detail)

    def test_doctor_flags_broken_extension(self):
        from vyne.cli.doctor import _checks
        from vyne.cli.new import create_project
        from vyne.cli.project import ProjectRepository
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "App"
            create_project(root, package="com.example.ext", module="app")
            # A broken extension is an expected failure: the inspection
            # records it as a stable issue, never a crash.
            _write_extension(root, "timer_ring", "")
            inspection = ProjectRepository().inspect(root)
            checks = _checks(inspection, require_device=False)
            ext_check = [c for c in checks if c.name == "extensions"][0]
            self.assertFalse(ext_check.ok)


if __name__ == "__main__":
    unittest.main()
