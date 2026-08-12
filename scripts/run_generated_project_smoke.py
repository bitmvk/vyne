#!/usr/bin/env python3
"""Truthful clean-room generated-project smoke gate."""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_gate(name: str, command: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 600) -> dict:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "name": name,
            "ok": False,
            "error": str(error),
        }
    return {
        "name": name,
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


def finish(gates: list[dict], work: Path) -> int:
    evidence = {
        "ok": all(gate.get("ok") is True for gate in gates),
        "gates": gates,
    }
    (work / "smoke-results.json").write_text(
        json.dumps(evidence, indent=2),
        encoding="utf-8",
    )
    for gate in gates:
        print(f"{gate['name']}: {'PASS' if gate.get('ok') else 'FAIL'}")
    return 0 if evidence["ok"] else 1


def find_aapt() -> str | None:
    android_home = Path(os.environ.get("ANDROID_HOME", "/opt/android-sdk"))
    candidates = sorted((android_home / "build-tools").glob("*/aapt"), reverse=True)
    return str(candidates[0]) if candidates else shutil.which("aapt")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--venv-root", required=True)
    parser.add_argument("--gradle-user-home", default="/tmp/vyne-gradle-home")
    parser.add_argument("--package", default="dev.vyne.smoke")
    parser.add_argument("--version-name", default="0.1.0")
    parser.add_argument("--version-code", type=int, default=1)
    parser.add_argument("--skip-android-build", action="store_true")
    args = parser.parse_args()

    work = Path(args.work_root).resolve()
    venv = Path(args.venv_root).resolve()
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(venv, ignore_errors=True)
    work.mkdir(parents=True)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    gates: list[dict] = []

    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    wheel_dir = work / "wheels"
    wheel_dir.mkdir()
    gates.append(run_gate(
        "repository-root-wheel",
        [str(venv / "bin/pip"), "wheel", "--no-deps", "--wheel-dir", str(wheel_dir), str(PROJECT_ROOT)],
        cwd=PROJECT_ROOT, env=env,
    ))
    wheels = list(wheel_dir.glob("*.whl"))
    if gates[-1]["ok"] and len(wheels) == 1:
        gates.append(run_gate("install-wheel", [str(venv / "bin/pip"), "install", str(wheels[0])], cwd=work, env=env))
    else:
        gates.append({"name": "install-wheel", "ok": False, "error": f"expected one wheel, got {wheels}"})
    if not gates[-1]["ok"]:
        return finish(gates, work)

    project = work / "project"
    gates.append(run_gate(
        "installed-cli-create",
        [str(venv / "bin/vyne"), "new", str(project), "--package", args.package, "--module", "app", "--label", "SmokeTest"],
        cwd=work, env=env,
    ))
    gates.append(run_gate(
        "generated-python-tests",
        [str(venv / "bin/python"), "-m", "unittest", "discover", "-s", "tests", "-t", "."],
        cwd=project, env={**env, "PYTHONPATH": str(project)},
    ))

    if args.skip_android_build:
        gates.append({"name": "android-build", "ok": False, "incomplete": True, "error": "required gate skipped"})
    else:
        gradlew = project / "android/gradlew"
        if gradlew.exists():
            gradlew.chmod(0o755)
        property_result = subprocess.run(
            [str(venv / "bin/python"), "-c",
             "import json; from vyne.cli.project import load_project; print(json.dumps(load_project().gradle_properties()))"],
            cwd=project, env=env, text=True, capture_output=True,
        )
        properties = json.loads(property_result.stdout) if property_result.returncode == 0 else []
        if property_result.returncode != 0:
            gates.append({"name": "resolve-gradle-properties", "ok": False,
                          "stderr": property_result.stderr[-4000:]})
        gradle = [str(gradlew), "--gradle-user-home", args.gradle_user_home, "--no-daemon"]
        gates.append(run_gate("gradle-projects", gradle + ["projects", *properties], cwd=project / "android", env=env))
        gates.append(run_gate("generated-app-tests", gradle + [":app:testDebugUnitTest", *properties], cwd=project / "android", env=env))
        gates.append(run_gate("assemble-debug", gradle + [":app:assembleDebug", *properties], cwd=project / "android", env=env))

        apks = list((project / "android/app/build/outputs/apk/debug").glob("*.apk"))
        metadata = {"name": "apk-metadata", "ok": False}
        if len(apks) == 1:
            apk = apks[0]
            with zipfile.ZipFile(apk) as archive:
                names = set(archive.namelist())
                app_archive = "assets/chaquopy/app.imy"
                if app_archive in names:
                    with zipfile.ZipFile(
                        io.BytesIO(archive.read(app_archive))
                    ) as python_archive:
                        python_names = set(python_archive.namelist())
                else:
                    python_names = set()
            has_python = (
                "app.pyc" in python_names
                and any(name.startswith("vyne/") for name in python_names)
            )
            abi_set = {name.split("/")[1] for name in names if name.startswith("lib/") and name.count("/") >= 2}
            aapt = find_aapt()
            badging = ""
            if aapt:
                proc = subprocess.run([aapt, "dump", "badging", str(apk)], text=True, capture_output=True)
                badging = proc.stdout if proc.returncode == 0 else ""
            metadata.update({
                "ok": has_python and bool(abi_set) and
                      f"package: name='{args.package}'" in badging and
                      f"versionCode='{args.version_code}'" in badging and
                      f"versionName='{args.version_name}'" in badging,
                "apk": str(apk), "abis": sorted(abi_set), "badging": badging[:2000],
                "has_python": has_python,
            })
        gates.append(metadata)

    # ── Extension flow through the installed CLI ─────────────────────────
    # Copy the example extension into the generated project, run the
    # installed `vyne build` (discovery + registrant generation), and verify
    # the generated Kotlin registrant, then assemble.
    ext_src = PROJECT_ROOT / "examples" / "extensions" / "timer_ring"
    ext_dst = project / "extensions" / "timer_ring"
    if not args.skip_android_build and ext_src.is_dir():
        shutil.copytree(ext_src, ext_dst)
        gates.append(run_gate(
            "extension-build",
            [str(venv / "bin/vyne"), "build"],
            cwd=project, env=env,
        ))
        registrant = (
            project / "android" / "app" / "src" / "main" / "java"
            / "dev" / "vyne" / "generated" / "ExtensionRegistrant.kt"
        )
        registrant_ok = (
            registrant.is_file() and
            "TimerRingExtension.register" in registrant.read_text(encoding="utf-8")
        )
        gates.append({
            "name": "extension-generated-wiring",
            "ok": registrant_ok,
            "registrant_ok": registrant_ok,
        })

    return finish(gates, work)


if __name__ == "__main__":
    raise SystemExit(main())
