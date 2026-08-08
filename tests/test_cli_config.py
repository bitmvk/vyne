"""Tests for ``vyne.cli.config`` — validated project configuration parsing.

Coverage:
- Exact config types (bool rejection, table shape, required fields)
- Package/module validation (ASCII, segments, identifiers)
- SDK ordering/bounds
- PEP 440 version validation
- Config-relative path resolution
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from vyne.cli.config import parse_config


class ConfigValidationTests(unittest.TestCase):
    """CLI-02 config validation."""

    def _cfg_path(self, tmp: str) -> Path:
        return Path(tmp) / "vyne.toml"

    def _minimal_raw(self):
        return {
            "app": {
                "name": "TestApp",
                "label": "Test App",
                "package": "com.example.test",
                "module": "app",
                "source": "app.py",
                "version": "0.1.0",
                "version_code": 1,
            },
            "android": {
                "min_sdk": 26,
                "target_sdk": 35,
                "compile_sdk": 35,
            },
        }

    # -- happy path ---------------------------------------------------------

    def test_valid_config_parses(self):
        with TemporaryDirectory() as tmp:
            cfg_path = self._cfg_path(tmp)
            # Create the required path directories
            for sub in ["site-packages", "base_project"]:
                (Path(tmp) / sub).mkdir(parents=True, exist_ok=True)
            raw = {
                **self._minimal_raw(),
                "paths": {
                    "package_python_dir": "site-packages",
                    "base_project_root": "base_project",
                },
            }
            cfg = parse_config(raw, config_path=cfg_path)
            self.assertEqual(cfg.app.name, "TestApp")
            self.assertEqual(cfg.app.package, "com.example.test")
            self.assertEqual(cfg.android.min_sdk, 26)

    # -- type enforcement ---------------------------------------------------

    def test_rejects_bool_as_int_for_min_sdk(self):
        raw = self._minimal_raw()
        raw["android"]["min_sdk"] = True  # type: ignore
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                parse_config(raw, config_path=self._cfg_path(tmp))
            self.assertIn("integer", str(ctx.exception))

    def test_rejects_bool_as_int_for_version_code(self):
        raw = self._minimal_raw()
        raw["app"]["version_code"] = True  # type: ignore
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                parse_config(raw, config_path=self._cfg_path(tmp))
            self.assertIn("integer", str(ctx.exception))

    def test_rejects_string_as_table(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                parse_config(
                    {"app": "not-a-table"},
                    config_path=self._cfg_path(tmp),
                )
            self.assertIn("table", str(ctx.exception))

    def test_rejects_invalid_section_top_level(self):
        with TemporaryDirectory() as tmp:
            # Top-level "android" as a string instead of table
            raw = {**self._minimal_raw(), "android": "bad"}
            with self.assertRaises(RuntimeError):
                parse_config(raw, config_path=self._cfg_path(tmp))

    # -- SDK ordering -------------------------------------------------------

    def test_rejects_min_sdk_below_26(self):
        raw = self._minimal_raw()
        raw["android"]["min_sdk"] = 21
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                parse_config(raw, config_path=self._cfg_path(tmp))
            self.assertIn("min_sdk", str(ctx.exception))

    def test_rejects_target_sdk_less_than_min_sdk(self):
        raw = self._minimal_raw()
        raw["android"]["target_sdk"] = 24
        raw["android"]["min_sdk"] = 26
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                parse_config(raw, config_path=self._cfg_path(tmp))
            self.assertIn("ordering", str(ctx.exception))

    def test_rejects_compile_sdk_less_than_target_sdk(self):
        raw = self._minimal_raw()
        raw["android"]["target_sdk"] = 35
        raw["android"]["compile_sdk"] = 33
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                parse_config(raw, config_path=self._cfg_path(tmp))
            self.assertIn("ordering", str(ctx.exception))

    # -- package validation -------------------------------------------------

    def test_rejects_invalid_package_unicode(self):
        raw = self._minimal_raw()
        raw["app"]["package"] = "com.exämple.app"
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                parse_config(raw, config_path=self._cfg_path(tmp))
            self.assertIn("package", str(ctx.exception))

    def test_rejects_single_segment_package(self):
        raw = self._minimal_raw()
        raw["app"]["package"] = "nopackage"
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                parse_config(raw, config_path=self._cfg_path(tmp))
            self.assertIn("package", str(ctx.exception))

    def test_rejects_leading_underscore_package(self):
        raw = self._minimal_raw()
        raw["app"]["package"] = "com._bad.app"
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                parse_config(raw, config_path=self._cfg_path(tmp))
            self.assertIn("package", str(ctx.exception))

    # -- module validation --------------------------------------------------

    def test_rejects_invalid_module(self):
        raw = self._minimal_raw()
        raw["app"]["module"] = "bad-module"
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                parse_config(raw, config_path=self._cfg_path(tmp))
            self.assertIn("module", str(ctx.exception))

    # -- version validation -------------------------------------------------

    def test_rejects_invalid_pep440_version(self):
        raw = self._minimal_raw()
        raw["app"]["version"] = "not-a-version"
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                parse_config(raw, config_path=self._cfg_path(tmp))
            self.assertIn("PEP 440", str(ctx.exception))

    def test_accepts_pep440_pre_release_version(self):
        raw = self._minimal_raw()
        raw["app"]["version"] = "0.1.0a1"
        with TemporaryDirectory() as tmp:
            for sub in ["site-packages", "base_project"]:
                (Path(tmp) / sub).mkdir(parents=True, exist_ok=True)
            raw["paths"] = {
                "package_python_dir": "site-packages",
                "base_project_root": "base_project",
            }
            cfg = parse_config(raw, config_path=self._cfg_path(tmp))
            self.assertEqual(cfg.app.version, "0.1.0a1")

    def test_negative_version_code_rejects(self):
        raw = self._minimal_raw()
        raw["app"]["version_code"] = 0
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                parse_config(raw, config_path=self._cfg_path(tmp))
            self.assertIn("version_code", str(ctx.exception))

    # -- path resolution ----------------------------------------------------

    def test_relative_path_resolves_from_config_dir(self):
        with TemporaryDirectory() as tmp:
            cfg_path = self._cfg_path(tmp)
            (Path(tmp) / "my-site-packages").mkdir()
            (Path(tmp) / "my-base").mkdir()
            raw = {
                **self._minimal_raw(),
                "paths": {
                    "package_python_dir": "my-site-packages",
                    "base_project_root": "my-base",
                },
            }
            cfg = parse_config(raw, config_path=cfg_path)
            self.assertEqual(
                cfg.paths.package_python_dir,
                (Path(tmp) / "my-site-packages").resolve(),
            )

    def test_rejects_missing_path(self):
        with TemporaryDirectory() as tmp:
            raw = {
                **self._minimal_raw(),
                "paths": {
                    "package_python_dir": "nonexistent",
                    "base_project_root": "nonexistent2",
                },
            }
            with self.assertRaises(RuntimeError):
                parse_config(raw, config_path=self._cfg_path(tmp))

    def test_rejects_missing_required_path_key(self):
        raw = self._minimal_raw()
        raw["paths"] = {}
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                parse_config(raw, config_path=self._cfg_path(tmp))
            self.assertIn("required", str(ctx.exception))

    # -- version_code default -----------------------------------------------

    def test_default_version_code_is_one(self):
        with TemporaryDirectory() as tmp:
            for sub in ["site-packages", "base_project"]:
                (Path(tmp) / sub).mkdir(parents=True, exist_ok=True)
            raw = {
                **self._minimal_raw(),
                "paths": {
                    "package_python_dir": "site-packages",
                    "base_project_root": "base_project",
                },
            }
            del raw["app"]["version_code"]
            cfg = parse_config(raw, config_path=self._cfg_path(tmp))
            self.assertEqual(cfg.app.version_code, 1)


if __name__ == "__main__":
    unittest.main()
