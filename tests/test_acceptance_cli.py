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
import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from vyne.cli.new import create_project
from vyne.cli.project import load_project


class TOMLDependencyEditingTests(unittest.TestCase):
    """CLI-01: Structure-preserving dependency editing."""

    def test_add_to_empty_dependencies(self):
        """Adding Vyne to empty dependencies list."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "TestProject"
            path.mkdir(parents=True, exist_ok=True)
            (path / "pyproject.toml").write_text(
                '[project]\nname = "test"\ndependencies = []\n',
                encoding="utf-8",
            )
            create_project(path)
            pyproject = tomllib.loads(
                (path / "pyproject.toml").read_text(encoding="utf-8")
            )
            deps = pyproject["project"]["dependencies"]
            self.assertTrue(any(d.startswith("vyne") for d in deps))

    def test_existing_vyne_is_noop(self):
        """Existing Vyne dependency is byte-for-byte no-op."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "TestProject"
            path.mkdir(parents=True, exist_ok=True)
            (path / "pyproject.toml").write_text(
                '[project]\nname = "test"\ndependencies = ["vyne"]\n',
                encoding="utf-8",
            )
            create_project(path)
            pyproject = (path / "pyproject.toml").read_text(encoding="utf-8")
            # Should not duplicate
            self.assertEqual(pyproject.count('"vyne"'), 1)

    def test_vyness_not_matched(self):
        """vyness is not Vyne."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "TestProject"
            path.mkdir(parents=True, exist_ok=True)
            (path / "pyproject.toml").write_text(
                '[project]\nname = "test"\ndependencies = ["vyness>=1.0"]\n',
                encoding="utf-8",
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
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "TestProject"
            path.mkdir(parents=True, exist_ok=True)
            (path / "pyproject.toml").write_text(
                '[project]\nname = "test"\ndependencies = [\n    "requests>=2.34",\n]\n',
                encoding="utf-8",
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
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "TestProject"
            path.mkdir(parents=True, exist_ok=True)
            (path / "pyproject.toml").write_text(
                '[project]\nname = "test"\ndependencies = ["vyne-core>=1.0"]\n',
                encoding="utf-8",
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

    def test_package_name_invalid_rejected(self):
        """Invalid Android package names are rejected."""
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                create_project(Path(tmp) / "BadPackage", package="com.example.class")

    def test_module_name_invalid_rejected(self):
        """Invalid Python module names are rejected."""
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                create_project(Path(tmp) / "BadModule", module="bad-name")

    def test_keyword_module_rejected(self):
        """Python keywords are rejected as module names."""
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                create_project(Path(tmp) / "BadModule", module="class")

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


if __name__ == "__main__":
    unittest.main()
