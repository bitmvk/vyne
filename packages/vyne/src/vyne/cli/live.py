"""Dev loop backend for ``vyne run`` — build once, then hot-swap Python.

``vyne run`` stays alive after the first build/install/launch:

- ``R`` — full rebuild: Gradle assemble + adb install + relaunch (native
  layer and framework changes take effect).
- ``r`` — hot reload: deploy the app's own Python (and extension python)
  onto the device and bump a ``REV`` marker; the packaged ``vyne.live``
  watcher recreates the host Activity with the new code. No rebuild.
- ``q`` / Ctrl-C — exit.

The very first hot reload arms live mode: it pushes the sources, then
force-stops and relaunches the app so the loader picks up the ``ENABLED``
marker. Every later ``r`` swaps in place without a restart.

Only app + extension Python is swappable; the framework and Kotlin/native
layers are frozen in the APK and need ``R``.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from vyne.cli.android import _ensure_adb_device
from vyne.cli.project import Project, load_project

LIVE_DIR = "vyne-live"
STAGING = "/data/local/tmp/vyne-live"

_SKIP_DIRS = frozenset({
    "android", ".venv", "build", "dist", ".git", "tests",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})

_HELP = (
    "\nvyne run — dev loop\n"
    "  R  rebuild: Gradle build + install + relaunch (native/framework)\n"
    "  r  hot reload: swap the app's Python, no rebuild\n"
    "  q  quit\n"
)


# ---------------------------------------------------------------------------
# Deployment (host-independent-ish; talks to adb)
# ---------------------------------------------------------------------------

def _collect(project: Project) -> list[tuple[Path, str]]:
    """Every local Python file to swap, as ``(abspath, live_relpath)``.

    Mirrors the app's import root (directory containing the app source file)
    and each extension's python dir, so module imports resolve under the
    live tree exactly as they do from the frozen APK. Later roots win on a
    relpath collision (extensions resolve their own modules).
    """
    roots = [project.app_source.parent]
    for extension in getattr(project, "extensions", ()) or ():
        python_dir = getattr(extension, "python_dir", None)
        if python_dir is not None:
            roots.append(python_dir)

    merged: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root)
            if any(part in _SKIP_DIRS for part in rel.parts):
                continue
            merged[str(rel)] = path.resolve()
    return [(path, rel) for rel, path in sorted(merged.items())]


def _adb(*args: str) -> None:
    _ensure_adb_device()
    subprocess.run(["adb", *args], check=True)


def _runas(project: Project, script: str) -> None:
    """Run *script* as the app's uid via ``run-as sh -c``.

    ``adb shell`` joins argv with spaces before the device re-parses, so the
    script must be single-quoted as ONE argv element or the remote shell
    hands only its first token to ``sh -c``.
    """
    _adb("shell", "run-as", project.app.package, "sh", "-c", f"'{script}'")


def _adb_out(*args: str) -> str:
    """Run an adb probe without raising; '' means it produced / requires nothing."""
    if shutil.which("adb") is None:
        return ""
    try:
        return subprocess.run(
            ["adb", *args], check=False, text=True, capture_output=True
        ).stdout
    except OSError:
        return ""


def _runas_out(project: Project, script: str) -> str:
    """Run *script* under the app's uid and capture stdout (see _runas)."""
    return _adb_out(
        "shell", "run-as", project.app.package, "sh", "-c", f"'{script}'"
    )


def _live_armed(project: Project) -> bool:
    """True when the device live tree already carries the ENABLED marker."""
    return "ENABLED" in _runas_out(project, f"ls files/{LIVE_DIR}")


def _deploy(project: Project) -> int:
    """Stage the app's Python on the device, copy it into the app's files
    dir via run-as, and bump REV last so the watcher fires exactly once."""
    files = _collect(project)
    rev = str(time.time_ns())

    # 1. Stage on the shell-readable side, preserving the import layout.
    _adb("shell", "rm", "-rf", STAGING)
    parents = sorted({str(Path(rel).parent) for _, rel in files})
    if parents:
        _adb("shell", "mkdir", "-p", *(f"{STAGING}/{p}" for p in parents))
    for path, rel in files:
        _adb("push", str(path), f"{STAGING}/{rel}")
    _adb("shell", "chmod", "-R", "755", STAGING)

    # 2. Copy into the app's files dir (run-as, so nothing survives an
    #    uninstall) and arm live mode. REV is written last. No single quotes
    #    inside these scripts — they are wrapped in quotes by _runas.
    copy_script = (
        f"rm -rf files/{LIVE_DIR} && mkdir -p files/{LIVE_DIR} && "
        f"cp -r {STAGING}/. files/{LIVE_DIR}/ && "
        f"touch files/{LIVE_DIR}/ENABLED"
    )
    _runas(project, copy_script)
    _runas(project, f"echo {rev} > files/{LIVE_DIR}/REV")
    return len(files)


def deploy(project: Project) -> int:
    """Hot-swap the app's Python, arming live mode on the first push."""
    armed = _live_armed(project)
    count = _deploy(project)
    if not armed:
        # First activation: the running app has no watcher yet, so give it a
        # cold start — it will boot with live mode armed and the new code.
        _adb("shell", "am", "force-stop", project.app.package)
        _adb("shell", "am", "start", "-n", project.main_activity)
        print(f"  armed live mode; cold-restarted ({count} files pushed)")
    return count


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------

def _read_key() -> str | None:
    """One keypress without Enter; '' on EOF, None on poll timeout."""
    if sys.platform == "win32":
        return _read_key_msvcrt()
    return _read_key_posix()


def _read_key_msvcrt() -> str:
    import msvcrt  # Windows only

    try:
        return msvcrt.getwch()  # type: ignore[attr-defined]
    except (KeyboardInterrupt, EOFError):
        return ""


def _read_key_posix() -> str | None:
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except Exception:
        return _read_key_line()  # not a terminal: fall back to line input
    try:
        tty.setcbreak(fd)
        ready, _, _ = select.select([sys.stdin], [], [], 0.2)
        if not ready:
            return None
        char = sys.stdin.read(1)
        return "" if char == "" else char
    except (KeyboardInterrupt, EOFError):
        return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_key_line() -> str | None:
    try:
        return input().strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def run_dev(args: argparse.Namespace) -> int:
    """Build/install/launch, then keep the dev loop open (unless --once)."""
    from vyne.cli.android import run_project

    project = load_project()
    run_project(project)
    print("Installed and launched APK.")
    if getattr(args, "once", False):
        return 0
    print(_HELP)
    try:
        while True:
            key = _read_key()
            if key in ("q", "x", "\x03", ""):
                print("vyne run: bye")
                return 0
            if key is None:
                continue
            if key == "r":
                deploy(project)
            elif key == "R":
                print("  rebuilding (native + framework take effect)...")
                run_project(project)
                print(_HELP)
            elif key in ("\n", "\r", " "):
                print(_HELP)
    except KeyboardInterrupt:
        print("\nvyne run: bye")
        return 0
