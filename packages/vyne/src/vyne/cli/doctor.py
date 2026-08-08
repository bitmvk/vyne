"""Environment diagnostics for Vyne projects.

'vyne doctor' checks that all required tools and paths are present:
- Python >= 3.12, uv, Java, adb
- Valid project config and directory structure
- Android host sources and resources
- Optionally, an authorized adb device (--device flag)

Each check produces a name/ok/detail triple, displayed as a compact table.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import subprocess
import sys

from vyne.cli.project import Project, ProjectInspection, ProjectRepository


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def run_doctor(project: Project | None = None, *, require_device: bool = False) -> int:
    if project is not None:
        inspection = ProjectInspection(project=project, issues=(), extensions=())
    else:
        # Never crash on expected failures: the inspection carries them as
        # stable issues (design-pattern #10).
        inspection = ProjectRepository().inspect()
    checks = _checks(inspection, require_device=require_device)
    if not checks:
        return 1
    width = max(len(check.name) for check in checks)
    for check in checks:
        status = "ok" if check.ok else "missing"
        print(f"{check.name.ljust(width)}  {status}  {check.detail}")
    return 0 if all(check.ok for check in checks) else 1


def _checks(inspection: ProjectInspection, *, require_device: bool) -> list[Check]:
    project = inspection.project
    if project is None:
        return [
            Check(name=issue.code, ok=False, detail=issue.detail)
            for issue in inspection.issues
        ]
    checks = [
        Check("project", project.root.is_dir(), str(project.root)),
        Check(
            "config",
            project.config_path is None or project.config_path.is_file(),
            str(project.config_path or "framework checkout"),
        ),
        Check("python", sys.version_info >= (3, 12), sys.version.split()[0]),
        _command("uv"),
        _command("java"),
        _command("adb"),
        Check("android project", project.android_dir.is_dir(), str(project.android_dir)),
        Check(
            "gradlew",
            project.gradlew.is_file() and os.access(project.gradlew, os.X_OK),
            str(project.gradlew),
        ),
        Check("app source", project.app_source.is_file(), str(project.app_source)),
        Check(
            "package python",
            project.framework_python_dir.is_dir(),
            str(project.framework_python_dir),
        ),
        Check("base project", project.base_project_root.is_dir(), str(project.base_project_root)),
        Check("host sources", project.host_source_dir.is_dir(), str(project.host_source_dir)),
        Check("host resources", project.host_res_dir.is_dir(), str(project.host_res_dir)),
    ]
    if require_device:
        checks.append(_adb_device())

    if inspection.issues:
        return checks + [
            Check(name=issue.code, ok=False, detail=issue.detail)
            for issue in inspection.issues
        ]
    extensions = inspection.extensions
    if extensions:
        checks.append(
            Check(
                name="extensions",
                ok=True,
                detail=", ".join(
                    f"{ext.name}@{ext.kotlin_dir.name}" for ext in extensions
                ),
            )
        )
    else:
        checks.append(Check(name="extensions", ok=True, detail="none"))
    return checks


def _command(name: str) -> Check:
    path = shutil.which(name)
    return Check(name, path is not None, path or "not found on PATH")


def _adb_device() -> Check:
    if shutil.which("adb") is None:
        return Check("adb device", False, "adb not found on PATH")
    try:
        result = subprocess.run(["adb", "devices"], text=True, capture_output=True, check=True)
    except subprocess.CalledProcessError as error:
        return Check("adb device", False, error.stderr.strip() or "adb devices failed")
    has_device = "\tdevice" in result.stdout
    detail = "authorized device" if has_device else "no authorized device"
    return Check("adb device", has_device, detail)
