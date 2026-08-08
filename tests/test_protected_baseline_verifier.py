"""Tests for the protected-baseline verifier.

Uses temporary git repositories and schema-v1 fixtures to exercise
strict parsing, hash matching, dirty-path detection, and error paths.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _run_verifier(baseline_path: str, protected_root: str) -> int:
    """Run the verifier script and return its exit code."""
    script = os.path.join(
        os.path.dirname(__file__), "..", "scripts", "verify-protected-baseline.py"
    )
    result = subprocess.run(
        [sys.executable, script, baseline_path, protected_root],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return result.returncode, result.stdout, result.stderr


class TestProtectedBaselineVerifier(unittest.TestCase):
    """Tests for scripts/verify-protected-baseline.py using temporary repos."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.tmpdir.name) / "test-repo"
        self.repo_path.mkdir()
        # Initialize git repo
        subprocess.run(
            ["git", "-C", str(self.repo_path), "init", "-b", "main"],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "-C", str(self.repo_path), "config", "user.email", "test@test"],
            capture_output=True, timeout=5,
        )
        subprocess.run(
            ["git", "-C", str(self.repo_path), "config", "user.name", "Test"],
            capture_output=True, timeout=5,
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_baseline(self, entries: list[dict], **kwargs) -> Path:
        """Write a baseline JSON and return its path."""
        head = kwargs.get("head", "0" * 40)
        branch = kwargs.get("branch", "main")
        git_toplevel = kwargs.get("git_toplevel", str(self.repo_path.resolve()))
        schema_version = kwargs.get("schema_version", 1)

        baseline = {
            "schema_version": schema_version,
            "original_checkout": {
                "git_toplevel": git_toplevel,
                "head": head,
                "branch": branch,
                "inventory_entries": entries,
                "pre_existing_setup_paths": kwargs.get("pre_existing_setup_paths", []),
            },
        }
        path = Path(self.tmpdir.name) / "baseline.json"
        path.write_text(json.dumps(baseline, indent=2))
        return path

    def _add_file(self, rel_path: str, content: str) -> str:
        """Create a file in the test repo and return its SHA256."""
        full = self.repo_path / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        return hashlib.sha256(content.encode()).hexdigest()

    def _make_entry(self, path: str, content: str) -> dict:
        h = hashlib.sha256(content.encode()).hexdigest()
        return {
            "path": path,
            "hashes": {"sha256": h},
            "git_status": {"record_type": "ordinary", "xy": ".M"},
        }

    def test_all_matching_entries_pass(self):
        """Baseline with matching files should pass."""
        content = "hello world"
        self._add_file("a.txt", content)
        # Commit so git tracks the file, then modify so it's dirty
        subprocess.run(
            ["git", "-C", str(self.repo_path), "add", "a.txt"],
            capture_output=True, timeout=5,
        )
        subprocess.run(
            ["git", "-C", str(self.repo_path), "commit", "-m", "init"],
            capture_output=True, timeout=5,
        )
        # Now modify to make it dirty
        modified = "hello world modified"
        (self.repo_path / "a.txt").write_text(modified)
        h = hashlib.sha256(modified.encode()).hexdigest()
        entry = {
            "path": "a.txt",
            "hashes": {"sha256": h},
            "git_status": {"record_type": "ordinary", "xy": ".M"},
        }
        baseline = self._make_baseline([entry])
        rc, stdout, stderr = _run_verifier(str(baseline), str(self.repo_path))
        self.assertEqual(rc, 0, f"stderr: {stderr}")
        self.assertIn("OK", stdout)

    def test_missing_entry_fails(self):
        """A captured entry whose file is missing should fail."""
        entry = {
            "path": "b.txt",
            "hashes": {"sha256": "0" * 64},
        }
        baseline = self._make_baseline([entry])
        rc, stdout, stderr = _run_verifier(str(baseline), str(self.repo_path))
        self.assertNotEqual(rc, 0)
        self.assertIn("MISSING", stderr)

    def test_changed_entry_fails(self):
        """A captured entry whose content changed should fail."""
        content = "original"
        h_orig = hashlib.sha256(content.encode()).hexdigest()
        self._add_file("c.txt", content)
        entry = {
            "path": "c.txt",
            "hashes": {"sha256": h_orig},
        }
        baseline = self._make_baseline([entry])
        # Modify the file
        (self.repo_path / "c.txt").write_text("modified")
        rc, stdout, stderr = _run_verifier(str(baseline), str(self.repo_path))
        self.assertNotEqual(rc, 0)
        self.assertIn("CHANGED", stderr)

    def test_new_dirty_path_fails(self):
        """A file not in the captured set that shows up dirty should fail."""
        content = "captured"
        h = hashlib.sha256(content.encode()).hexdigest()
        self._add_file("d.txt", content)
        entry = {
            "path": "d.txt",
            "hashes": {"sha256": h},
        }
        baseline = self._make_baseline([entry])
        # Create a new dirty file and stage it
        new_file = self.repo_path / "e.txt"
        new_file.write_text("new dirty")
        subprocess.run(
            ["git", "-C", str(self.repo_path), "add", "e.txt"],
            capture_output=True, timeout=5,
        )
        rc, stdout, stderr = _run_verifier(str(baseline), str(self.repo_path))
        self.assertNotEqual(rc, 0)
        self.assertIn("NEW DIRTY PATH", stderr)

    def test_malformed_schema_fails(self):
        """Malformed JSON schema should fail."""
        bad = self.tmpdir.name + "/bad.json"
        Path(bad).write_text("{not valid json")
        rc, stdout, stderr = _run_verifier(bad, str(self.repo_path))
        self.assertNotEqual(rc, 0)
        self.assertIn("not valid JSON", stderr)

    def test_missing_schema_version_fails(self):
        """Baseline without schema_version should fail."""
        path = Path(self.tmpdir.name) / "no-version.json"
        path.write_text(json.dumps({"original_checkout": {"inventory_entries": []}}))
        rc, stdout, stderr = _run_verifier(str(path), str(self.repo_path))
        self.assertNotEqual(rc, 0)

    def test_non_existent_root_fails(self):
        """Non-existent protected root should fail."""
        baseline = self._make_baseline([])
        rc, stdout, stderr = _run_verifier(
            str(baseline), "/nonexistent/path/12345"
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("not a directory", stderr)

    def test_multiple_entries_verified(self):
        """Multiple captured entries should all be verified."""
        contents = {"f1.txt": "alpha", "f2.txt": "beta", "sub/f3.txt": "gamma"}
        for path, content in contents.items():
            self._add_file(path, content)
        subprocess.run(
            ["git", "-C", str(self.repo_path), "add", "."],
            capture_output=True, timeout=5,
        )
        subprocess.run(
            ["git", "-C", str(self.repo_path), "commit", "-m", "init"],
            capture_output=True, timeout=5,
        )
        # Modify all files to make them dirty
        entries = []
        for path, content in contents.items():
            modified = content + "_modified"
            (self.repo_path / path).write_text(modified)
            h = hashlib.sha256(modified.encode()).hexdigest()
            entries.append({
                "path": path,
                "hashes": {"sha256": h},
                "git_status": {"record_type": "ordinary", "xy": ".M"},
            })
        baseline = self._make_baseline(entries)
        rc, stdout, stderr = _run_verifier(str(baseline), str(self.repo_path))
        self.assertEqual(rc, 0, f"stderr: {stderr}")
        self.assertIn("3 captured entries", stdout)


if __name__ == "__main__":
    unittest.main()
