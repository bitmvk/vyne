#!/usr/bin/env python3
"""Verify the protected original checkout against its canonical inventory schema.

Reads a baseline JSON (schema-versioned inventory with original_checkout
metadata) and compares every captured inventory entry against the current
state of the protected checkout.  Exits 0 only when every inventory entry
matches and no new dirty paths are detected.

The canonical schema stores checkout identity/status under
``original_checkout`` and captured entries under
``original_checkout.inventory_entries``.  This verifier parses that exact
schema and performs no checkout, index, ref, or file mutation.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def _hash_file(path: Path) -> str:
    """Return the SHA-256 hex digest of *path* contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _load_baseline(baseline_path: Path) -> dict:
    """Load and minimally validate the baseline JSON structure."""
    if not baseline_path.exists():
        print(f"ERROR: baseline file not found: {baseline_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(baseline_path) as f:
            baseline = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"ERROR: baseline is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    schema_version = baseline.get("schema_version")
    if not isinstance(schema_version, int) or schema_version < 1:
        print(
            f"ERROR: baseline schema_version must be an integer >= 1, "
            f"got {schema_version!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    oc = baseline.get("original_checkout")
    if not isinstance(oc, dict):
        print(
            "ERROR: baseline missing or invalid 'original_checkout' object",
            file=sys.stderr,
        )
        sys.exit(1)

    required_meta = ["git_toplevel", "head", "branch", "inventory_entries"]
    for key in required_meta:
        if key not in oc:
            print(
                f"ERROR: baseline original_checkout missing required key {key!r}",
                file=sys.stderr,
            )
            sys.exit(1)

    entries = oc["inventory_entries"]
    if not isinstance(entries, list):
        print(
            "ERROR: baseline inventory_entries must be a list",
            file=sys.stderr,
        )
        sys.exit(1)

    return baseline


def _validate_entry(entry: dict, idx: int) -> str | None:
    """Validate one inventory entry has required fields.  Returns error or None."""
    required = ["path", "hashes"]
    for key in required:
        if key not in entry:
            return f"inventory_entries[{idx}] missing required key {key!r}"
    hashes = entry["hashes"]
    if not isinstance(hashes, dict) or "sha256" not in hashes:
        return f"inventory_entries[{idx}].hashes missing sha256"
    path_val = entry["path"]
    if not isinstance(path_val, str) or not path_val:
        return f"inventory_entries[{idx}].path must be a non-empty string"
    return None


def _current_git_dirty_paths(git_toplevel: str) -> set[str] | None:
    """Get the set of dirty (modified/untracked) paths from git status.

    Returns None if git is unavailable or fails.
    """
    try:
        result = subprocess.run(
            ["git", "-C", git_toplevel, "status", "--porcelain=v2", "-z",
             "--ignore-submodules", "--untracked-files=normal"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        records = result.stdout.split("\0")
        paths: set[str] = set()
        for rec in records:
            if not rec.strip():
                continue
            # porcelain-v2 format: lines starting with # are headers,
            # ordinary entries have path at field index 8 (0-based)
            if rec.startswith("#"):
                continue
            fields = rec.split(" ", 8)
            if len(fields) >= 9:
                path = fields[8].rstrip("\0")
                paths.add(path)
        return paths
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return None


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "Usage: verify-protected-baseline.py <baseline.json> <protected-root>",
            file=sys.stderr,
        )
        return 2

    baseline_path = Path(sys.argv[1])
    protected_root = Path(sys.argv[2])

    if not protected_root.is_dir():
        print(f"ERROR: protected root not a directory: {protected_root}", file=sys.stderr)
        return 1

    baseline = _load_baseline(baseline_path)
    oc = baseline["original_checkout"]
    entries = oc["inventory_entries"]

    # Validate git_toplevel matches
    captured_toplevel = oc.get("git_toplevel", "")
    if captured_toplevel:
        real_toplevel = str(protected_root.resolve())
        if real_toplevel != captured_toplevel:
            print(
                f"ERROR: git_toplevel mismatch: baseline has {captured_toplevel!r}, "
                f"but protected root resolves to {real_toplevel!r}",
                file=sys.stderr,
            )
            return 1

    errors: list[str] = []

    # Validate all entries have required fields
    for i, entry in enumerate(entries):
        err = _validate_entry(entry, i)
        if err:
            errors.append(f"SCHEMA ERROR: {err}")

    # Build captured path set
    captured_paths: set[str] = set()
    for entry in entries:
        captured_paths.add(entry["path"])

    # Check each captured entry: file must exist and hash must match
    for entry in entries:
        rel_path = entry["path"]
        expected_hash = entry["hashes"]["sha256"]
        full_path = protected_root / rel_path

        if not full_path.exists():
            errors.append(f"MISSING: {rel_path}")
            continue

        if not full_path.is_file():
            errors.append(f"NOT A FILE: {rel_path}")
            continue

        current_hash = _hash_file(full_path)
        if current_hash != expected_hash:
            errors.append(f"CHANGED: {rel_path} (SHA256 mismatch)")

    # Compare current git dirty paths against captured set
    git_toplevel = captured_toplevel or str(protected_root.resolve())
    current_dirty = _current_git_dirty_paths(git_toplevel)
    if current_dirty is None:
        errors.append("GIT ERROR: unable to run git status for dirty-path comparison")
    else:
        new_dirty = current_dirty - captured_paths
        # Also accept pre_existing_setup_paths as known
        pre_existing = set(oc.get("pre_existing_setup_paths", []))
        truly_new = new_dirty - pre_existing

        for path in sorted(truly_new):
            errors.append(f"NEW DIRTY PATH: {path}")

        # Paths that were captured as dirty but are now clean
        # Files captured as "untracked" may legitimately be deleted by owner.
        # Only flag files whose captured git_status indicates tracked modification
        # (ordinary + worktree-modified), since those should remain dirty.
        missing_dirty = captured_paths - current_dirty
        for path in sorted(missing_dirty):
            entry = next((e for e in entries if e["path"] == path), None)
            if entry:
                gs = entry.get("git_status", {})
                record_type = gs.get("record_type", "")
                xy = gs.get("xy", "")
                # Only flag if this was a tracked file with worktree changes
                # (ordinary record type with non-empty xy that indicates modification)
                if record_type == "ordinary" and xy and xy != "..":
                    errors.append(
                        f"DIRTY RESOLVED: {path} (was modified, now clean)"
                    )

    if errors:
        print("PROTECTED BASELINE VIOLATION:", file=sys.stderr)
        for err in errors[:50]:
            print(f"  {err}", file=sys.stderr)
        if len(errors) > 50:
            print(f"  ... and {len(errors) - 50} more", file=sys.stderr)
        return 1

    print(
        f"Protected baseline OK: {len(entries)} captured entries verified "
        f"against {protected_root}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
