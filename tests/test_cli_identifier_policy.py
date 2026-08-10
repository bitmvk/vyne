"""Shared CLI identifier policy tests (CLI-02, TL-3).

Verifies that ``parse_config``, ``vyne new``, and extension scaffolding
apply exactly one reserved-word/identifier policy, so no CLI path accepts
a package, module, or name another path rejects.

The policy is deliberately stricter than before this alpha cleanup:
reserved words are now rejected at config load time (not only in ``vyne
new``) and extension names are ASCII-only.  These tests pin that
intentional tightening.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from vyne.cli.config import (
    is_reserved_identifier,
    parse_config,
    validate_module,
    validate_package,
)


class ReservedIdentifierPolicyTests(unittest.TestCase):
    """The single reserved-word set covers Python and Android/Kotlin."""

    def test_python_keywords_are_reserved(self):
        for name in ("class", "def", "import", "from", "while", "lambda"):
            self.assertTrue(is_reserved_identifier(name), name)

    def test_android_java_keywords_are_reserved(self):
        for name in ("package", "public", "void", "static", "extends"):
            self.assertTrue(is_reserved_identifier(name), name)

    def test_kotlin_keywords_are_reserved(self):
        for name in ("val", "var", "fun", "when", "object", "is"):
            self.assertTrue(is_reserved_identifier(name), name)

    def test_plain_identifiers_are_not_reserved(self):
        for name in ("app", "main", "timer_ring", "myapp", "Vy"):
            self.assertFalse(is_reserved_identifier(name), name)


class PackagePolicyTests(unittest.TestCase):
    """One package policy across config parsing and project creation."""

    VALID = (
        "com.example.app",
        "dev.vyne",
        "com.example.my_app",
        "io.github.user.project",
    )
    INVALID = (
        "com.example.class",
        "com.package.app",
        "nopackage",
        "com..app",
        "com.exämple.app",
        "com.example.",
        # Android package segments must start with an ASCII letter.
        "com._bad.app",
    )

    def test_valid_packages_accepted(self):
        for package in self.VALID:
            validate_package(package)  # must not raise

    def test_invalid_packages_rejected_by_validate_package(self):
        for package in self.INVALID:
            with self.assertRaises(RuntimeError, msg=package):
                validate_package(package)

    def test_parse_config_rejects_reserved_package(self):
        with TemporaryDirectory() as tmp:
            raw = self._minimal_raw(package="com.example.class")
            with self.assertRaisesRegex(RuntimeError, "reserved"):
                parse_config(raw, config_path=Path(tmp) / "vyne.toml")

    def test_parse_config_rejects_underscore_leading_package_segment(self):
        with TemporaryDirectory() as tmp:
            raw = self._minimal_raw(package="com._bad.app")
            with self.assertRaisesRegex(RuntimeError, "ASCII letter"):
                parse_config(raw, config_path=Path(tmp) / "vyne.toml")

    def test_create_project_rejects_reserved_package(self):
        from vyne.cli.new import create_project
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "reserved"):
                create_project(
                    Path(tmp) / "App", package="com.example.class"
                )

    def test_create_project_rejects_reserved_default_package_segment(self):
        # A target whose derived default package contains a reserved word
        # must be repaired by prefixing, never emitted invalid.
        from vyne.cli.new import _default_package
        self.assertEqual(
            _default_package("my-class"), "com.example.my.appclass"
        )
        validate_package(_default_package("my-class"))

    def test_default_package_of_plain_name_is_valid(self):
        from vyne.cli.new import _default_package
        validate_package(_default_package("base-package"))

    def _minimal_raw(self, package: str):
        return {
            "app": {
                "name": "TestApp",
                "label": "Test App",
                "package": package,
                "module": "app",
                "source": "app.py",
                "version": "0.1.0",
                "version_code": 1,
            },
            "android": {"min_sdk": 26, "target_sdk": 35, "compile_sdk": 35},
        }


class ModulePolicyTests(unittest.TestCase):
    """One module policy across config parsing, creation, and extensions."""

    def test_valid_modules_accepted(self):
        for module in ("app", "main", "timer_ring"):
            validate_module(module)

    def test_underscore_leading_module_accepted(self):
        """Python module names may start with an underscore.

        Android package segments must start with a letter, but module names
        are ordinary Python identifiers and may be private-style.
        """
        for module in ("_private", "__init__", "_app"):
            validate_module(module)

    def test_reserved_and_invalid_modules_rejected(self):
        for module in ("class", "package", "val", "bad-name", "3app"):
            with self.assertRaises(RuntimeError, msg=module):
                validate_module(module)

    def test_parse_config_rejects_reserved_module(self):
        with TemporaryDirectory() as tmp:
            raw = {
                "app": {
                    "name": "TestApp",
                    "package": "com.example.app",
                    "module": "class",
                    "source": "class.py",
                    "version": "0.1.0",
                    "version_code": 1,
                },
                "android": {"min_sdk": 26, "target_sdk": 35, "compile_sdk": 35},
            }
            with self.assertRaisesRegex(RuntimeError, "module"):
                parse_config(raw, config_path=Path(tmp) / "vyne.toml")

    def test_create_project_rejects_reserved_module(self):
        from vyne.cli.new import create_project
        for module in ("class", "val"):
            with TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(RuntimeError, "valid Python identifier"):
                    create_project(Path(tmp) / "App", module=module)

    def test_extension_scaffolding_rejects_reserved_names(self):
        from vyne.cli.extension_new import create_extension
        with TemporaryDirectory() as tmp:
            for name in ("class", "val", "package"):
                with self.assertRaisesRegex(RuntimeError, "valid Python identifier"):
                    create_extension(Path(tmp), name)

    def test_extension_discovery_rejects_reserved_dir_name(self):
        from vyne.cli.extensions import discover_extensions
        with TemporaryDirectory() as tmp:
            ext_dir = Path(tmp) / "extensions" / "class"
            (ext_dir / "python").mkdir(parents=True)
            (ext_dir / "android").mkdir()
            (ext_dir / "python" / "class.py").write_text("", encoding="utf-8")
            (ext_dir / "extension.toml").write_text(
                'android_register = "dev.vyne.ext.cls.ClsExtension"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "valid Python identifier"):
                discover_extensions(Path(tmp))


class ParseConfigPathPolicyTests(unittest.TestCase):
    """Generation preflight and loading share parse_config's validation."""

    def test_check_paths_false_skips_existence(self):
        """check_paths=False validates structure but not path existence."""
        with TemporaryDirectory() as tmp:
            raw = {
                "app": {
                    "name": "TestApp",
                    "package": "com.example.app",
                    "module": "app",
                    "source": "app.py",
                    "version": "0.1.0",
                    "version_code": 1,
                },
                "android": {"min_sdk": 26, "target_sdk": 35, "compile_sdk": 35},
                "paths": {
                    "package_python_dir": "site-packages",
                    "base_project_root": "base_project",
                },
            }
            cfg = parse_config(
                raw,
                config_path=Path(tmp) / "vyne.toml",
                check_paths=False,
            )
            self.assertEqual(cfg.app.package, "com.example.app")
            self.assertEqual(
                cfg.paths.package_python_dir,
                (Path(tmp) / "site-packages").resolve(),
            )

    def test_check_paths_true_still_requires_existence(self):
        with TemporaryDirectory() as tmp:
            raw = {
                "app": {
                    "name": "TestApp",
                    "package": "com.example.app",
                    "module": "app",
                    "source": "app.py",
                    "version": "0.1.0",
                    "version_code": 1,
                },
                "android": {"min_sdk": 26, "target_sdk": 35, "compile_sdk": 35},
                "paths": {
                    "package_python_dir": "site-packages",
                    "base_project_root": "base_project",
                },
            }
            with self.assertRaises(RuntimeError):
                parse_config(raw, config_path=Path(tmp) / "vyne.toml")


if __name__ == "__main__":
    unittest.main()
