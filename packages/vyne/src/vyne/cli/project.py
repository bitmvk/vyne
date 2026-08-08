"""Project discovery and configuration for the Vyne CLI.

A "project" can be in two modes:

1. Framework checkout — the vyne repository itself, detected by the presence
   of ``packages/vyne/src/vyne`` and ``android/settings.gradle.kts``.
   Used during framework development; ``vyne run`` builds the host app.

2. Generated project — a user app scaffolded by ``vyne new``, containing a
   ``vyne.toml`` config file, an ``app.py``, and a generated Android project.
   Builds against the framework as a dependency.

Project discovery walks up from the current directory looking for either a
``vyne.toml`` or a framework checkout.  Path resolution uses the config
file's parent directory as the reference for all relative paths.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from vyne.cli.config import (
    parse_config,
)
from vyne.cli.extensions import Extension, discover_extensions


@dataclass(frozen=True)
class AppConfig:
    name: str
    label: str
    package: str
    module: str
    source: str
    version: str
    version_code: int = 1


@dataclass(frozen=True)
class AndroidConfig:
    min_sdk: int
    target_sdk: int
    compile_sdk: int


@dataclass(frozen=True)
class Project:
    root: Path
    config_path: Path | None
    app: AppConfig
    android: AndroidConfig
    package_python_dir: Path
    base_project_root: Path
    generated: bool
    checkout_root: Path | None = None
    extensions: tuple[Extension, ...] = ()

    @property
    def android_dir(self) -> Path:
        return self.root / "android"

    @property
    def gradlew(self) -> Path:
        return self.android_dir / "gradlew"

    @property
    def app_source(self) -> Path:
        return (self.root / self.app.source).resolve()

    @property
    def framework_python_dir(self) -> Path:
        return self.package_python_dir

    @property
    def host_source_dir(self) -> Path:
        if self.checkout_root is not None:
            return self.checkout_root / "android" / "host" / "src" / "main" / "java"
        return self.base_project_root / "android-host" / "src" / "main" / "java"

    @property
    def host_res_dir(self) -> Path:
        if self.checkout_root is not None:
            return self.checkout_root / "android" / "host" / "src" / "main" / "res"
        return self.base_project_root / "android-host" / "src" / "main" / "res"

    @property
    def apk_path(self) -> Path:
        if not self.generated:
            return (
                self.root
                / "android"
                / "host"
                / "build"
                / "outputs"
                / "apk"
                / "debug"
                / "host-debug.apk"
            )
        return (
            self.android_dir
            / "app"
            / "build"
            / "outputs"
            / "apk"
            / "debug"
            / "app-debug.apk"
        )

    @property
    def assemble_task(self) -> str:
        return ":app:assembleDebug" if self.generated else ":host:assembleDebug"

    @property
    def main_activity(self) -> str:
        """Fully qualified Android component name for ``adb shell am start``."""
        return f"{self.app.package}/dev.vyne.MainActivity"

    def gradle_properties(self) -> list[str]:
        """Build the ``-P`` property list passed to Gradle on the command line.

        These ``-Pvyne.*`` properties are read by ``app/build.gradle.kts``
        to wire up the correct Python source, host sources, resource
        directories, and extension directories for the current project.
        """
        extension_kotlin = ":".join(str(e.kotlin_dir) for e in self.extensions)
        extension_res = ":".join(
            str(e.res_dir) for e in self.extensions if e.res_dir is not None
        )
        extension_python = ":".join(str(e.python_dir) for e in self.extensions)
        return [
            f"-Pvyne.applicationId={self.app.package}",
            f"-Pvyne.appLabel={self.app.label}",
            f"-Pvyne.appModule={self.app.module}",
            f"-Pvyne.appSource={self.app_source}",
            f"-Pvyne.frameworkPythonDir={self.framework_python_dir}",
            f"-Pvyne.hostSourceDir={self.host_source_dir}",
            f"-Pvyne.hostResDir={self.host_res_dir}",
            f"-Pvyne.extensionKotlinDirs={extension_kotlin}",
            f"-Pvyne.extensionResDirs={extension_res}",
            f"-Pvyne.extensionPythonDirs={extension_python}",
            f"-Pvyne.minSdk={self.android.min_sdk}",
            f"-Pvyne.targetSdk={self.android.target_sdk}",
            f"-Pvyne.compileSdk={self.android.compile_sdk}",
            f"-Pvyne.versionName={self.app.version}",
            f"-Pvyne.versionCode={self.app.version_code}",
        ]


def checkout_root_from_package() -> Path | None:
    env_root = os.environ.get("VYNE_FRAMEWORK_ROOT")
    if env_root:
        path = Path(env_root).expanduser().resolve()
        if _is_framework_checkout(path):
            return path
        raise RuntimeError(f"VYNE_FRAMEWORK_ROOT is not a framework checkout: {path}")

    for parent in Path(__file__).resolve().parents:
        if _is_framework_checkout(parent):
            return parent
    return None


def package_root_from_package() -> Path:
    return Path(__file__).resolve().parents[1]


def package_python_dir_from_package() -> Path:
    return package_root_from_package().parent


def base_project_root_from_package() -> Path:
    env_root = os.environ.get("VYNE_BASE_PROJECT_ROOT")
    if env_root:
        root = Path(env_root).expanduser().resolve()
        if _is_framework_checkout(root):
            return root
        if _is_base_project(root):
            return root
        raise RuntimeError(f"Missing Vyne base project: {root}")
    else:
        root = package_root_from_package() / "base_project"
        if _is_base_project(root):
            return root

    checkout = checkout_root_from_package()
    if checkout is not None:
        return checkout

    raise RuntimeError(f"Missing Vyne base project: {root}")


def find_project_root(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for path in (current, *current.parents):
        if (path / "vyne.toml").is_file():
            return path
        if _is_framework_checkout(path):
            return path
    return None


@dataclass(frozen=True)
class Issue:
    """One expected inspection failure, with a stable machine-readable code."""

    code: str
    detail: str


@dataclass(frozen=True)
class ProjectInspection:
    """The complete result of one repository inspection (design-pattern #10).

    ``inspect`` never throws for expected discovery/TOML/config/path
    failures — they are ``issues``.  Unexpected programming errors still
    propagate.
    """

    project: Project | None
    issues: tuple[Issue, ...] = ()
    extensions: tuple[Any, ...] = ()


class ProjectRepository:
    """Repository facade: inspect a directory without throwing on
    expected failures, so ``vyne doctor`` can always render something."""

    def inspect(self, start: Path | None = None) -> ProjectInspection:
        issues: list[Issue] = []
        root = find_project_root(start)
        if root is None:
            issues.append(
                Issue(
                    code="no_project",
                    detail=(
                        "No Vyne project found. Run this inside a generated "
                        "project or the framework checkout."
                    ),
                )
            )
            return ProjectInspection(project=None, issues=tuple(issues), extensions=())

        project: Project | None = None
        try:
            project = load_project(root)
        except RuntimeError as exc:
            # Expected failures: bad TOML, bad config values, unrecognized
            # root.  Type/Attribute/OS errors still propagate.
            issues.append(Issue(code="project", detail=str(exc)))

        extensions: tuple[Any, ...] = ()
        try:
            extensions = tuple(discover_extensions(root))
        except RuntimeError as exc:
            issues.append(Issue(code="extensions", detail=str(exc)))

        return ProjectInspection(project=project, issues=tuple(issues), extensions=extensions)


def load_project(start: Path | None = None) -> Project:
    root = find_project_root(start)
    if root is None:
        raise RuntimeError(
            "No Vyne project found. Run this inside a generated project "
            "or the framework checkout."
        )

    config_path = root / "vyne.toml"
    if config_path.is_file():
        return _load_generated_project(root, config_path)

    if _is_framework_checkout(root):
        return _load_framework_checkout(root)

    raise RuntimeError(f"{root} is not a recognized Vyne project")


def _load_generated_project(root: Path, config_path: Path) -> Project:
    import tomllib
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    cfg = parse_config(raw, config_path=config_path)

    app = AppConfig(
        name=cfg.app.name,
        label=cfg.app.label,
        package=cfg.app.package,
        module=cfg.app.module,
        source=cfg.app.source,
        version=cfg.app.version,
        version_code=cfg.app.version_code,
    )
    android = AndroidConfig(
        min_sdk=cfg.android.min_sdk,
        target_sdk=cfg.android.target_sdk,
        compile_sdk=cfg.android.compile_sdk,
    )

    return Project(
        root=root,
        config_path=config_path,
        app=app,
        android=android,
        package_python_dir=cfg.paths.package_python_dir,
        base_project_root=cfg.paths.base_project_root,
        generated=True,
        checkout_root=cfg.framework.root,
        extensions=_discover_best_effort(root),
    )


def _load_framework_checkout(root: Path) -> Project:
    return Project(
        root=root,
        config_path=None,
        app=AppConfig(
            name="Vyne",
            label="Vyne",
            package="dev.vyne",
            module="app",
            source="examples/app.py",
            version="0.1.0a1",
        ),
        android=AndroidConfig(
            min_sdk=26,
            target_sdk=35,
            compile_sdk=35,
        ),
        package_python_dir=(root / "packages" / "vyne" / "src").resolve(),
        base_project_root=root.resolve(),
        generated=False,
        checkout_root=root,
        extensions=_discover_best_effort(root),
    )


def _discover_best_effort(root: Path) -> tuple[Any, ...]:
    """Extension discovery inside project load never raises: the repository
    layer records broken extensions as an Issue (design-pattern #10)."""
    try:
        return tuple(discover_extensions(root))
    except RuntimeError:
        return ()


def _is_framework_checkout(path: Path) -> bool:
    return (
        (path / "packages" / "vyne" / "src" / "vyne").is_dir()
        and (path / "android" / "settings.gradle.kts").is_file()
        and (path / "android" / "gradlew").is_file()
        and (path / "android" / "host" / "build.gradle.kts").is_file()
    )


def _is_base_project(path: Path) -> bool:
    return (
        (path / "android-host" / "src" / "main" / "java" / "dev" / "vyne").is_dir()
        and (path / "gradlew").is_file()
        and (path / "gradle" / "wrapper" / "gradle-wrapper.jar").is_file()
    )
