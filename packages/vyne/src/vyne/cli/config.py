"""Validated project configuration for the Vyne CLI.

Parses a ``vyne.toml`` file into a strongly-typed ``ValidatedConfig``,
enforcing exact types, required tables, valid SDK/ABI/version values, and
config-relative path resolution.  Replaces permissive ``_int``/``_string``/
``_path`` helpers that silently accepted bool-as-int, invalid application IDs,
and resolved relative paths from the process CWD.

``parse_config`` is the single parsing/validation entry point used by project
loading and by generation preflight.  ``validate_package``, ``validate_module``,
and ``is_reserved_identifier`` are the one identifier policy shared by
``parse_config``, ``vyne new``, and extension scaffolding so no CLI path
accepts a name another path rejects.
"""

from __future__ import annotations

from dataclasses import dataclass
import keyword
import re
from pathlib import Path
from typing import Mapping

from packaging.version import Version as Pep440Version, InvalidVersion


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_SDK_MINIMUM = 26
_DEFAULT_COMPILE_SDK = 35
_DEFAULT_TARGET_SDK = 35
_DEFAULT_MIN_SDK = 26
_DEFAULT_VERSION = "0.1.0"
_DEFAULT_VERSION_CODE = 1

# Android application ID segments must start with an ASCII letter while
# Python module names may start with an underscore.  Both are ASCII-only
# identifiers for Vyne-generated configurations.
_PACKAGE_SEGMENT_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
_MODULE_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Java/Kotlin reserved words that cannot appear in an Android application ID
# segment.  Combined with Python keywords by ``is_reserved_identifier``.
ANDROID_RESERVED_WORDS = frozenset({
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
})


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AppIdentity:
    """Validated ``[app]`` section values."""
    name: str
    label: str
    package: str
    module: str
    source: str
    version: str
    version_code: int


@dataclass(frozen=True)
class AndroidSpec:
    """Validated ``[android]`` section values."""
    min_sdk: int
    target_sdk: int
    compile_sdk: int


@dataclass(frozen=True)
class PathsConfig:
    """Validated ``[paths]`` section values, resolved from the config root."""
    package_python_dir: Path
    base_project_root: Path


@dataclass(frozen=True)
class FrameworkConfig:
    """Optional ``[framework]`` section values."""
    root: Path | None


@dataclass(frozen=True)
class ValidatedConfig:
    """Fully validated Vyne project configuration.

    Every field has been type-checked, range-checked, and resolved
    relative to the configuration file's parent directory.
    """
    config_path: Path
    app: AppIdentity
    android: AndroidSpec
    paths: PathsConfig
    framework: FrameworkConfig


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_config(
    raw: Mapping[str, object],
    *,
    config_path: Path,
    check_paths: bool = True,
) -> ValidatedConfig:
    """Validate *raw* TOML data and return a ``ValidatedConfig``.

    *config_path* is the absolute path to the ``vyne.toml`` file so that
    relative paths are resolved from its parent directory.

    *check_paths* controls whether referenced directories must already
    exist.  Project loading sets it to True; generation preflight validates
    the exact same structural policy with ``check_paths=False`` before the
    referenced directories are created.

    Raises ``RuntimeError`` with a field-path diagnostic for any invalid
    value.
    """
    config_dir = config_path.parent
    app = _parse_app(raw)
    android = _parse_android(raw)
    paths = _parse_paths(raw, config_dir, check_paths=check_paths)
    framework = _parse_framework(raw, config_dir, check_paths=check_paths)

    return ValidatedConfig(
        config_path=config_path,
        app=app,
        android=android,
        paths=paths,
        framework=framework,
    )


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------

def _parse_app(raw: Mapping[str, object]) -> AppIdentity:
    table = _table(raw, "app")
    name = _exact_str(table, "name", "[app].name")
    if not name:
        raise RuntimeError("[app].name must be a non-empty string")
    label = _exact_str(table, "label", "[app].label", default=name)
    package = _exact_str(table, "package", "[app].package", default="com.example.app")
    validate_package(package)
    module = _exact_str(table, "module", "[app].module", default="app")
    validate_module(module)
    source = _exact_str(table, "source", "[app].source", default="app.py")
    if not source:
        raise RuntimeError("[app].source must be a non-empty string")
    version = _exact_str(table, "version", "[app].version", default=_DEFAULT_VERSION)
    validate_pep440(version, "[app].version")
    version_code = _exact_int(table, "version_code", "[app].version_code",
                              default=_DEFAULT_VERSION_CODE)
    if not (1 <= version_code <= 2_100_000_000):
        raise RuntimeError(
            f"[app].version_code must be between 1 and 2_100_000_000, got {version_code}"
        )
    return AppIdentity(
        name=name,
        label=label,
        package=package,
        module=module,
        source=source,
        version=version,
        version_code=version_code,
    )


def _parse_android(raw: Mapping[str, object]) -> AndroidSpec:
    table = raw.get("android", {})
    if not isinstance(table, dict):
        raise RuntimeError("[android] in vyne.toml must be a table")

    min_sdk = _exact_int(table, "min_sdk", "[android].min_sdk",
                         default=_DEFAULT_MIN_SDK)
    target_sdk = _exact_int(table, "target_sdk", "[android].target_sdk",
                            default=_DEFAULT_TARGET_SDK)
    compile_sdk = _exact_int(table, "compile_sdk", "[android].compile_sdk",
                             default=_DEFAULT_COMPILE_SDK)

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
    return AndroidSpec(
        min_sdk=min_sdk,
        target_sdk=target_sdk,
        compile_sdk=compile_sdk,
    )


def _parse_paths(raw: Mapping[str, object], config_dir: Path,
                 *, check_paths: bool) -> PathsConfig:
    table = raw.get("paths", {})
    if not isinstance(table, dict):
        raise RuntimeError("[paths] in vyne.toml must be a table")

    return PathsConfig(
        package_python_dir=_required_path(table, "package_python_dir",
                                          "[paths].package_python_dir",
                                          config_dir, check_paths=check_paths),
        base_project_root=_required_path(table, "base_project_root",
                                         "[paths].base_project_root",
                                         config_dir, check_paths=check_paths),
    )


def _parse_framework(raw: Mapping[str, object], config_dir: Path,
                     *, check_paths: bool) -> FrameworkConfig:
    table = raw.get("framework", {})
    if not isinstance(table, dict):
        raise RuntimeError("[framework] in vyne.toml must be a table")
    root_str = table.get("root")
    if root_str is None:
        return FrameworkConfig(root=None)
    if not isinstance(root_str, str):
        raise RuntimeError(
            f"[framework].root must be a string, "
            f"got {type(root_str).__name__}"
        )
    resolved = _resolve_path(root_str, config_dir)
    if check_paths and not resolved.is_dir():
        raise RuntimeError(
            f"[framework].root resolved to {resolved}, which is not a directory"
        )
    return FrameworkConfig(root=resolved)


# ---------------------------------------------------------------------------
# Primitive validators
# ---------------------------------------------------------------------------

def _table(data: object, name: str) -> dict[str, object]:
    value = data.get(name) if isinstance(data, dict) else None
    if not isinstance(value, dict):
        raise RuntimeError(f"[{name}] in vyne.toml must be a table")
    return value


def _exact_str(data: dict[str, object], key: str, path: str,
               *, default: str | None = None) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise RuntimeError(f"{path} must be a string, got {type(value).__name__}")
    return value


def _exact_int(data: dict[str, object], key: str, path: str,
               *, default: int | None = None) -> int:
    value = data.get(key, default)
    if type(value) is not int:
        raise RuntimeError(
            f"{path} must be an integer, got {type(value).__name__}"
        )
    return value


def _resolve_path(raw: str, config_dir: Path) -> Path:
    """Resolve *raw* relative to *config_dir*.

    Absolute paths (on the current OS) are still resolved/canonicalized
    but a warning about portability may be added later.
    """
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate.expanduser().resolve()
    return (config_dir / candidate).expanduser().resolve()


def _required_path(data: dict[str, object], key: str, path: str,
                   config_dir: Path, *, check_paths: bool) -> Path:
    value = data.get(key)
    if value is None:
        raise RuntimeError(f"{path} is required")
    if not isinstance(value, str):
        raise RuntimeError(f"{path} must be a string, got {type(value).__name__}")
    resolved = _resolve_path(value, config_dir)
    if check_paths and not resolved.exists():
        raise RuntimeError(f"{path} resolved to {resolved}, which does not exist")
    return resolved


# ---------------------------------------------------------------------------
# Shared identifier policy
# ---------------------------------------------------------------------------

# Deliberate alpha tightening: this single policy now applies at config load
# time (``parse_config``) and to extension scaffolding/discovery, not only to
# ``vyne new``.  A manually-edited ``vyne.toml`` or an existing extension
# whose package/module/name uses a Python or Android/Java/Kotlin reserved
# word, or a non-ASCII extension name, is now rejected on every CLI path.
# This is an intentional pre-1.0 decision; in-tree configs are unaffected.

def is_reserved_identifier(value: str) -> bool:
    """Return True for Python keywords and Android/Java/Kotlin reserved words.

    This is the single reserved-word policy used by package, module, and
    extension-name validation across the CLI.
    """
    return keyword.iskeyword(value) or value in ANDROID_RESERVED_WORDS


def validate_package(package: str) -> None:
    """Reject invalid Android application IDs.

    Enforces ASCII-only, dot-separated identifiers with at least two
    segments, requires every segment to start with an ASCII letter, and
    rejects Python/Java/Kotlin reserved words, matching the ``vyne new``
    policy so every CLI path accepts the same packages.
    """
    if not package or ".." in package or package.startswith(".") or package.endswith("."):
        raise RuntimeError(
            f"[app].package must be a valid Android application id, "
            f"got {package!r}"
        )
    segments = package.split(".")
    if len(segments) < 2:
        raise RuntimeError(
            f"[app].package must have at least two dot-separated segments, "
            f"got {package!r}"
        )
    for idx, seg in enumerate(segments):
        if not seg:
            raise RuntimeError(
                f"[app].package segment {idx} is empty in {package!r}"
            )
        if not _PACKAGE_SEGMENT_RE.match(seg):
            raise RuntimeError(
                f"[app].package segment {idx} ({seg!r}) must start with an "
                f"ASCII letter and contain only ASCII letters, digits, and "
                f"underscores, got {package!r}"
            )
        if is_reserved_identifier(seg):
            raise RuntimeError(
                f"[app].package segment {idx} ({seg!r}) is a reserved "
                f"identifier; package must be a valid Android application id, "
                f"got {package!r}"
            )


def validate_module(module: str) -> None:
    """Ensure *module* is a valid, non-reserved Python import name."""
    if not module or not _MODULE_RE.match(module) or is_reserved_identifier(module):
        raise RuntimeError(
            f"[app].module must be a valid Python identifier, got {module!r}"
        )


def validate_pep440(version: str, path: str) -> None:
    """Reject versions that are not valid PEP 440 strings."""
    try:
        Pep440Version(version)
    except InvalidVersion as exc:
        raise RuntimeError(
            f"{path} ({version!r}) is not a valid PEP 440 version: {exc}"
        ) from exc
