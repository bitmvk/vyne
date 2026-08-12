"""Atomic project generation: stage into a temporary sibling, publish with os.replace.

Managed files are staged into a temporary sibling directory on the same
filesystem and published with a single ``os.replace`` — no journals, no
backups, no per-file merges.  Generation only targets empty (or missing)
directories; an existing non-empty target is refused unless ``force``
replaces the entire tree.

CLI-02 / GEN-14: atomic generation and path-escape rejection.
"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import mkdtemp
import shutil


# Files that must be executable after placement.
_EXECUTABLE_FILES = frozenset({
    "android/gradlew",
    "gradlew",
})


class GenerationPlan:
    """A fully staged tree, ready to publish.  Call ``apply()`` then
    ``cleanup()``.  Do not instantiate directly — use ``PlanBuilder.preflight()``.
    """

    def __init__(self, target_root: Path, staging_root: Path) -> None:
        self.target_root = target_root
        self.staging_root = staging_root
        self._applied = False

    def apply(self, *, force: bool = False) -> None:
        """Publish the staged tree atomically.

        The target must not exist, or be an empty directory.  With
        ``force=True`` an existing non-empty target is replaced entirely.
        """
        if self._applied:
            raise RuntimeError("GenerationPlan already applied")
        self._applied = True
        _clear_target(self.target_root, force=force)
        self.target_root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(self.staging_root, self.target_root)

    def cleanup(self) -> None:
        """Remove leftover staging debris (safe after success or failure)."""
        if self.staging_root.exists():
            shutil.rmtree(self.staging_root, ignore_errors=True)


def _clear_target(target: Path, *, force: bool) -> None:
    """Enforce the empty-target rule, optionally clearing the target."""
    if target.is_symlink():
        raise RuntimeError(
            f"Refusing to generate through symlink target: {target}"
        )
    if not target.exists():
        return
    if not target.is_dir():
        raise RuntimeError(f"{target} exists and is not a directory")
    if any(target.iterdir()):
        if not force:
            raise RuntimeError(
                f"Refusing to generate into non-empty directory {target}; "
                f"use --force to replace it entirely"
            )
        shutil.rmtree(target)
    else:
        target.rmdir()


class PlanBuilder:
    """Gathers managed files and preflights them into a temp sibling.

    Every path is relative to the target root and must not escape it (no
    ``..`` segments, no absolute paths).
    """

    def __init__(self, target_root: Path) -> None:
        self.target_root = target_root
        self._plan: GenerationPlan | None = None
        self._files: list[tuple[str, bytes]] = []

    def add_file(self, relative: str, content: str | bytes) -> None:
        """Stage a file.  Strings are UTF-8 encoded."""
        self._validate_relative(relative)
        data = content.encode("utf-8") if isinstance(content, str) else content
        self._files.append((relative, data))

    def preflight(self) -> GenerationPlan:
        """Stage every file into a temporary sibling with final modes.

        Nothing in the target is modified yet.  Raises ``RuntimeError`` if
        called more than once.
        """
        if self._plan is not None:
            raise RuntimeError("preflight already called")
        parent = self.target_root.parent
        parent.mkdir(parents=True, exist_ok=True)
        staging = Path(mkdtemp(prefix=".vyne-stage-", dir=str(parent)))
        for relative, data in self._files:
            dest = staging / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            if relative in _EXECUTABLE_FILES:
                dest.chmod(0o755)
        self._plan = GenerationPlan(self.target_root, staging)
        return self._plan

    def _validate_relative(self, relative: str) -> None:
        """Reject paths that escape the target root via ``..`` segments or
        absolute paths."""
        if not relative or relative.startswith("/"):
            raise RuntimeError(
                f"Managed file path must be relative: {relative!r}"
            )
        parts = relative.replace("\\", "/").split("/")
        if ".." in parts:
            raise RuntimeError(
                f"Managed file path must not escape target root: {relative!r}"
            )
