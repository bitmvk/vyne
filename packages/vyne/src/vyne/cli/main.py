"""Vyne command line entry point.

The CLI is the developer-facing tool for creating, building, and running
Vyne apps on Android.  Subcommands:

  new      — scaffold a new Vyne project directory
  doctor   — check that all build prerequisites are met
  build    — compile the Android APK via Gradle
  install  — build + adb install on a connected device
  run      — build + install + launch via adb
  launch   — launch an already-installed app
  test     — run local Python unit tests

Each subcommand delegates to its respective module in vyne.cli.*.
"""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import subprocess
import sys

from vyne.cli.android import (
    build_project,
    install_project,
    launch_project,
    run_project,
    test_project,
)
from vyne.cli.project import load_project
from vyne.cli.doctor import run_doctor
from vyne.cli.extension_new import create_extension
from vyne.cli.new import create_project


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "new":
            path = create_project(
                Path(args.path),
                package=args.package,
                label=args.label,
                module=args.module,
                force=args.force,
            )
            print(f"Created Vyne project at {path}")
            print("Next steps:")
            print(f"  cd {path}")
            print("  vyne run")
            return 0

        if args.command == "extension":
            if args.extension_command == "new":
                project = load_project(Path.cwd())
                path = create_extension(project.root, args.name, force=args.force)
                print(f"Created extension at {path}")
                print("Next steps:")
                print("  implement MyWidgetView in android/")
                print("  add a MyWidget() constructor in python/")
                print("  vyne build")
                return 0
            parser.print_help()
            return 2

        handler = getattr(args, "handler", None)
        if handler is not None:
            return handler(args)
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        return error.returncode

    parser.print_help()
    return 2


def _parser() -> ArgumentParser:
    """Build the argparse parser with subcommand dispatch.

    Each subcommand sets a ``handler`` function via ``set_defaults()``.
    The main() function looks up ``args.handler`` and calls it, passing
    the parsed args namespace — enabling clean per-command function
    dispatch without a big if/elif chain.
    """
    parser = ArgumentParser(prog="vyne")
    subparsers = parser.add_subparsers(dest="command")

    new = subparsers.add_parser("new", help="create a new Vyne app")
    new.add_argument("path", help="project directory to create")
    new.add_argument("--package", help="Android application id, for example com.example.todo")
    new.add_argument("--label", help="Android launcher label")
    new.add_argument("--module", default="app", help="Python module to import on startup")
    new.add_argument("--force", action="store_true", help="overwrite conflicting files")

    doctor = subparsers.add_parser("doctor", help="check local build prerequisites")
    doctor.add_argument("--device", action="store_true", help="also require an authorized adb device")
    doctor.set_defaults(handler=_doctor)

    build = subparsers.add_parser("build", help="build the debug Android APK")
    build.set_defaults(handler=_build)

    install = subparsers.add_parser("install", help="build and install the debug APK")
    install.set_defaults(handler=_install)

    run = subparsers.add_parser("run", help="build, install, and launch the app")
    run.set_defaults(handler=_run)

    launch = subparsers.add_parser("launch", help="launch an already-installed app")
    launch.set_defaults(handler=_launch)

    test = subparsers.add_parser("test", help="run Python unit tests")
    test.set_defaults(handler=_test)

    extension = subparsers.add_parser("extension", help="extension scaffolding")
    ext_sub = extension.add_subparsers(dest="extension_command")
    ext_new = ext_sub.add_parser("new", help="scaffold a new extension")
    ext_new.add_argument("name", help="extension name (Python identifier)")
    ext_new.add_argument("--force", action="store_true", help="overwrite conflicting files")
    return parser


def _doctor(args) -> int:
    return run_doctor(require_device=args.device)


def _build(_args) -> int:
    apk = build_project()
    print(f"Built APK: {apk}")
    return 0


def _install(_args) -> int:
    apk = install_project()
    print(f"Installed APK: {apk}")
    return 0


def _run(_args) -> int:
    apk = run_project()
    print(f"Installed and launched APK: {apk}")
    return 0


def _launch(_args) -> int:
    launch_project()
    return 0


def _test(_args) -> int:
    test_project()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
