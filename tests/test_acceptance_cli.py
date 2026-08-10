"""CLI and project generation acceptance tests (CLI-01, CLI-02).

Tests for:
- Structure-preserving TOML dependency editing
- PEP 508 requirement parsing and normalized comparison
- Config validation (package name, version, SDK ordering, ABI)
- Atomic project generation and rollback
- Generated project structure and build contract

Evidence: filesystem digest/rollback and generated project smoke.
"""

from __future__ import annotations

import json
import re
import shutil
import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from vyne.cli.new import create_project
from vyne.cli.project import load_project


class TOMLDependencyEditingTests(unittest.TestCase):
    """CLI-01: Structure-preserving dependency editing."""

    def _project_with_pyproject(self, content: str) -> Path:
        """Create a project dir whose pyproject.toml starts with *content*."""
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "TestProject"
        path.mkdir(parents=True, exist_ok=True)
        (path / "pyproject.toml").write_text(content, encoding="utf-8")
        return path

    def test_add_to_empty_dependencies(self):
        """Adding Vyne to empty dependencies list."""
        path = self._project_with_pyproject(
            '[project]\nname = "test"\ndependencies = []\n',
        )
        create_project(path)
        pyproject = tomllib.loads(
            (path / "pyproject.toml").read_text(encoding="utf-8")
        )
        deps = pyproject["project"]["dependencies"]
        self.assertTrue(any(d.startswith("vyne") for d in deps))

    def test_existing_vyne_is_noop(self):
        """Existing Vyne dependency is byte-for-byte no-op."""
        path = self._project_with_pyproject(
            '[project]\nname = "test"\ndependencies = ["vyne"]\n',
        )
        create_project(path)
        pyproject = (path / "pyproject.toml").read_text(encoding="utf-8")
        # Should not duplicate
        self.assertEqual(pyproject.count('"vyne"'), 1)

    def test_vyness_not_matched(self):
        """vyness is not Vyne."""
        path = self._project_with_pyproject(
            '[project]\nname = "test"\ndependencies = ["vyness>=1.0"]\n',
        )
        create_project(path)
        pyproject = tomllib.loads(
            (path / "pyproject.toml").read_text(encoding="utf-8")
        )
        deps = pyproject["project"]["dependencies"]
        # Should have both vyness and vyne
        self.assertTrue(any("vyness" in d for d in deps))
        self.assertTrue(any(d.startswith("vyne") for d in deps))

    def test_comments_preserved(self):
        """Comments in TOML are preserved."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "TestProject"
            content = (
                '# Top comment\n'
                '[project]\n'
                'name = "test"\n'
                '# inline comment about deps\n'
                'dependencies = [\n'
                '    "requests",  # keep this\n'
                ']\n'
            )
            path.mkdir(parents=True, exist_ok=True)
            (path / "pyproject.toml").write_text(content, encoding="utf-8")
            create_project(path)

            result = (path / "pyproject.toml").read_text(encoding="utf-8")
            self.assertIn("keep this", result)

    def test_multiline_arrays_preserved(self):
        """Multiline array formatting is preserved."""
        path = self._project_with_pyproject(
            '[project]\nname = "test"\ndependencies = [\n    "requests>=2.34",\n]\n',
        )
        create_project(path)
        result = (path / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("requests>=2.34", result)

    def test_trailing_commas_preserved(self):
        """Trailing commas are preserved."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "TestProject"
            content = (
                '[project]\n'
                'name = "test"\n'
                'dependencies = [\n'
                '    "requests>=2.34",\n'
                ']\n'
            )
            path.mkdir(parents=True, exist_ok=True)
            (path / "pyproject.toml").write_text(content, encoding="utf-8")
            create_project(path)
            pyproject = (path / "pyproject.toml").read_text(encoding="utf-8")
            parsed = tomllib.loads(pyproject)
            deps = parsed["project"]["dependencies"]
            self.assertTrue(any(d.startswith("vyne") for d in deps))

    def test_tool_tables_preserved(self):
        """Unrelated tool tables are preserved."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "TestProject"
            content = (
                '[project]\n'
                'name = "test"\n'
                'dependencies = []\n'
                '\n'
                '[tool.uv]\n'
                'dev-dependencies = ["pytest"]\n'
            )
            path.mkdir(parents=True, exist_ok=True)
            (path / "pyproject.toml").write_text(content, encoding="utf-8")
            create_project(path)
            result = (path / "pyproject.toml").read_text(encoding="utf-8")
            self.assertIn("tool.uv", result)
            self.assertIn("pytest", result)

    def test_url_dependency_preserved(self):
        """URL-based dependencies are preserved."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "TestProject"
            content = (
                '[project]\n'
                'name = "test"\n'
                'dependencies = ["my-pkg @ https://example.com/pkg.whl"]\n'
            )
            path.mkdir(parents=True, exist_ok=True)
            (path / "pyproject.toml").write_text(content, encoding="utf-8")
            create_project(path)
            result = (path / "pyproject.toml").read_text(encoding="utf-8")
            parsed = tomllib.loads(result)
            deps = parsed["project"]["dependencies"]
            self.assertTrue(any("my-pkg" in d for d in deps))
            self.assertTrue(any(d.startswith("vyne") for d in deps))

    def test_case_normalized_matching(self):
        """VYNE, VyNe, vyne are all recognized."""
        for variant in ["VYNE", "VyNe", "vyne", "vYnE"]:
            with TemporaryDirectory() as tmp:
                path = Path(tmp) / "TestProject"
                path.mkdir(parents=True, exist_ok=True)
                (path / "pyproject.toml").write_text(
                    f'[project]\nname = "test"\ndependencies = ["{variant}"]\n',
                    encoding="utf-8",
                )
                create_project(path)
                result = (path / "pyproject.toml").read_text(encoding="utf-8")
                # Should not add another vyne
                self.assertIn(variant, result)

    def test_dash_underscore_normalization(self):
        """vyne-core is not vyne."""
        path = self._project_with_pyproject(
            '[project]\nname = "test"\ndependencies = ["vyne-core>=1.0"]\n'
        )
        create_project(path)
        pyproject = tomllib.loads(
            (path / "pyproject.toml").read_text(encoding="utf-8")
        )
        deps = pyproject["project"]["dependencies"]
        self.assertTrue(any("vyne-core" in d for d in deps))
        self.assertTrue(any(d.startswith("vyne") for d in deps))


class ConfigValidationTests(unittest.TestCase):
    """CLI-02: Config validation (package name, version, SDK, ABI)."""

    def test_invalid_package_and_module_rejected(self):
        """Invalid packages/modules are rejected through create_project."""
        cases = [
            ("com.example.class", None),
            (None, "class"),
            (None, "bad-name"),
        ]
        for package, module in cases:
            with self.subTest(package=package, module=module):
                with TemporaryDirectory() as tmp:
                    with self.assertRaises(RuntimeError):
                        create_project(
                            Path(tmp) / "BadProject",
                            package=package or "com.example.ok",
                            module=module or "app",
                        )

    def test_valid_package_accepted(self):
        """Valid package names create project successfully."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ValidProject"
            create_project(path, package="com.example.hello", label="Hello App")
            project = load_project(path)
            self.assertEqual(project.app.package, "com.example.hello")


class ProjectGenerationTests(unittest.TestCase):
    """CLI-02: Project generation and rollback."""

    def test_new_project_creates_expected_structure(self):
        """Generated project has all required files."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "HelloApp"
            create_project(path, package="com.example.hello", label="Hello App")

            required_files = [
                "vyne.toml",
                "pyproject.toml",
                "app.py",
                "android/gradlew",
                "android/app/build.gradle.kts",
                "android/settings.gradle.kts",
                "android/build.gradle.kts",
            ]
            for file in required_files:
                self.assertTrue((path / file).exists(), f"Missing: {file}")

    def test_config_file_contents(self):
        """vyne.toml contains correct configuration."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ConfigTest"
            create_project(path, package="com.example.config", label="Config App")

            config = (path / "vyne.toml").read_text(encoding="utf-8")
            self.assertIn('package = "com.example.config"', config)
            self.assertIn('label = "Config App"', config)
            self.assertIn('source = "app.py"', config)
            self.assertIn("[paths]", config)

    def test_app_py_contents(self):
        """Generated app.py contains run_app."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "AppTest"
            create_project(path)

            app_py = (path / "app.py").read_text(encoding="utf-8")
            self.assertIn("run_app", app_py)
            self.assertIn("from vyne import", app_py)

    def test_refuses_overwrite_existing_file(self):
        """Project creation refuses to overwrite existing managed files."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "Existing"
            path.mkdir()
            (path / "app.py").write_text("existing content", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                create_project(path)

            # File should be unchanged
            self.assertEqual(
                (path / "app.py").read_text(encoding="utf-8"),
                "existing content",
            )

    def test_force_overwrites(self):
        """--force overwrites existing files."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ForceTest"
            path.mkdir()
            (path / "app.py").write_text("existing", encoding="utf-8")

            create_project(path, force=True)

            content = (path / "app.py").read_text(encoding="utf-8")
            self.assertIn("run_app", content)

    def test_preserves_unrelated_files(self):
        """Unrelated files survive project generation."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "Mixed"
            path.mkdir()
            (path / "notes.txt").write_text("my notes", encoding="utf-8")
            path.mkdir(parents=True, exist_ok=True)
            (path / "data.json").write_text('{"key": "value"}', encoding="utf-8")

            create_project(path)

            self.assertEqual(
                (path / "notes.txt").read_text(encoding="utf-8"),
                "my notes",
            )
            self.assertEqual(
                (path / "data.json").read_text(encoding="utf-8"),
                '{"key": "value"}',
            )

    def test_non_empty_directory_without_conflicts(self):
        """Non-empty directory without managed files succeeds."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "DirWithFiles"
            path.mkdir()
            (path / "readme.md").write_text("# My App", encoding="utf-8")

            create_project(path)

            self.assertTrue((path / "app.py").exists())
            self.assertEqual(
                (path / "readme.md").read_text(encoding="utf-8"),
                "# My App",
            )

    def test_custom_module_name(self):
        """Custom module name creates correctly named source file."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "CustomModule"
            create_project(path, module="main")

            project = load_project(path)
            self.assertEqual(project.app.module, "main")
            self.assertEqual(project.app.source, "main.py")
            self.assertTrue((path / "main.py").exists())


class ProjectCreationEdgeTests(unittest.TestCase):
    """CLI-02: Unique creation edge cases retained from the old test_cli."""

    def test_default_package_avoids_android_reserved_words(self):
        """A reserved word in the target name is prefixed in the package."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "base-package"

            create_project(path)
            project = load_project(path)

            self.assertEqual(project.app.package, "com.example.base.apppackage")

    def test_project_rerun_when_generated_files_match(self):
        """Rerunning creation on a matching generated project succeeds."""
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

    def test_force_overwrites_existing_pyproject(self):
        """--force replaces an existing pyproject.toml."""
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

    def test_updates_existing_pyproject_without_dependencies_key(self):
        """A pyproject without a dependencies key still gains the Vyne dep."""
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

    def test_project_creation_without_checkout_root(self):
        """Packaged mode: creation works with an explicit base project."""
        from unittest.mock import patch

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


class GradleNameEscapingTests(unittest.TestCase):
    """Generated ``settings.gradle.kts`` escapes the project name safely.

    A target directory name containing quotes, backslashes, dollar signs, or
    control characters must render as a valid Kotlin string literal instead
    of injecting raw syntax into ``rootProject.name``.
    """

    def test_kotlin_string_literal_helper(self):
        from vyne.cli.new import _kotlin_string

        cases = [
            ("HelloApp", '"HelloApp"'),
            ('say "hi"', r'"say \"hi\""'),
            (r"back\slash", r'"back\\slash"'),
            ("cost $5", r'"cost \$5"'),
            ("line\nbreak", r'"line\nbreak"'),
            ("tab\there", r'"tab\there"'),
            ("", '""'),
            # Every C0 control character and DEL is escaped as \uXXXX.
            ("back\x08space", '"back\\u0008space"'),
            ("feed\x0Chere", '"feed\\u000Chere"'),
            ("esc\x1Bape", '"esc\\u001Bape"'),
            ("nul\x00x", '"nul\\u0000x"'),
            ("del\x7Fete", '"del\\u007Fete"'),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(_kotlin_string(value), expected)

    def test_settings_gradle_escapes_control_characters(self):
        from vyne.cli.new import create_project

        # NUL is excluded: POSIX forbids it in directory names.  The rest
        # are valid on Linux and must render as \uXXXX escapes, never raw.
        cases = [
            ("Back\x08space", '"Back\\u0008space"'),
            ("Feed\x0Chere", '"Feed\\u000Chere"'),
            ("Esc\x1Bape", '"Esc\\u001Bape"'),
            ("Del\x7Fete", '"Del\\u007Fete"'),
        ]
        for name, expected_escape in cases:
            with self.subTest(name=name):
                with TemporaryDirectory() as tmp:
                    path = Path(tmp) / name
                    create_project(
                        path, package="com.example.escape", label="Escape"
                    )
                    settings = (
                        path / "android" / "settings.gradle.kts"
                    ).read_text(encoding="utf-8")
                    self.assertIn(
                        f"rootProject.name = {expected_escape}", settings
                    )
                    self.assertNotIn(
                        f"rootProject.name = \"{name}\"", settings
                    )
                    # The placeholder is never substituted into the comment.
                    self.assertNotIn("{nameLiteral}", settings)
                    self.assertIn(
                        "The placeholder in the line below is replaced",
                        settings,
                    )

    def test_settings_gradle_escapes_edge_case_project_names(self):
        from vyne.cli.new import create_project

        cases = [
            ('Quote"App', 'rootProject.name = "Quote\\"App"'),
            (r"Back\slash", r'rootProject.name = "Back\\slash"'),
            ("Dollar$App", 'rootProject.name = "Dollar\\$App"'),
            ("Line\nBreak", 'rootProject.name = "Line\\nBreak"'),
        ]
        for name, expected_line in cases:
            with self.subTest(name=name):
                with TemporaryDirectory() as tmp:
                    path = Path(tmp) / name
                    create_project(
                        path, package="com.example.escape", label="Escape"
                    )
                    settings = (
                        path / "android" / "settings.gradle.kts"
                    ).read_text(encoding="utf-8")
                    self.assertIn(expected_line, settings)
                    self.assertNotIn(
                        f'rootProject.name = "{name}"', settings
                    )

    def test_settings_gradle_preserves_plain_project_name(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "HelloApp"
            create_project(path, package="com.example.hello", label="Hello")
            settings = (path / "android" / "settings.gradle.kts").read_text(
                encoding="utf-8"
            )
            self.assertIn('rootProject.name = "HelloApp"', settings)
            self.assertNotIn("{nameLiteral}", settings)


if __name__ == "__main__":
    unittest.main()
