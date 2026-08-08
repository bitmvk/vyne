"""Android build, install, and launch commands.

Each command delegates to Gradle and/or adb.  The project is auto-discovered
via ``load_project()`` if not explicitly passed, so these commands work from
any subdirectory of a Vyne project.
"""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import sys

from vyne.cli.project import Project, load_project
from vyne.cli.extensions import discover_extensions, generate_extension_files


def build_project(project: Project | None = None) -> Path:
    project = project or load_project()
    _ensure_android_ready(project)
    project = _generate_extensions(project)
    _run_gradle(project, project.assemble_task)
    return project.apk_path


def _generate_extensions(project: Project) -> Project:
    """Regenerate the extension registrant and Python bootstrap module.

    Runs before every Gradle build so Kotlin and Python wiring always
    reflect the current ``extensions/`` contents — including the empty
    state after extensions are removed (stale generated files must never
    survive). Journaled and byte-identical-skip, so unchanged projects
    produce zero churn. The SAME discovery result is published back into
    the project so Gradle properties and generation can never disagree.
    """
    from dataclasses import replace

    extensions = discover_extensions(project.root)
    generate_extension_files(project, extensions)
    return replace(project, extensions=tuple(extensions))


def install_project(project: Project | None = None) -> Path:
    project = project or load_project()
    apk = build_project(project)
    _ensure_adb_device()
    subprocess.run(["adb", "install", "-r", str(apk)], check=True)
    return apk


def run_project(project: Project | None = None) -> Path:
    project = project or load_project()
    apk = install_project(project)
    subprocess.run(["adb", "shell", "am", "start", "-n", project.main_activity], check=True)
    return apk


def launch_project(project: Project | None = None) -> None:
    project = project or load_project()
    _ensure_adb_device()
    subprocess.run(["adb", "shell", "am", "start", "-n", project.main_activity], check=True)


def test_project(project: Project | None = None) -> None:
    project = project or load_project()
    tests_dir = project.root / "tests"
    if not tests_dir.is_dir():
        print(f"No tests directory found at {tests_dir}")
        return
    subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(tests_dir)],
        cwd=project.root,
        check=True,
    )


def _run_gradle(project: Project, task: str) -> None:
    env = os.environ.copy()
    env.setdefault("GRADLE_USER_HOME", "/tmp/gradle-home")
    command = [str(project.gradlew), task, *project.gradle_properties()]
    subprocess.run(command, cwd=project.android_dir, env=env, check=True)


def _ensure_android_ready(project: Project) -> None:
    if not project.gradlew.is_file():
        raise RuntimeError(f"Missing Gradle wrapper: {project.gradlew}")
    if not os.access(project.gradlew, os.X_OK):
        raise RuntimeError(f"Gradle wrapper is not executable: {project.gradlew}")
    if not project.app_source.is_file():
        raise RuntimeError(f"Missing app source: {project.app_source}")
    if not project.framework_python_dir.is_dir():
        raise RuntimeError(f"Missing framework Python package: {project.framework_python_dir}")
    if not project.host_source_dir.is_dir():
        raise RuntimeError(f"Missing Android host sources: {project.host_source_dir}")


def _ensure_adb_device() -> None:
    if shutil.which("adb") is None:
        raise RuntimeError("adb was not found on PATH")
    result = subprocess.run(["adb", "devices"], check=True, text=True, capture_output=True)
    if "\tdevice" not in result.stdout:
        raise RuntimeError("No authorized adb device found")
