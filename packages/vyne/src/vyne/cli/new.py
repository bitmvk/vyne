"""Project creation command.

'vyne new' scaffolds a complete Vyne app directory containing:
- vyne.toml — project configuration (app identity, Android SDK versions, paths)
- pyproject.toml — Python packaging metadata with vyne dependency
- app.py — a minimal Vyne app with state, event handling, and theming
- tests/test_app.py — a boilerplate unit test
- android/ — a generated Gradle Android project (settings, build scripts,
  manifest, and a copy of the Gradle wrapper from the framework)

The command uses an atomic staging approach: all inputs and destinations
are checked before any target mutation; on failure the target directory
is fully rolled back.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from vyne.cli.config import (
    _DEFAULT_COMPILE_SDK,
    _DEFAULT_MIN_SDK,
    _DEFAULT_TARGET_SDK,
    _DEFAULT_VERSION,
    _DEFAULT_VERSION_CODE,
    is_reserved_identifier,
    parse_config,
    validate_module,
    validate_package,
)
from vyne.cli.dependencies import (
    _has_dependency,
    ensure_vyne_dependency,
)
from vyne.cli.generation import (
    ConflictPolicy,
    PlanBuilder,
)
from vyne.cli.project import (
    base_project_root_from_package,
    checkout_root_from_package,
    package_python_dir_from_package,
)
from vyne.cli.templates import load


def create_project(
    target: Path,
    *,
    package: str | None = None,
    label: str | None = None,
    module: str = "app",
    force: bool = False,
) -> Path:
    """Scaffold a complete Vyne app directory atomically.

    All inputs are validated and all destination conflicts are checked
    before any file in *target* is modified.  If anything fails during
    preflight, *target* is untouched.  If staging placement fails, the
    changes are rolled back.
    """
    target = target.expanduser().resolve()
    if target.exists() and not target.is_dir():
        raise RuntimeError(f"{target} exists and is not a directory")
    validate_module(module)

    checkout_root = checkout_root_from_package()
    package_python_dir = package_python_dir_from_package().resolve()
    base_project_root = base_project_root_from_package().resolve()
    app_name = target.name
    app_label = label or _label_from_name(app_name)
    app_package = package or _default_package(app_name)
    validate_package(app_package)
    source_file = f"{module}.py"

    same_policy = ConflictPolicy.REPLACE if force else ConflictPolicy.ERROR

    builder = PlanBuilder(target)

    # Validate/plan every file before any write
    vyne_toml_content = _project_config(
        name=app_name,
        label=app_label,
        package=app_package,
        module=module,
        source=source_file,
        package_python_dir=package_python_dir,
        base_project_root=base_project_root,
        checkout_root=checkout_root,
    )
    # Re-parse generated config to validate before placement (TL-3)
    _validate_generated_config(vyne_toml_content, target)
    builder.add_file("vyne.toml", vyne_toml_content, policy=same_policy)
    _plan_pyproject(builder, target, app_name, checkout_root, force)
    builder.add_file(source_file, _app_py(app_label), policy=same_policy)
    builder.add_file("__init__.py", "", policy=same_policy)
    builder.add_file(
        "tests/__init__.py", "", policy=same_policy,
    )
    builder.add_file(
        "tests/test_app.py", _test_app(module), policy=same_policy,
    )
    _plan_android_project(builder, target, app_name, base_project_root, force)

    # Preflight stages everything to a temp sibling; apply atomically
    plan = builder.preflight()
    try:
        plan.apply()
    finally:
        plan.cleanup()

    return target


def _plan_pyproject(
    builder: PlanBuilder,
    target: Path,
    app_name: str,
    checkout_root: Path | None,
    force: bool,
) -> None:
    """Plan the pyproject.toml file: either rewrite (force/new) or add
    the Vyne dependency to an existing file."""
    dependency = _dependency(checkout_root)
    pyproject_path = target / "pyproject.toml"

    if force or not pyproject_path.is_file():
        builder.add_file(
            "pyproject.toml",
            _pyproject(app_name, dependency),
            policy=ConflictPolicy.REPLACE if force else ConflictPolicy.ERROR,
        )
        return

    # Existing pyproject.toml: inject dependency or leave unchanged
    content = pyproject_path.read_text(encoding="utf-8")
    if _has_dependency(content):
        # Already has Vyne; preserve the existing file byte-for-byte
        builder.add_file(
            "pyproject.toml",
            content,
            policy=ConflictPolicy.ERROR,
        )
        return

    # Add the dependency preserving structure and comments.
    # This is an intentional modification, so we always replace.
    transformed = ensure_vyne_dependency(content, dependency)
    builder.add_file(
        "pyproject.toml",
        transformed,
        policy=ConflictPolicy.REPLACE,
    )


def _plan_android_project(
    builder: PlanBuilder,
    target: Path,
    app_name: str,
    base_project_root: Path,
    force: bool,
) -> None:
    """Plan all Android project files including the Gradle wrapper copy."""
    same_policy = ConflictPolicy.REPLACE if force else ConflictPolicy.ERROR

    builder.add_file(
        "android/settings.gradle.kts",
        load("settings.gradle.kts").replace(
            "{nameLiteral}", _kotlin_string(app_name)
        ),
        policy=same_policy,
    )
    builder.add_file(
        "android/build.gradle.kts",
        load("root-build.gradle.kts"),
        policy=same_policy,
    )
    builder.add_file(
        "android/gradle.properties",
        load("gradle.properties"),
        policy=same_policy,
    )
    builder.add_file(
        "android/app/build.gradle.kts",
        load("app-build.gradle.kts"),
        policy=same_policy,
    )
    builder.add_file(
        "android/app/src/main/AndroidManifest.xml",
        load("AndroidManifest.xml"),
        policy=same_policy,
    )

    # The packaged host excludes its shipped default registrant, so the
    # app module owns the generated file from day one — the project compiles
    # standalone before the first `vyne build` regeneration.
    from vyne.cli.extensions import registrant_content

    builder.add_file(
        "android/app/src/main/java/dev/vyne/generated/ExtensionRegistrant.kt",
        registrant_content([]),
        policy=same_policy,
    )
    # Gradle wrapper files are read from the base project and staged
    _plan_gradle_wrapper(builder, base_project_root, force)


def _plan_gradle_wrapper(
    builder: PlanBuilder,
    base_project_root: Path,
    force: bool,
) -> None:
    """Stage Gradle wrapper files from the framework's base project.

    Each wrapper file is read during preflight; a missing source is an
    immediate error before any target mutation.
    """
    wrapper_root = _gradle_wrapper_root(base_project_root)
    files = [
        "gradlew",
        "gradlew.bat",
        "gradle/wrapper/gradle-wrapper.jar",
        "gradle/wrapper/gradle-wrapper.properties",
    ]
    for relative in files:
        source = wrapper_root / relative
        if not source.is_file():
            raise RuntimeError(
                f"Missing Gradle wrapper file in base project: {source}"
            )
        dest_rel = f"android/{relative}"
        dest = builder.target_root / dest_rel
        if dest.exists() and not force:
            if dest.read_bytes() == source.read_bytes():
                continue
            raise RuntimeError(
                f"Refusing to overwrite existing file: {dest}"
            )
        is_gradlew = relative == "gradlew"
        builder.add_file(
            dest_rel,
            source.read_bytes(),
            policy=ConflictPolicy.REPLACE if force else ConflictPolicy.ERROR,
            executable=is_gradlew,  # gradlew must be executable (CLI-02)
        )


def _gradle_wrapper_root(base_project_root: Path) -> Path:
    checkout_android = base_project_root / "android"
    if (checkout_android / "gradlew").is_file():
        return checkout_android
    return base_project_root


def _label_from_name(name: str) -> str:
    words = re.split(r"[^A-Za-z0-9]+", name)
    return " ".join(word[:1].upper() + word[1:] for word in words if word) or "Vyne App"


def _default_package(name: str) -> str:
    raw_segments = re.split(r"[^A-Za-z0-9]+", name.lower())
    segments = []
    for segment in raw_segments:
        if not segment:
            continue
        if not segment[0].isalpha() or is_reserved_identifier(segment):
            segment = f"app{segment}"
        segments.append(segment)
    return "com.example." + (".".join(segments) if segments else "app")


def _quote(value: str) -> str:
    return json.dumps(value)


def _kotlin_string(value: str) -> str:
    """Return *value* as a valid Kotlin double-quoted string literal.

    Escapes backslashes, double quotes, dollar signs, and every control
    character (the C0 range ``\\u0000``-``\\u001F`` plus DEL) so a target
    directory name cannot inject invalid or behavior-changing syntax into
    the generated ``settings.gradle.kts``.  Newline, carriage return, and
    tab use the named Kotlin escapes; the remaining control characters use
    ``\\uXXXX`` Unicode escapes (valid Kotlin string escapes).  Backslashes
    are escaped first so later escapes stay unambiguous.
    """
    escaped = value.replace("\\", "\\\\")
    escaped = escaped.replace('"', '\\"')
    escaped = escaped.replace("$", "\\$")
    escaped = escaped.replace("\n", "\\n")
    escaped = escaped.replace("\r", "\\r")
    escaped = escaped.replace("\t", "\\t")

    def _escape(char: str) -> str:
        code = ord(char)
        if code < 0x20 or code == 0x7F:
            return f"\\u{code:04X}"
        return char

    escaped = "".join(_escape(char) for char in escaped)
    return f'"{escaped}"'


def _project_config(
    *,
    name: str,
    label: str,
    package: str,
    module: str,
    source: str,
    package_python_dir: Path,
    base_project_root: Path,
    checkout_root: Path | None,
) -> str:
    checkout_section = ""
    if checkout_root is not None:
        checkout_section = f"""
[framework]
root = {_quote(checkout_root.as_posix())}
"""

    return f"""[app]
name = {_quote(name)}
label = {_quote(label)}
package = {_quote(package)}
module = {_quote(module)}
source = {_quote(source)}
version = {_quote(_DEFAULT_VERSION)}
version_code = {_DEFAULT_VERSION_CODE}

[android]
min_sdk = {_DEFAULT_MIN_SDK}
target_sdk = {_DEFAULT_TARGET_SDK}
compile_sdk = {_DEFAULT_COMPILE_SDK}

[paths]
package_python_dir = {_quote(package_python_dir.as_posix())}
base_project_root = {_quote(base_project_root.as_posix())}
{checkout_section}"""


def _dependency(checkout_root: Path | None) -> str:
    return (
        f"vyne @ {checkout_root.as_uri()}"
        if checkout_root is not None
        else "vyne"
    )


def _pyproject(name: str, dependency: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-._").lower() or "vyne-app"
    return f"""[project]
name = {_quote(normalized)}
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [{_quote(dependency)}]

[tool.uv]
package = false
"""


def _app_py(label: str) -> str:
    return f'''from vyne import Box, Column, Text, run_app, state


def App():
    clicks = state(0)

    return Column(
        Text(
            text={_quote(label)},
            font_size=24,
            text_color="#172554",
            include_font_padding=False,
        ),
        Box(
            Text(text=f"Clicked {{clicks.value}} times", text_color="#ffffff"),
            background_color="#2563eb",
            corner_radius=12,
            padding=16,
            margin_top=16,
            on_click=lambda _: clicks.set(clicks.value + 1),
        ),
        padding=24,
    )


run_app(App)
'''


def _test_app(module: str) -> str:
    return f'''import unittest

from vyne.bootstrap import _start_registered_app
from vyne.transport import MemoryTransport


class AppTests(unittest.TestCase):
    def test_app_mounts_through_host_bootstrap(self):
        transport = MemoryTransport()
        runtime = _start_registered_app({_quote(module)}, transport=transport)
        try:
            self.assertIsNotNone(runtime._coordinator.accepted_root)
            self.assertIsNotNone(transport.latest)
        finally:
            runtime.dispose()
'''


def _validate_generated_config(vyne_toml_content: str, target: Path) -> None:
    """Re-parse the generated ``vyne.toml`` through the single config
    validator, ensuring it is structurally valid before any files are placed.

    ``check_paths=False`` skips directory-existence checks: paths may be
    created during placement or point to pre-existing framework directories.
    """
    import tomllib
    try:
        raw = tomllib.loads(vyne_toml_content)
    except Exception as exc:
        raise RuntimeError(
            f"Generated vyne.toml is not valid TOML: {exc}"
        ) from exc
    parse_config(raw, config_path=target / "vyne.toml", check_paths=False)
