"""Focused tests for Material Python source wiring in the Android builds.

Covers the two consumers of the separate ``packages/vyne-material/src``
source tree:

- the framework-checkout host build (``android/host/build.gradle.kts``) used
  by ``vyne run`` with ``examples/app.py``;
- the generated-project ``app/build.gradle.kts`` template, which must keep
  working when both distributions are installed in one site-packages dir and
  support an explicit ``vyne.materialPythonDir`` override.

The canonical template files ship as package resources in
``vyne/cli/templates/``.
"""

from __future__ import annotations

from pathlib import Path
import unittest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HOST_BUILD = _REPO_ROOT / "android" / "host" / "build.gradle.kts"


class HostBuildMaterialWiringTests(unittest.TestCase):
    """The framework-checkout host app bundles the separate material source."""

    def test_host_build_declares_material_python_dir(self) -> None:
        text = _HOST_BUILD.read_text(encoding="utf-8")
        self.assertIn('providers.gradleProperty("vyne.materialPythonDir")', text)
        self.assertIn('rootProject.file("../packages/vyne-material/src")', text)

    def test_host_build_adds_material_dir_to_chaquopy_source_sets(self) -> None:
        text = _HOST_BUILD.read_text(encoding="utf-8")
        self.assertIn("if (materialPythonDir.isDirectory)", text)
        self.assertIn("srcDir(materialPythonDir)", text)


class GeneratedTemplateMaterialWiringTests(unittest.TestCase):
    """The generated app template supports an explicit material source dir."""

    def test_template_declares_material_python_dir_without_default(self) -> None:
        from vyne.cli.templates import load

        app_build_gradle = load("app-build.gradle.kts")
        # Generated projects install both distributions into one
        # site-packages dir covered by frameworkPythonDir, so the material
        # dir must default to absent (no separate source path guessed).
        self.assertIn('providers.gradleProperty("vyne.materialPythonDir")', app_build_gradle)
        self.assertIn("if (materialPythonPath != null) file(materialPythonPath) else null",
                      app_build_gradle)
        self.assertNotIn("../packages/vyne-material/src", app_build_gradle)

    def test_template_guards_material_src_dir(self) -> None:
        from vyne.cli.templates import load

        app_build_gradle = load("app-build.gradle.kts")
        self.assertIn("if (materialPythonDir != null)", app_build_gradle)
        self.assertIn("srcDir(materialPythonDir)", app_build_gradle)

    def test_all_template_resources_load(self) -> None:
        from vyne.cli.templates import load

        for name in (
            "gradle.properties",
            "root-build.gradle.kts",
            "app-build.gradle.kts",
            "settings.gradle.kts",
            "AndroidManifest.xml",
        ):
            content = load(name)
            self.assertTrue(content, f"template {name!r} is empty")


class CliMaterialDirPropertyTests(unittest.TestCase):
    """``Project.gradle_properties`` forwards the material source dir."""

    def test_framework_checkout_forwards_material_python_dir(self) -> None:
        from vyne.cli.project import load_project

        project = load_project(_REPO_ROOT)
        self.assertIsNotNone(project.checkout_root)
        self.assertIsNotNone(project.material_python_dir)
        self.assertTrue(
            project.material_python_dir.name == "src"
            and project.material_python_dir.parent.name == "vyne-material"
        )
        props = project.gradle_properties()
        self.assertIn(
            f"-Pvyne.materialPythonDir={project.material_python_dir}",
            props,
        )

    def test_project_without_checkout_root_has_no_material_property(self) -> None:
        from vyne.cli.config import AppIdentity, AndroidSpec
        from vyne.cli.project import Project

        project = Project(
            root=Path("/tmp/nonexistent-project"),
            config_path=None,
            app=AppIdentity(name="app", label="App", package="com.example.app",
                            module="app", source="app.py", version="0.1.0",
                            version_code=1),
            android=AndroidSpec(min_sdk=26, target_sdk=35, compile_sdk=35),
            package_python_dir=Path("/tmp/site-packages"),
            base_project_root=Path("/tmp/base"),
            generated=True,
            checkout_root=None,
        )
        self.assertIsNone(project.material_python_dir)
        self.assertNotIn(
            "-Pvyne.materialPythonDir",
            project.gradle_properties(),
        )


if __name__ == "__main__":
    unittest.main()
