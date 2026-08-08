"""CLI policy roundtrip tests (CLI-02, TL-3).

Verify that ``create_project`` and ``load_project`` accept/reject the same:
- Package names
- Versions
- SDK values
- Paths

Generated config is re-parsed before placement, so create+load must agree.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from vyne.cli.new import create_project
from vyne.cli.project import load_project


class ConfigRoundtripTests(unittest.TestCase):
    """TL-3: Config roundtrip through create_project and load_project."""

    def test_roundtrip_default_config(self):
        """Default generated config roundtrips through create/load."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "RoundtripDefault"
            create_project(path, package="com.example.roundtrip", label="Roundtrip")
            project = load_project(path)
            self.assertEqual(project.app.package, "com.example.roundtrip")
            self.assertEqual(project.app.label, "Roundtrip")
            self.assertEqual(project.app.module, "app")
            self.assertEqual(project.app.source, "app.py")
            self.assertEqual(project.app.version, "0.1.0")
            self.assertEqual(project.app.version_code, 1)
            self.assertEqual(project.android.min_sdk, 26)
            self.assertEqual(project.android.target_sdk, 35)
            self.assertEqual(project.android.compile_sdk, 35)
            self.assertEqual(project.generated, True)
            self.assertIsNotNone(project.config_path)
            self.assertEqual(project.config_path, path / "vyne.toml")

    def test_roundtrip_custom_module(self):
        """Custom module name survives create/load roundtrip."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "RoundtripModule"
            create_project(path, package="com.example.mainapp", module="main")
            project = load_project(path)
            self.assertEqual(project.app.module, "main")
            self.assertEqual(project.app.source, "main.py")
            self.assertTrue((path / "main.py").is_file())

    def test_roundtrip_with_force(self):
        """Force creation still produces valid config."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "RoundtripForce"
            path.mkdir()
            create_project(path, package="com.example.force", force=True)
            project = load_project(path)
            self.assertEqual(project.app.package, "com.example.force")

    def test_rejects_version_code_zero(self):
        """Version code 0 is rejected (must be >= 1)."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "BadVersionCode"
            path.mkdir()
            # Write a bad config that will fail parse_config during create
            (path / "vyne.toml").write_text(
                '[app]\nname = "test"\npackage = "com.example.bad"\n'
                'module = "app"\nsource = "app.py"\nversion = "0.1.0"\n'
                'version_code = 0\n\n'
                '[android]\nmin_sdk = 26\ntarget_sdk = 35\ncompile_sdk = 35\n',
                encoding="utf-8",
            )

    def test_rejects_version_code_too_large(self):
        """Version code > 2_100_000_000 is rejected."""
        from vyne.cli.config import parse_config
        with TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "vyne.toml"
            raw = {
                "app": {
                    "name": "TestApp",
                    "label": "Test",
                    "package": "com.example.test",
                    "module": "app",
                    "source": "app.py",
                    "version": "0.1.0",
                    "version_code": 2_200_000_000,
                },
                "android": {
                    "min_sdk": 26,
                    "target_sdk": 35,
                    "compile_sdk": 35,
                },
            }
            with self.assertRaises(RuntimeError) as ctx:
                parse_config(raw, config_path=cfg_path)
            self.assertIn("2_100_000_000", str(ctx.exception).replace(",", ""))

    def test_load_after_create_builds_correct_gradle_properties(self):
        """The Gradle -P properties from a loaded project are well-formed."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "GradleProps"
            create_project(path, package="com.example.gradle", label="Gradle Test")
            project = load_project(path)

            props = project.gradle_properties()
            self.assertIn("-Pvyne.applicationId=com.example.gradle", props)
            self.assertIn("-Pvyne.appLabel=Gradle Test", props)
            self.assertIn("-Pvyne.appModule=app", props)
            self.assertIn("-Pvyne.minSdk=26", props)
            self.assertIn("-Pvyne.targetSdk=35", props)
            self.assertIn("-Pvyne.compileSdk=35", props)
            self.assertIn("-Pvyne.versionName=0.1.0", props)
            self.assertIn("-Pvyne.versionCode=1", props)

    def test_project_identity_paths_resolve(self):
        """All project paths resolve to existing directories after creation."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "PathsResolve"
            create_project(path, package="com.example.paths", label="Paths")
            project = load_project(path)

            # Paths from the generated config should exist
            self.assertTrue(project.package_python_dir.exists(),
                            f"package_python_dir {project.package_python_dir} does not exist")
            self.assertTrue(project.base_project_root.exists(),
                            f"base_project_root {project.base_project_root} does not exist")

    def test_create_then_load_determines_generated_mode(self):
        """Generated projects must set generated=True."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "Generated"
            create_project(path, package="com.example.gen", label="Gen")
            project = load_project(path)
            self.assertTrue(project.generated)
            self.assertEqual(project.assemble_task, ":app:assembleDebug")

    def test_both_accept_same_min_sdk(self):
        """create_project and load_project accept the same min_sdk."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "MinSdk26"
            create_project(path, package="com.example.minsdk")
            project = load_project(path)
            self.assertEqual(project.android.min_sdk, 26)

if __name__ == "__main__":
    unittest.main()
