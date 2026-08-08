from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import tomllib
import unittest
from unittest.mock import patch

from vyne.cli.new import create_project
from vyne.cli.project import load_project


class CliProjectTests(unittest.TestCase):
    def test_new_project_creates_expected_structure(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "HelloApp"

            create_project(path, package="com.example.hello", label="Hello App")

            self.assertTrue((path / "vyne.toml").is_file())
            self.assertTrue((path / "pyproject.toml").is_file())
            self.assertTrue((path / "app.py").is_file())
            self.assertTrue((path / "android" / "gradlew").is_file())
            self.assertTrue((path / "android" / "app" / "build.gradle.kts").is_file())

            config = (path / "vyne.toml").read_text(encoding="utf-8")
            self.assertIn('package = "com.example.hello"', config)
            self.assertIn('source = "app.py"', config)
            self.assertIn("[paths]", config)
            self.assertIn("base_project_root", config)

    def test_new_project_uses_custom_module_as_source_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "CustomModule"

            create_project(path, module="main")
            project = load_project(path)

            self.assertEqual(project.app.module, "main")
            self.assertEqual(project.app.source, "main.py")
            self.assertTrue((path / "main.py").is_file())

    def test_new_project_rejects_invalid_module_name(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "valid Python identifier"):
                create_project(Path(tmp) / "BadModule", module="bad-name")

    def test_new_project_rejects_keyword_module_name(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "valid Python identifier"):
                create_project(Path(tmp) / "BadModule", module="class")

    def test_new_project_rejects_invalid_package_name(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "valid Android application id"):
                create_project(Path(tmp) / "BadPackage", package="com.example.class")

    def test_new_project_avoids_android_reserved_words_in_default_package(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "base-package"

            create_project(path)
            project = load_project(path)

            self.assertEqual(project.app.package, "com.example.base.apppackage")

    def test_new_project_allows_non_empty_directory_without_conflicts(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "Existing"
            path.mkdir()
            (path / "notes.txt").write_text("keep me", encoding="utf-8")

            create_project(path)

            self.assertEqual((path / "notes.txt").read_text(encoding="utf-8"), "keep me")
            self.assertTrue((path / "app.py").is_file())

    def test_new_project_rejects_existing_generated_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "Existing"
            path.mkdir()
            (path / "app.py").write_text("existing", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "Refusing to overwrite"):
                create_project(path)

            self.assertEqual((path / "app.py").read_text(encoding="utf-8"), "existing")

    def test_new_project_force_overwrites_existing_generated_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "Existing"
            path.mkdir()
            (path / "app.py").write_text("existing", encoding="utf-8")

            create_project(path, force=True)

            self.assertIn("run_app(App)", (path / "app.py").read_text(encoding="utf-8"))

    def test_new_project_updates_existing_pyproject_dependency(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ExistingUvProject"
            path.mkdir()
            existing = '[project]\nname = "existing"\n'
            (path / "pyproject.toml").write_text(existing, encoding="utf-8")

            create_project(path)

            pyproject = (path / "pyproject.toml").read_text(encoding="utf-8")
            self.assertIn('name = "existing"', pyproject)
            self.assertIn("vyne", pyproject)
            self.assertTrue((path / "vyne.toml").is_file())

    def test_new_project_updates_existing_empty_dependencies(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ExistingUvProject"
            path.mkdir()
            (path / "pyproject.toml").write_text(
                '[project]\nname = "existing"\ndependencies = []\n',
                encoding="utf-8",
            )

            create_project(path)

            pyproject = (path / "pyproject.toml").read_text(encoding="utf-8")
            parsed = tomllib.loads(pyproject)
            self.assertIn("dependencies = [", pyproject)
            self.assertTrue(
                any(
                    dependency.startswith("vyne")
                    for dependency in parsed["project"]["dependencies"]
                )
            )

    def test_new_project_updates_existing_multiline_dependencies(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ExistingUvProject"
            path.mkdir()
            (path / "pyproject.toml").write_text(
                '[project]\nname = "existing"\ndependencies = [\n    "requests",\n]\n',
                encoding="utf-8",
            )

            create_project(path)

            pyproject = (path / "pyproject.toml").read_text(encoding="utf-8")
            parsed = tomllib.loads(pyproject)
            self.assertIn("requests", parsed["project"]["dependencies"])
            self.assertTrue(
                any(
                    dependency.startswith("vyne")
                    for dependency in parsed["project"]["dependencies"]
                )
            )

    def test_new_project_updates_existing_uv_multiline_dependencies_parseably(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ExistingUvProject"
            path.mkdir()
            (path / "pyproject.toml").write_text(
                (
                    '[project]\n'
                    'name = "existing"\n'
                    'dependencies = [\n'
                    '    "requests>=2.34.2",\n'
                    ']\n'
                ),
                encoding="utf-8",
            )

            create_project(path)

            pyproject = (path / "pyproject.toml").read_text(encoding="utf-8")
            parsed = tomllib.loads(pyproject)
            self.assertIn("requests>=2.34.2", parsed["project"]["dependencies"])
            self.assertTrue(
                any(
                    dependency.startswith("vyne")
                    for dependency in parsed["project"]["dependencies"]
                )
            )

    def test_new_project_force_overwrites_existing_pyproject(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ExistingUvProject"
            path.mkdir()
            (path / "pyproject.toml").write_text(
                '[project]\nname = "existing"\n',
                encoding="utf-8",
            )

            create_project(path, force=True)

            self.assertIn(
                "vyne",
                (path / "pyproject.toml").read_text(encoding="utf-8"),
            )

    def test_new_project_can_be_rerun_when_generated_files_match(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ExistingUvProject"
            path.mkdir()
            (path / "pyproject.toml").write_text(
                '[project]\nname = "existing"\n',
                encoding="utf-8",
            )

            create_project(path)
            create_project(path)

            self.assertTrue((path / "vyne.toml").is_file())
            self.assertTrue((path / "app.py").is_file())

    def test_new_project_can_be_created_without_checkout_root(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            path = tmp_path / "Packaged"
            base_project = tmp_path / "base_project"
            package_python_dir = tmp_path / "site-packages"
            for relative in [
                "gradle/wrapper/gradle-wrapper.jar",
                "gradle/wrapper/gradle-wrapper.properties",
                "gradlew",
                "gradlew.bat",
            ]:
                file_path = base_project / relative
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text("placeholder", encoding="utf-8")
            (base_project / "android-host" / "src" / "main" / "java").mkdir(
                parents=True
            )

            with (
                patch("vyne.cli.new.checkout_root_from_package", return_value=None),
                patch(
                    "vyne.cli.new.base_project_root_from_package",
                    return_value=base_project,
                ),
                patch(
                    "vyne.cli.new.package_python_dir_from_package",
                    return_value=package_python_dir,
                ),
            ):
                create_project(path)

            pyproject = (path / "pyproject.toml").read_text(encoding="utf-8")
            self.assertIn('"vyne"', pyproject)

            settings = (path / "android" / "settings.gradle.kts").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("runtime", settings)


if __name__ == "__main__":
    unittest.main()
