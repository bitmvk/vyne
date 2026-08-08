"""Durable, recoverable generation transaction with journal/rollback.

Replaces the incremental-write model so that every input and destination
is checked before any target mutation.  Staged files live in a temporary
sibling directory with final modes applied; no fallible mutation occurs
after publication.

Transaction phases
------------------
1. SCAN — build an immutable plan with target snapshots.
2. STAGE — copy/encode all files into a same-filesystem staging directory
   with correct modes.
3. REVALIDATE — check that target snapshots have not changed since scan.
4. PUBLISH — for new targets rename staging into place; for existing
   targets rename target to backup, staging to target.
5. COMMIT — remove backup (success) or restore from backup (failure).
6. RECOVER — detect interrupted published/backed-up states next run and
   complete or restore deterministically.

CLI-02 / GEN-14: atomic generation, snapshot revalidation, symlink escape
rejection, durable journal, and failure-injection coverage.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum, auto
import hashlib
import json
import os
from pathlib import Path
import shutil
from tempfile import mkdtemp


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class ConflictPolicy(Enum):
    """How to handle an existing managed file that differs from the desired
    content."""
    ERROR = auto()   # raise RuntimeError
    SKIP = auto()    # leave existing file untouched
    REPLACE = auto() # overwrite (only with staging + backup)


@dataclass(frozen=True)
class ManagedFile:
    """A file or directory tree that the generator is responsible for placing.

    Every path is relative to the project root and must not escape outside
    it (no ``..`` segments, no absolute paths, no symlink intermediates that
    resolve outside the target).  Symlink escapes through managed parents are
    checked during plan validation.
    """
    relative: str                           # relative to project root
    content: bytes | None = None            # None = a directory source
    source_dir: Path | None = None          # copy-tree source (only for dirs)
    policy: ConflictPolicy = ConflictPolicy.ERROR
    is_dir_copy: bool = False               # True = copy source_dir recursively
    executable: bool = False                # Set 0o755 after staging (gradlew, etc.)


@dataclass
class JournalRecord:
    original: str
    backup: str | None
    digest: str | None
    mode: int | None
    phase: str
    restored: bool = False
    created: bool = False


@dataclass
class GenerationPlan:
    """Resolved plan: all targets classified, staging root created, ready to
    apply.  Call ``apply()`` to execute, then ``cleanup()`` on success or
    rollback.

    **Do not instantiate directly.**  Use ``PlanBuilder.preflight()``.
    """

    target_root: Path
    staging_root: Path
    files: list[ManagedFile]
    _journal_records: list["JournalRecord"] = field(default_factory=list, repr=False)

    # Internal bookkeeping
    _target_snapshots: dict[str, bytes | None] = field(
        default_factory=dict, repr=False,
    )
    _newly_placed: list[Path] = field(default_factory=list, repr=False)
    _applied: bool = field(default=False, repr=False)

    # --- public API ---

    def apply(self) -> None:
        """Publish the staged tree and commit (or rollback on failure).

        * Phase 3 (REVALIDATE): verify snapshot invariants.
        * Phase 4 (PUBLISH): move staging -> target, with backup.
        * Phase 5 (COMMIT): remove backup; on any failure, restore backup.
        """
        if self._applied:
            raise RuntimeError("GenerationPlan already applied")
        self._applied = True
        self._newly_placed.clear()

        try:
            self._revalidate_snapshots()
            self._publish()
            self._commit()
        except Exception:
            self._rollback_publish()
            # Always clean staging after a failed publish/commit
            self._remove_staging()
            raise

    def cleanup(self) -> None:
        """Remove staging directory and backup debris.

        After a successful ``apply()`` this removes staging artifacts.
        After a failed ``apply()`` the caller already raised, and cleanup
        of staging was handled during rollback, but this is still safe
        to call (it is a no-op if staging is already gone).
        """
        self._remove_staging()
        # Verified success/rollback removes the journal itself.  An incomplete
        # journal is recovery evidence and cleanup must never destroy it.
        if not self._journal_path.exists():
            shutil.rmtree(self._backup_root, ignore_errors=True)

    @property
    def _journal_path(self) -> Path:
        return self.target_root.parent / f".{self.target_root.name}.vyne-generation-journal"

    @property
    def _backup_root(self) -> Path:
        return self.target_root.parent / f".{self.target_root.name}.vyne-backups"

    def _sync_journal(self) -> None:
        payload = {
            "version": 1,
            "target": str(self.target_root),
            "records": [asdict(record) for record in self._journal_records],
        }
        temp = self._journal_path.with_suffix(self._journal_path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        with temp.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temp, self._journal_path)
        directory_fd = os.open(self._journal_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    # --- internal: revalidate ---

    def _revalidate_snapshots(self) -> None:
        """Phase 3: verify that target file snapshots match what was recorded
        during planning.  A late writer that changed (or created) a managed
        file must cause the generation to abort before any mutation.
        """
        for rel, expected_bytes in self._target_snapshots.items():
            dest = self.target_root / rel
            actual = dest.read_bytes() if dest.is_file() else None
            if actual != expected_bytes:
                raise RuntimeError(
                    f"Target file changed after planning: {dest}"
                )

    # --- internal: publish ---

    def _publish(self) -> None:
        """Phase 4: atomically swap staging into place.

        - For a new or empty target: rename staging -> target.
        - For an existing, non-empty target: individually move each
          staged file into the target, backing up any file that
          existed before.  Unrelated files are preserved.
        """
        target = self.target_root
        staging = self.staging_root
        is_empty = self._target_is_effectively_empty()

        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)

        if is_empty or not target.exists():
            # New target: rename staging into place atomically.
            os.rename(staging, target)
            # staging no longer exists — clear reference
            self.staging_root = target.parent / ".vyne-staging-gone"
            return

        # Existing non-empty target: per-file merge.
        # First make the target directory if staging had it (should already exist).
        target.mkdir(parents=True, exist_ok=True)
        self._place_files(staging, target)
        # staging now has only empty dirs; remove it
        self._remove_staging()

    def _place_files(self, staging: Path, target: Path) -> None:
        """Move every staged file into *target*, backing up overwritten files.

        Traverses the staging tree and renames each file/dir into place.
        Directories that already exist in *target* are merged; files are
        backed up before replacement.
        """
        for staged_entry in sorted(staging.iterdir()):
            dest = target / staged_entry.name
            if staged_entry.is_dir():
                # Merge directories
                dest.mkdir(exist_ok=True)
                self._place_files(staged_entry, dest)
                # Remove the (now empty) staging subdirectory
                try:
                    staged_entry.rmdir()
                except OSError:
                    pass
            else:
                # File: backup existing, then rename
                if dest.exists():
                    self._backup_path(dest)
                else:
                    relative = dest.relative_to(self.target_root).as_posix()
                    self._journal_records.append(JournalRecord(
                        original=relative, backup=None, digest=None, mode=None,
                        phase="prepared", created=True,
                    ))
                    self._sync_journal()
                    self._newly_placed.append(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.rename(staged_entry, dest)
                self._journal_records[-1].phase = "published"
                self._sync_journal()

    def _backup_path(self, path: Path) -> None:
        """Journal the exact original path before an opaque backup rename."""
        if not path.exists():
            return
        relative = path.relative_to(self.target_root).as_posix()
        data = path.read_bytes()
        mode = path.stat().st_mode & 0o7777
        self._backup_root.mkdir(parents=True, exist_ok=True)
        backup = self._backup_root / f"record-{len(self._journal_records):08d}.bak"
        record = JournalRecord(
            original=relative,
            backup=backup.name,
            digest=hashlib.sha256(data).hexdigest(),
            mode=mode,
            phase="prepared",
        )
        self._journal_records.append(record)
        self._sync_journal()
        os.rename(path, backup)
        record.phase = "backed_up"
        self._sync_journal()

    def _commit(self) -> None:
        """Mark verified publication and remove recovery evidence."""
        for record in self._journal_records:
            record.phase = "committed"
        if self._journal_records:
            self._sync_journal()
        if self._backup_root.exists():
            shutil.rmtree(self._backup_root, ignore_errors=False)
        self._journal_path.unlink(missing_ok=True)
        self._journal_records.clear()

    def _rollback_publish(self) -> None:
        """Restore exact paths/modes/digests or preserve an actionable journal."""
        try:
            for record in reversed(self._journal_records):
                dest = self.target_root / record.original
                if record.created:
                    if dest.exists():
                        dest.unlink()
                else:
                    if record.backup is None:
                        raise RuntimeError(f"Missing backup identity for {record.original}")
                    backup = self._backup_root / record.backup
                    if not backup.exists():
                        raise RuntimeError(f"Missing backup file {backup}")
                    if dest.exists():
                        dest.unlink()
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    os.rename(backup, dest)
                    if record.mode is not None:
                        dest.chmod(record.mode)
                    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
                    if digest != record.digest:
                        raise RuntimeError(f"Restored digest mismatch for {dest}")
                record.restored = True
                record.phase = "restored"
                self._sync_journal()
        except Exception as exc:
            raise RuntimeError(
                f"Generation rollback incomplete; recovery journal preserved at "
                f"{self._journal_path}: {exc}"
            ) from exc
        self._journal_path.unlink(missing_ok=True)
        if self._backup_root.exists():
            shutil.rmtree(self._backup_root, ignore_errors=False)
        self._journal_records.clear()
        self._newly_placed.clear()

    # --- internal helpers ---

    def _target_is_effectively_empty(self) -> bool:
        """Return True when the target does not exist or is an empty directory.

        If the parent directory doesn't exist, the target is effectively
        empty (it will be created during publish).
        """
        target = self.target_root
        if not target.exists():
            return True
        if not target.is_dir():
            return False
        try:
            return not any(target.iterdir())
        except OSError:
            return False

    def _remove_staging(self) -> None:
        staging = self.staging_root
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    def _set_executable_bits(self) -> None:
        """Set executable permissions on staged files that require them.

        Called during staging (before publish), so a chmod failure is a
        preflight error, not a post-publication inconsistency.
        """
        for mf in self.files:
            if not mf.executable:
                continue
            dest = self.staging_root / mf.relative
            if dest.is_file():
                dest.chmod(0o755)


# ---------------------------------------------------------------------------
# Plan builder (preflight)
# ---------------------------------------------------------------------------


def _recover_incomplete_generation(target_root: Path) -> None:
    journal = target_root.parent / f".{target_root.name}.vyne-generation-journal"
    backup_root = target_root.parent / f".{target_root.name}.vyne-backups"
    if not journal.exists():
        return
    try:
        payload = json.loads(journal.read_text(encoding="utf-8"))
        if payload.get("version") != 1 or payload.get("target") != str(target_root):
            raise RuntimeError("journal identity does not match target")
        records = [JournalRecord(**item) for item in payload.get("records", [])]
        if records and all(record.phase == "committed" for record in records):
            if backup_root.exists():
                shutil.rmtree(backup_root)
            journal.unlink()
            return
        for record in reversed(records):
            if record.restored:
                continue
            dest = target_root / record.original
            if record.created:
                if dest.exists():
                    dest.unlink()
                continue
            if record.backup is None:
                continue
            backup = backup_root / record.backup
            if not backup.exists():
                # A prepared record may not have performed its destructive rename.
                if record.phase == "prepared" and dest.exists():
                    continue
                raise RuntimeError(f"missing backup {backup}")
            if dest.exists():
                dest.unlink()
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.rename(backup, dest)
            if record.mode is not None:
                dest.chmod(record.mode)
            if hashlib.sha256(dest.read_bytes()).hexdigest() != record.digest:
                raise RuntimeError(f"digest mismatch restoring {dest}")
        if backup_root.exists():
            shutil.rmtree(backup_root)
        journal.unlink()
    except Exception as exc:
        raise RuntimeError(
            f"Incomplete generation requires manual recovery; journal preserved at "
            f"{journal}: {exc}"
        ) from exc


@dataclass
class PlanBuilder:
    """Gathers ManagedFile entries and preflights every conflict before
    staging.  Also records target snapshots for late-conflict detection."""
    target_root: Path
    files: list[ManagedFile] = field(default_factory=list)
    _staging_root: Path | None = field(default=None, repr=False)
    _snapshots: dict[str, bytes | None] = field(
        default_factory=dict, repr=False,
    )

    # Path validation
    _ESCAPE_SEGMENT: str = ".."

    def add_file(
        self,
        relative: str,
        content: str | bytes,
        policy: ConflictPolicy = ConflictPolicy.ERROR,
        executable: bool = False,
    ) -> None:
        """Stage a file.  Strings are UTF-8 encoded.

        The destination is checked immediately for ERROR conflicts.
        For SKIP/REPLACE, conflicts are handled at staging time.
        """
        self._validate_relative(relative)
        data = content.encode("utf-8") if isinstance(content, str) else content
        dest = self.target_root / relative

        # Record a target snapshot for late-conflict detection
        self._snapshot_dest(relative)

        if self._should_skip(dest, data, policy):
            return

        self.files.append(ManagedFile(
            relative=relative,
            content=data,
            policy=policy,
            executable=executable,
        ))

    def preflight(self) -> GenerationPlan:
        """Phase 1-2: create staging root, copy all files with final modes,
        and record target snapshots for revalidation.

        Returns the GenerationPlan ready to apply.  Nothing in the target
        root has been modified yet.

        Raises ``RuntimeError`` if called more than once.
        """
        if self._staging_root is not None:
            raise RuntimeError("preflight already called")
        _recover_incomplete_generation(self.target_root)

        # Phase 1: validate all paths (no escapes)
        for mf in self.files:
            self._validate_relative(mf.relative)

        # Phase 2: stage everything
        # Ensure the parent of the target root exists so staging can be
        # created alongside it.
        self.target_root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(mkdtemp(
            prefix=".vyne-stage-",
            dir=str(self.target_root.parent),
        ))
        self._staging_root = staging

        # Files that must be executable after placement.
        _EXECUTABLE_FILES = frozenset({
            "android/gradlew",
            "gradlew",
        })

        for mf in self.files:
            if mf.content is not None:
                dest = staging / mf.relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(mf.content)
                # Set executable bits in staging (not after publish)
                if mf.executable or mf.relative in _EXECUTABLE_FILES:
                    if dest.is_file():
                        dest.chmod(0o755)

        # Ensure snapshots cover every managed path
        for mf in self.files:
            if mf.relative not in self._snapshots:
                self._snapshot_dest(mf.relative)

        return GenerationPlan(
            target_root=self.target_root,
            staging_root=staging,
            files=list(self.files),
            _target_snapshots=dict(self._snapshots),
        )

    # --- internal ---

    def _validate_relative(self, relative: str) -> None:
        """Reject paths that escape the target root via ``..`` segments,
        absolute paths, or symlink intermediates in parent components."""
        if not relative or relative.startswith("/"):
            raise RuntimeError(
                f"Managed file path must be relative: {relative!r}"
            )
        parts = relative.replace("\\", "/").split("/")
        if self._ESCAPE_SEGMENT in parts:
            raise RuntimeError(
                f"Managed file path must not escape target root: {relative!r}"
            )
        # Check that no parent component (through which the path passes)
        # is a symlink that points outside the target root.
        current = self.target_root
        for part in parts[:-1]:  # all but the final file/dir name
            current = current / part
            if current.is_symlink():
                resolved = current.resolve()
                try:
                    resolved.relative_to(self.target_root)
                except ValueError:
                    raise RuntimeError(
                        f"Managed path {relative!r} traverses a symlink "
                        f"({current}) that resolves outside the target root "
                        f"({self.target_root})"
                    )

    def _snapshot_dest(self, relative: str) -> None:
        """Record the current bytes of a managed destination file, or None
        if it does not exist."""
        dest = self.target_root / relative
        if dest.is_file():
            self._snapshots[relative] = dest.read_bytes()
        else:
            self._snapshots[relative] = None

    def _should_skip(
        self,
        dest: Path,
        desired: bytes,
        policy: ConflictPolicy,
    ) -> bool:
        """Return True if this file should not be staged (e.g. SKIP with
        existing file, or ERROR with byte-identical content).

        Raises RuntimeError for ERROR on a real conflict.
        """
        if not dest.exists():
            return False
        if policy == ConflictPolicy.REPLACE:
            return False
        if policy == ConflictPolicy.SKIP:
            return True
        # ERROR policy
        existing = dest.read_bytes() if dest.is_file() else b""
        if existing == desired:
            return True  # byte-identical, no conflict
        raise RuntimeError(
            f"Refusing to overwrite existing file: {dest}. "
            f"Use --force to replace."
        )
