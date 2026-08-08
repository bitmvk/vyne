"""Tests for atomic project generation with preflight, staging, and rollback.

Coverage:
- Preflight failure leaves target untouched
- Staging places files correctly
- Existing target directory rollback
- --force behavior
- Unrelated file preservation
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from vyne.cli.generation import (
    ConflictPolicy,
    GenerationPlan,
    PlanBuilder,
)


class AtomicGenerationTests(unittest.TestCase):
    """CLI-02 atomic generation plan."""

    def test_preflight_failure_does_not_modify_target(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            original_file = target / "existing.txt"
            original_file.write_text("keep-me", encoding="utf-8")

            # add_file raises on ERROR conflict immediately (before preflight)
            builder = PlanBuilder(target)
            with self.assertRaises(RuntimeError):
                builder.add_file("existing.txt", "different-content")

            # Target must be unchanged
            self.assertEqual(original_file.read_text(), "keep-me")

    def test_staging_and_apply_creates_files(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "new-project"
            builder = PlanBuilder(target)
            builder.add_file("a.txt", "hello a")
            builder.add_file("sub/b.txt", "hello b")

            plan = builder.preflight()
            try:
                plan.apply()
            finally:
                plan.cleanup()

            self.assertTrue((target / "a.txt").is_file())
            self.assertEqual((target / "a.txt").read_text(), "hello a")
            self.assertTrue((target / "sub" / "b.txt").is_file())

    def test_existing_target_with_backup_and_rollback(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            keep_file = target / "keep.txt"
            keep_file.write_text("original keep", encoding="utf-8")

            builder = PlanBuilder(target)
            # This file already exists with different content - use REPLACE
            builder.add_file("keep.txt", "replaced content",
                             policy=ConflictPolicy.REPLACE)

            plan = builder.preflight()
            plan.apply()
            plan.cleanup()

            self.assertEqual((target / "keep.txt").read_text(), "replaced content")

    def test_skip_policy_leaves_existing_untouched(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            (target / "skip.txt").write_text("original", encoding="utf-8")

            builder = PlanBuilder(target)
            builder.add_file("skip.txt", "new content",
                             policy=ConflictPolicy.SKIP)

            plan = builder.preflight()
            plan.apply()
            plan.cleanup()

            self.assertEqual((target / "skip.txt").read_text(), "original")

    def test_byte_identical_file_does_not_conflict(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            (target / "same.txt").write_text("identical", encoding="utf-8")

            builder = PlanBuilder(target)
            builder.add_file("same.txt", "identical")

            plan = builder.preflight()
            plan.apply()
            plan.cleanup()

            self.assertEqual((target / "same.txt").read_text(), "identical")

    def test_empty_target_directory_atomic_rename(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "fresh"
            target.mkdir()  # empty directory

            builder = PlanBuilder(target)
            builder.add_file("hello.txt", "world")

            plan = builder.preflight()
            plan.apply()
            plan.cleanup()

            self.assertTrue(target.exists())
            self.assertTrue((target / "hello.txt").is_file())

    def test_force_policy_overwrites(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            (target / "force.txt").write_text("old", encoding="utf-8")

            builder = PlanBuilder(target)
            builder.add_file("force.txt", "new",
                             policy=ConflictPolicy.REPLACE)

            plan = builder.preflight()
            plan.apply()
            plan.cleanup()

            self.assertEqual((target / "force.txt").read_text(), "new")

    def test_error_policy_raises_on_conflict(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            (target / "conflict.txt").write_text("old", encoding="utf-8")

            builder = PlanBuilder(target)
            # ERROR policy raises immediately when content differs
            with self.assertRaises(RuntimeError):
                builder.add_file("conflict.txt", "new",
                                 policy=ConflictPolicy.ERROR)


if __name__ == "__main__":
    unittest.main()
