from __future__ import annotations

from pathlib import Path
import tomllib
import unittest

from vyne.cli.project import load_project


class ProjectIdentityTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def test_framework_checkout_resolves_vyne_paths_and_identity(self):
        project = load_project(self.ROOT)

        self.assertEqual(project.app.name, "Vyne")
        self.assertEqual(project.app.package, "dev.vyne")
        self.assertEqual(project.package_python_dir.name, "src")
        self.assertEqual(project.package_python_dir.parent.name, "vyne")
        self.assertEqual(project.main_activity, "dev.vyne/dev.vyne.MainActivity")
        self.assertEqual(project.assemble_task, ":host:assembleDebug")

    def test_packaging_and_launcher_use_vyne(self):
        pyproject = tomllib.loads(
            (self.ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(pyproject["project"]["name"], "vyne")
        self.assertEqual(pyproject["project"]["scripts"]["vyne"], "vyne.cli.main:main")
        self.assertIn("packages/vyne/src", pyproject["tool"]["setuptools"]["packages"]["find"]["where"])

        launcher = (self.ROOT / "vyne").read_text(encoding="utf-8")
        self.assertIn("packages/vyne/src", launcher)
        self.assertIn("vyne.cli.main", launcher)

    def test_android_source_identity_uses_new_namespace(self):
        root_gradle = (
            self.ROOT / "android" / "build.gradle.kts"
        ).read_text(encoding="utf-8")
        host_manifest = (
            self.ROOT / "android" / "host" / "src" / "main" / "AndroidManifest.xml"
        ).read_text(encoding="utf-8")

        self.assertIn('id("com.chaquo.python")', root_gradle)
        self.assertIn("dev.vyne.MODULE_NAME", host_manifest)
        self.assertNotIn("pynativeui", root_gradle.lower())
        self.assertNotIn("pynativeui", host_manifest.lower())


if __name__ == "__main__":
    unittest.main()
