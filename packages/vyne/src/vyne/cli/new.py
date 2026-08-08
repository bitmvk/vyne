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
import keyword
from pathlib import Path
import re

from vyne.cli._templates import (
    ANDROID_MANIFEST,
    APP_BUILD_GRADLE,
    GRADLE_PROPERTIES,
    ROOT_BUILD_GRADLE,
    SETTINGS_GRADLE,
)
from vyne.cli.dependencies import ensure_vyne_dependency
from vyne.cli.generation import (
    ConflictPolicy,
    PlanBuilder,
)
from vyne.cli.project import (
    base_project_root_from_package,
    checkout_root_from_package,
    package_python_dir_from_package,
)

ANDROID_RESERVED_WORDS = {
    "abstract",
    "as",
    "assert",
    "break",
    "case",
    "catch",
    "class",
    "const",
    "continue",
    "default",
    "do",
    "else",
    "enum",
    "extends",
    "false",
    "final",
    "finally",
    "for",
    "fun",
    "if",
    "implements",
    "import",
    "in",
    "interface",
    "is",
    "new",
    "null",
    "object",
    "override",
    "package",
    "private",
    "protected",
    "public",
    "return",
    "static",
    "super",
    "switch",
    "this",
    "throw",
    "throws",
    "true",
    "try",
    "val",
    "var",
    "void",
    "when",
    "while",
}


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
    _validate_module(module)

    checkout_root = checkout_root_from_package()
    package_python_dir = package_python_dir_from_package().resolve()
    base_project_root = base_project_root_from_package().resolve()
    app_name = target.name
    app_label = label or _label_from_name(app_name)
    app_package = package or _default_package(app_name)
    _validate_package(app_package)
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
    transformed = _add_dependency(content, dependency)
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
        _settings_gradle(app_name, base_project_root),
        policy=same_policy,
    )
    builder.add_file(
        "android/build.gradle.kts",
        _root_build_gradle(),
        policy=same_policy,
    )
    builder.add_file(
        "android/gradle.properties",
        _gradle_properties(),
        policy=same_policy,
    )
    builder.add_file(
        "android/app/build.gradle.kts",
        _app_build_gradle(),
        policy=same_policy,
    )
    builder.add_file(
        "android/app/src/main/AndroidManifest.xml",
        _android_manifest(),
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
        if not segment[0].isalpha() or _is_reserved_identifier(segment):
            segment = f"app{segment}"
        segments.append(segment)
    return "com.example." + (".".join(segments) if segments else "app")


def _validate_module(module: str) -> None:
    """Ensure the module name is a valid Python import identifier."""
    if not module.isidentifier() or keyword.iskeyword(module):
        raise RuntimeError("module must be a valid Python identifier, for example app")


def _validate_package(package: str) -> None:
    """Ensure the Android application ID is valid (dot-separated, no reserved words)."""
    segments = package.split(".")
    if len(segments) < 2 or any(
        not segment.isidentifier() or _is_reserved_identifier(segment)
        for segment in segments
    ):
        raise RuntimeError(
            "package must be a valid Android application id, for example com.example.app"
        )


def _is_reserved_identifier(value: str) -> bool:
    return keyword.iskeyword(value) or value in ANDROID_RESERVED_WORDS


def _quote(value: str) -> str:
    return json.dumps(value)


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
version = "0.1.0"
version_code = 1

[android]
min_sdk = 26
target_sdk = 35
compile_sdk = 35

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


def _has_dependency(content: str) -> bool:
    """Return True if *content* already contains a Vyne PEP 508 requirement.

    Uses the canonical tomlkit+packaging implementation in
    ``vyne.cli.dependencies``.
    """
    from vyne.cli.dependencies import _has_dependency as _check
    return _check(content)


def _add_dependency(content: str, dependency: str) -> str:
    """Insert *dependency* into ``[project].dependencies`` using a
    structure-preserving round-tripping TOML document.

    Uses ``vyne.cli.dependencies.ensure_vyne_dependency`` so that
    comments, multiline arrays, trailing commas, tool tables, and
    unrelated content are preserved.
    """
    return ensure_vyne_dependency(content, dependency)


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


def _settings_gradle(name: str, base_project_root: Path) -> str:
    result = SETTINGS_GRADLE
    result = result.replace("{name}", name)
    return result


def _root_build_gradle() -> str:
    return ROOT_BUILD_GRADLE


def _gradle_properties() -> str:
    return GRADLE_PROPERTIES


def _app_build_gradle() -> str:
    return APP_BUILD_GRADLE


def _android_manifest() -> str:
    return ANDROID_MANIFEST


def _validate_generated_config(vyne_toml_content: str, target: Path) -> None:
    """Re-parse the generated ``vyne.toml`` content through TOML and
    structural validation, ensuring the generated config is structurally
    valid before any files are placed.

    Does NOT require that path references exist (they may be created later
    or point to pre-existing framework directories).  Raises
    ``RuntimeError`` if the config is malformed TOML, has wrong types,
    or violates SDK/ABI/package/version constraints.
    """
    import tomllib
    try:
        raw = tomllib.loads(vyne_toml_content)
    except Exception as exc:
        raise RuntimeError(
            f"Generated vyne.toml is not valid TOML: {exc}"
        ) from exc
    # Structural validation: types, ranges, package/module patterns,
    # SDK ordering, ABI membership, PEP 440 version.  Path existence
    # is NOT enforced here since paths may reference directories that
    # are created later or that live outside the target tree.
    _validate_config_structure(raw)


def _validate_config_structure(raw: dict) -> None:
    """Validate config structure without path-existence checks.

    Used during generation to ensure the generated config is coherent
    before placement.  Full path validation happens in ``parse_config``
    at load time.
    """
    from vyne.cli.config import (
        _exact_int, _exact_str,
        _validate_package, _validate_module, _validate_pep440,
        _MIN_SDK_MINIMUM,
    )

    # [app] table
    app_table = raw.get("app", {})
    if not isinstance(app_table, dict):
        raise RuntimeError("[app] in vyne.toml must be a table")
    name = _exact_str(app_table, "name", "[app].name")
    if not name:
        raise RuntimeError("[app].name must be a non-empty string")
    _exact_str(app_table, "label", "[app].label", default=name)
    package = _exact_str(app_table, "package", "[app].package", default="com.example.app")
    _validate_package(package)
    module = _exact_str(app_table, "module", "[app].module", default="app")
    _validate_module(module)
    source = _exact_str(app_table, "source", "[app].source", default="app.py")
    if not source:
        raise RuntimeError("[app].source must be a non-empty string")
    version = _exact_str(app_table, "version", "[app].version", default="0.1.0")
    _validate_pep440(version, "[app].version")
    version_code = _exact_int(app_table, "version_code", "[app].version_code", default=1)
    if not (1 <= version_code <= 2_100_000_000):
        raise RuntimeError(
            f"[app].version_code must be between 1 and 2_100_000_000, got {version_code}"
        )

    # [android] table
    android_table = raw.get("android", {})
    if not isinstance(android_table, dict):
        raise RuntimeError("[android] in vyne.toml must be a table")
    min_sdk = _exact_int(android_table, "min_sdk", "[android].min_sdk", default=26)
    target_sdk = _exact_int(android_table, "target_sdk", "[android].target_sdk", default=35)
    compile_sdk = _exact_int(android_table, "compile_sdk", "[android].compile_sdk", default=35)
    if min_sdk < _MIN_SDK_MINIMUM:
        raise RuntimeError(
            f"[android].min_sdk must be >= {_MIN_SDK_MINIMUM}, got {min_sdk}"
        )
    if not (min_sdk <= target_sdk <= compile_sdk):
        raise RuntimeError(
            f"[android] SDK ordering violated: "
            f"min_sdk({min_sdk}) <= target_sdk({target_sdk}) <= "
            f"compile_sdk({compile_sdk})"
        )
    # [paths] table — require keys to be present and be strings,
    # but do not require the paths to exist on disk yet.
    paths_table = raw.get("paths", {})
    if not isinstance(paths_table, dict):
        raise RuntimeError("[paths] in vyne.toml must be a table")
    for key in ("package_python_dir", "base_project_root"):
        val = paths_table.get(key)
        if val is None:
            raise RuntimeError(f"[paths].{key} is required")
        if not isinstance(val, str):
            raise RuntimeError(
                f"[paths].{key} must be a string, got {type(val).__name__}"
            )

    # [framework] table is optional
    framework_table = raw.get("framework", {})
    if framework_table is not None and not isinstance(framework_table, dict):
        raise RuntimeError("[framework] in vyne.toml must be a table")
