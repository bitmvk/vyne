from __future__ import annotations

from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py


ROOT = Path(__file__).parent.resolve()


class BuildPy(build_py):
    def run(self) -> None:
        super().run()
        self._copy_base_project()

    def _copy_base_project(self) -> None:
        target = Path(self.build_lib) / "vyne" / "base_project"
        if target.exists():
            shutil.rmtree(target)

        self._copy_file(ROOT / "android" / "gradlew", target / "gradlew")
        self._copy_file(ROOT / "android" / "gradlew.bat", target / "gradlew.bat")
        self._copy_tree(
            ROOT / "android" / "gradle" / "wrapper",
            target / "gradle" / "wrapper",
        )

        self._copy_tree(
            ROOT / "android" / "host" / "src" / "main",
            target / "android-host" / "src" / "main",
        )
    def _copy_file(self, source: Path, destination: Path) -> None:
        if not source.is_file():
            raise RuntimeError(f"Missing package asset: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    def _copy_tree(self, source: Path, destination: Path) -> None:
        if not source.is_dir():
            raise RuntimeError(f"Missing package asset directory: {source}")
        shutil.copytree(source, destination, ignore=self._ignore)

    def _ignore(self, _directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in {"__pycache__", "build", ".cxx", ".gradle"}
            # The registrant is generated per-project into the app module;
            # the packaged host default must not compile there too.
            or name == "ExtensionRegistrant.kt"
            or name.endswith((".pyc", ".pyo"))
        }


setup(cmdclass={"build_py": BuildPy})
