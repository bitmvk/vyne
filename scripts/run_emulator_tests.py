#!/usr/bin/env python3
"""Run Vyne's framework acceptance suite on a tester-supplied emulator.

The script deliberately does not create, start, or delete an emulator.  It
selects an already-online device, pins Gradle to that serial, packages the
dedicated Python acceptance app, runs instrumentation, and writes a compact
JSON evidence file.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANDROID_ROOT = PROJECT_ROOT / "android"
TEST_APP = (
    ANDROID_ROOT
    / "host"
    / "src"
    / "androidTest"
    / "python"
    / "vyne_emulator_app.py"
)
DEFAULT_EVIDENCE = PROJECT_ROOT / "build" / "emulator-test-results.json"


def adb(
    adb_path: str,
    arguments: list[str],
    *,
    serial: str | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    command = [adb_path]
    if serial is not None:
        command += ["-s", serial]
    command += arguments
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def online_devices(output: str) -> list[tuple[str, str]]:
    """Return ``(serial, description)`` for ready adb devices."""
    devices: list[tuple[str, str]] = []
    for raw_line in output.splitlines()[1:]:
        line = raw_line.strip()
        if not line or line.startswith("*"):
            continue
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "device":
            devices.append((fields[0], " ".join(fields[2:])))
    return devices


def select_serial(
    devices: list[tuple[str, str]],
    requested: str | None,
    *,
    allow_physical: bool,
) -> str:
    available = {serial for serial, _ in devices}
    if requested is not None:
        if requested not in available:
            raise RuntimeError(
                f"Requested device {requested!r} is not online; "
                f"available devices: {sorted(available)!r}"
            )
        selected = requested
    elif len(devices) == 1:
        selected = devices[0][0]
    elif not devices:
        raise RuntimeError(
            "No online adb device found. Start an emulator first and rerun."
        )
    else:
        raise RuntimeError(
            "Multiple adb devices are online; pass --serial explicitly: "
            + ", ".join(sorted(available))
        )
    if not allow_physical and not selected.startswith("emulator-"):
        raise RuntimeError(
            f"{selected!r} does not look like an emulator serial; "
            "pass --allow-physical to opt into a real device"
        )
    return selected


def getprop(adb_path: str, serial: str, name: str) -> str:
    result = adb(adb_path, ["shell", "getprop", name], serial=serial)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def instrumentation_counts(
    results_root: Path,
    *,
    since: float | None = None,
) -> dict[str, int]:
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for result_file in results_root.rglob("TEST-*.xml"):
        if since is not None and result_file.stat().st_mtime < since:
            continue
        text = result_file.read_text(encoding="utf-8", errors="replace")
        suite = re.search(r"<testsuite(?:\s|>)([^>]*)>", text)
        if suite is None:
            continue
        attributes = dict(re.findall(r'(\w+)="(\d+)"', suite.group(1)))
        for name in counts:
            counts[name] += int(attributes.get(name, "0"))
    return counts


def test_class_argument(test_classes: list[str]) -> str | None:
    if not test_classes:
        return None
    return (
        "-Pandroid.testInstrumentationRunnerArguments.class="
        + ",".join(test_classes)
    )


def run_succeeded(returncode: int, counts: dict[str, int]) -> bool:
    return (
        returncode == 0
        and counts["tests"] > 0
        and counts["failures"] == 0
        and counts["errors"] == 0
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    listed = adb(args.adb, ["devices", "-l"])
    if listed.returncode != 0:
        raise RuntimeError(
            "adb devices failed. The tester must start adb and an emulator "
            f"before this runner.\n{listed.stderr.strip()}"
        )
    devices = online_devices(listed.stdout)
    serial = select_serial(
        devices,
        args.serial,
        allow_physical=args.allow_physical,
    )
    state = adb(args.adb, ["get-state"], serial=serial)
    if state.returncode != 0 or state.stdout.strip() != "device":
        raise RuntimeError(f"Device {serial!r} is not ready")

    device = {
        "serial": serial,
        "api": getprop(args.adb, serial, "ro.build.version.sdk"),
        "abi": getprop(args.adb, serial, "ro.product.cpu.abi"),
        "model": getprop(args.adb, serial, "ro.product.model"),
    }
    # Root-level extensions are compiled into the host (the generated
    # registrant references them), so their source dirs must be on the
    # compile path for the suite to build. The notification-entry example
    # extension is also required: its Kotlin helper and Python module are
    # exercised by the instrumentation suite.
    extension_kotlin_dirs = [
        PROJECT_ROOT / "examples" / "extensions" / "notification_entry" / "android",
    ]
    extension_python_dirs = [
        PROJECT_ROOT / "examples" / "extensions" / "notification_entry" / "python",
    ]
    try:
        from vyne.cli.extensions import discover_extensions
        for extension in discover_extensions(PROJECT_ROOT):
            extension_kotlin_dirs.append(extension.kotlin_dir)
            extension_python_dirs.append(extension.python_dir)
    except ImportError:
        pass
    command = [
        str(ANDROID_ROOT / "gradlew"),
        "--gradle-user-home",
        str(Path(args.gradle_user_home).resolve()),
        "--no-daemon",
        ":host:connectedDebugAndroidTest",
        f"-Pvyne.appSource={TEST_APP}",
        f"-Pvyne.extensionKotlinDirs={':'.join(map(str, extension_kotlin_dirs))}",
        f"-Pvyne.extensionPythonDirs={':'.join(map(str, extension_python_dirs))}",
        "-Pvyne.appModule=vyne_emulator_app",
        "-Pvyne.appLabel=Vyne Emulator Tests",
    ]
    class_argument = test_class_argument(args.test_class)
    if class_argument is not None:
        command.append(class_argument)

    environment = {
        **os.environ,
        "ANDROID_SERIAL": serial,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    started = time.time()
    process = subprocess.run(
        command,
        cwd=ANDROID_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=args.timeout,
        check=False,
    )
    elapsed = time.time() - started
    results_root = (
        ANDROID_ROOT
        / "host"
        / "build"
        / "outputs"
        / "androidTest-results"
    )
    counts = instrumentation_counts(results_root, since=started)
    return {
        "ok": run_succeeded(process.returncode, counts),
        "device": device,
        "command": command,
        "elapsed_seconds": round(elapsed, 3),
        "returncode": process.returncode,
        "counts": counts,
        "stdout_tail": process.stdout[-12000:],
        "stderr_tail": process.stderr[-12000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run framework-wide Vyne tests on an already-running emulator"
        )
    )
    parser.add_argument("--serial", help="adb serial; required when multiple devices are online")
    parser.add_argument("--adb", default=os.environ.get("ADB", "adb"))
    parser.add_argument(
        "--gradle-user-home",
        default="/tmp/vyne-emulator-gradle-home",
    )
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument(
        "--allow-physical",
        action="store_true",
        help="allow a non-emulator adb serial",
    )
    parser.add_argument(
        "--test-class",
        action="append",
        default=[],
        help="optional instrumentation class filter; repeatable",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=DEFAULT_EVIDENCE,
    )
    args = parser.parse_args()

    try:
        evidence = run(args)
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        evidence = {"ok": False, "error": str(error)}

    evidence_path = args.evidence.resolve()
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
