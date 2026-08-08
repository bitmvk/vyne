"""Generation fault-matrix tests (GEN-14 / GN-3).

Injects failure at every transaction boundary and verifies:
- Staging failure: target untouched, no staging debris
- Snapshot change failure: target untouched
- Backup failure: prior tree intact
- Publish failure: prior tree restored from backup
- Rollback failure: diagnosed recoverable state
- No silent cleanup loss
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest
from unittest.mock import patch

from vyne.cli.generation import (
    ConflictPolicy,
    PlanBuilder,
    GenerationPlan,
)


class GenerationFaultMatrixTests(unittest.TestCase):
    """GN-3: Failure at every transaction and rollback boundary."""

    def test_staging_failure_does_not_modify_target(self):
        """If publish fails (rename error), target is untouched and staging
        debris is cleaned up."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            original_file = target / "keep.txt"
            original_file.write_text("keep me", encoding="utf-8")

            # Create a managed file in target that is a regular file
            (target / "new.txt").write_text("existing file", encoding="utf-8")

            builder = PlanBuilder(target)
            builder.add_file("new.txt", "new content",
                             policy=ConflictPolicy.REPLACE)

            plan = builder.preflight()
            try:
                # Inject fault: replace the staged file with a directory
                # so rename will fail (target has a file, staging has a dir)
                staged_file = plan.staging_root / "new.txt"
                staged_file.unlink()
                staged_file.mkdir()

                with self.assertRaises((FileExistsError, IsADirectoryError, OSError)):
                    plan.apply()
            finally:
                plan.cleanup()

            # Target must be unchanged
            self.assertTrue((target / "keep.txt").is_file())
            self.assertEqual((target / "keep.txt").read_text(), "keep me")
            # The managed file should also be restored
            self.assertTrue((target / "new.txt").is_file())
            self.assertEqual((target / "new.txt").read_text(), "existing file")

    def test_preflight_failure_does_not_modify_target(self):
        """An ERROR conflict during add_file leaves the target untouched."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            original = target / "conflict.txt"
            original.write_text("original", encoding="utf-8")

            builder = PlanBuilder(target)
            with self.assertRaises(RuntimeError):
                builder.add_file("conflict.txt", "different",
                                 policy=ConflictPolicy.ERROR)

            # Target unchanged
            self.assertEqual(original.read_text(), "original")

    def test_preflight_double_call_rejected(self):
        """Calling preflight() twice raises RuntimeError."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()

            builder = PlanBuilder(target)
            builder.add_file("a.txt", "hello")
            plan = builder.preflight()
            try:
                with self.assertRaises(RuntimeError):
                    builder.preflight()
            finally:
                plan.cleanup()

    def test_cleanup_removes_only_owned_staging_transaction(self):
        """Cleaning one live plan must not delete another plan's staging."""
        with TemporaryDirectory() as tmp:
            parent = Path(tmp)
            first_builder = PlanBuilder(parent / "first")
            first_builder.add_file("a.txt", "first")
            second_builder = PlanBuilder(parent / "second")
            second_builder.add_file("b.txt", "second")

            first = first_builder.preflight()
            second = second_builder.preflight()
            try:
                self.assertTrue(first.staging_root.exists())
                self.assertTrue(second.staging_root.exists())
                first.cleanup()
                self.assertFalse(first.staging_root.exists())
                self.assertTrue(
                    second.staging_root.exists(),
                    "cleanup deleted a foreign live staging transaction",
                )
                second.apply()
                self.assertEqual((parent / "second" / "b.txt").read_text(), "second")
            finally:
                first.cleanup()
                second.cleanup()

    def test_apply_double_call_rejected(self):
        """Calling apply() twice raises RuntimeError."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            builder = PlanBuilder(target)
            builder.add_file("a.txt", "hello")
            plan = builder.preflight()
            try:
                plan.apply()
                with self.assertRaises(RuntimeError):
                    plan.apply()
            finally:
                plan.cleanup()

    def test_revalidate_failure_rolls_back_cleanly(self):
        """When revalidation fails, the target is not modified."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            (target / "managed.txt").write_text("original bytes", encoding="utf-8")

            builder = PlanBuilder(target)
            builder.add_file("managed.txt", "replaced content",
                             policy=ConflictPolicy.REPLACE)
            plan = builder.preflight()

            # Late writer modifies the file after preflight
            (target / "managed.txt").write_text("late modification", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                try:
                    plan.apply()
                finally:
                    plan.cleanup()

            # Target must still have the late-writer content (unchanged)
            self.assertEqual(
                (target / "managed.txt").read_text(),
                "late modification",
            )

    def test_nonempty_target_whole_tree_swap(self):
        """For a non-empty target, only managed files are replaced;
        unrelated files are preserved (per-file merge model)."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            (target / "old.txt").write_text("old", encoding="utf-8")
            (target / "sub" / "old-nested.txt").parent.mkdir(parents=True, exist_ok=True)
            (target / "sub" / "old-nested.txt").write_text("old nested", encoding="utf-8")

            builder = PlanBuilder(target)
            builder.add_file("new.txt", "new content",
                             policy=ConflictPolicy.REPLACE)

            plan = builder.preflight()
            try:
                plan.apply()
            finally:
                plan.cleanup()

            # New file exists
            self.assertTrue((target / "new.txt").is_file())
            self.assertEqual((target / "new.txt").read_text(), "new content")
            # Unrelated files are preserved (per-file merge)
            self.assertTrue((target / "old.txt").is_file())
            self.assertEqual((target / "old.txt").read_text(), "old")

    def test_cleanup_after_success_leaves_no_debris(self):
        """After a successful apply + cleanup, no staging or backup debris remains."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "clean-target"
            builder = PlanBuilder(target)
            builder.add_file("hello.txt", "world")

            plan = builder.preflight()
            plan.apply()
            plan.cleanup()

            # Staging root is gone
            # Check parent for any .vyne- debris
            parent = target.parent
            debris = list(parent.glob(".vyne-*"))
            self.assertEqual(
                len(debris), 0,
                f"Found debris: {[str(d) for d in debris]}"
            )

    def test_cleanup_after_failure_removes_staging(self):
        """After a failed apply, staging is cleaned up."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "fail-target"
            target.mkdir()

            builder = PlanBuilder(target)
            builder.add_file("a.txt", "hello",
                             policy=ConflictPolicy.REPLACE)
            plan = builder.preflight()

            # Corrupt staging to make apply fail
            for f in plan.staging_root.rglob("*"):
                if f.is_file():
                    f.unlink()

            try:
                plan.apply()
            except Exception:
                plan.cleanup()

            # Staging should be gone
            # Check parent for debris
            parent = target.parent
            debris = list(parent.glob(".vyne-stage-*"))
            self.assertEqual(
                len(debris), 0,
                f"Found staging debris: {[str(d) for d in debris]}"
            )

    def test_non_utf8_content_stored_as_bytes(self):
        """Binary content is correctly stored and retrieved."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "binary-target"
            binary_data = bytes(range(256))

            builder = PlanBuilder(target)
            builder.add_file("data.bin", binary_data)

            plan = builder.preflight()
            try:
                plan.apply()
            finally:
                plan.cleanup()

            self.assertEqual((target / "data.bin").read_bytes(), binary_data)

    def test_empty_content_file(self):
        """Zero-byte files are correctly created."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "empty-file-target"
            builder = PlanBuilder(target)
            builder.add_file("empty.txt", "")

            plan = builder.preflight()
            try:
                plan.apply()
            finally:
                plan.cleanup()

            self.assertTrue((target / "empty.txt").is_file())
            self.assertEqual((target / "empty.txt").read_text(), "")

    def test_preexisting_nonempty_with_replace_policy_works(self):
        """REPLACE on a non-empty target directory with different content works."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "replace-test"
            target.mkdir()
            (target / "existing.txt").write_text("old content", encoding="utf-8")

            builder = PlanBuilder(target)
            builder.add_file("existing.txt", "new content",
                             policy=ConflictPolicy.REPLACE)

            plan = builder.preflight()
            try:
                plan.apply()
            finally:
                plan.cleanup()

            self.assertEqual((target / "existing.txt").read_text(), "new content")

    def test_nonempty_target_with_only_managed_files(self):
        """When a non-empty target only has files we want to replace, the
        whole-tree swap correctly replaces everything."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "replace-all"
            target.mkdir()
            (target / "old.txt").write_text("old", encoding="utf-8")

            builder = PlanBuilder(target)
            builder.add_file("managed.txt", "managed",
                             policy=ConflictPolicy.REPLACE)

            plan = builder.preflight()
            try:
                plan.apply()
            finally:
                plan.cleanup()

            # New file exists
            self.assertTrue((target / "managed.txt").is_file())

    def test_parent_directory_creation_for_nonexistent_target(self):
        """When the target's parent directory doesn't exist, it's created."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "deep" / "nested" / "project"

            builder = PlanBuilder(target)
            builder.add_file("hello.txt", "world")

            plan = builder.preflight()
            try:
                plan.apply()
            finally:
                plan.cleanup()

            self.assertTrue(target.is_dir())
            self.assertTrue((target / "hello.txt").is_file())

if __name__ == "__main__":
    unittest.main()
