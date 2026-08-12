"""Generation transaction contract tests (GEN-14 / GN-1, GN-2).

Verifies the empty-target rule and atomic publish:
- Fresh and empty targets receive exact desired bytes/modes
- Non-empty targets are refused unless ``force`` replaces them entirely
- Path escapes are rejected
- No staging debris after success or failure
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import stat
import unittest

from vyne.cli.generation import PlanBuilder


class GenerationTransactionTests(unittest.TestCase):
    """GN-1: Empty-target rule and atomic publish."""

    def test_fresh_target_creates_files_with_exact_content(self):
        """A new (non-existent) target receives exact desired bytes."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "fresh-project"
            builder = PlanBuilder(target)
            builder.add_file("a.txt", "hello a")
            builder.add_file("sub/b.txt", "hello b")

            plan = builder.preflight()
            try:
                plan.apply()
            finally:
                plan.cleanup()

            self.assertTrue(target.is_dir())
            self.assertEqual((target / "a.txt").read_text(), "hello a")
            self.assertEqual((target / "sub" / "b.txt").read_text(), "hello b")

    def test_empty_target_directory_is_treated_as_fresh(self):
        """An empty existing directory receives files."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "empty-dir"
            target.mkdir()

            builder = PlanBuilder(target)
            builder.add_file("hello.txt", "world")

            plan = builder.preflight()
            try:
                plan.apply()
            finally:
                plan.cleanup()

            self.assertTrue((target / "hello.txt").is_file())
            self.assertEqual((target / "hello.txt").read_text(), "world")

    def test_nonempty_target_refused_without_force(self):
        """A non-empty target is refused: no merging, no partial writes."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            (target / "notes.txt").write_text("keep me", encoding="utf-8")

            builder = PlanBuilder(target)
            builder.add_file("new.txt", "new content")

            plan = builder.preflight()
            try:
                with self.assertRaisesRegex(RuntimeError, "non-empty"):
                    plan.apply()
            finally:
                plan.cleanup()

            # Target is untouched: no merge of new files, no lost files.
            self.assertFalse((target / "new.txt").exists())
            self.assertEqual((target / "notes.txt").read_text(), "keep me")

    def test_force_replaces_nonempty_target_entirely(self):
        """force replaces the whole tree, including unrelated files."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            (target / "old.txt").write_text("old", encoding="utf-8")

            builder = PlanBuilder(target)
            builder.add_file("new.txt", "new content")

            plan = builder.preflight()
            try:
                plan.apply(force=True)
            finally:
                plan.cleanup()

            self.assertTrue((target / "new.txt").is_file())
            self.assertEqual((target / "new.txt").read_text(), "new content")
            self.assertFalse((target / "old.txt").exists())

    def test_force_refuses_file_target(self):
        """A regular-file target is never a valid generation target."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "not-a-dir"
            target.write_text("file", encoding="utf-8")

            builder = PlanBuilder(target)
            builder.add_file("a.txt", "hello")

            plan = builder.preflight()
            try:
                with self.assertRaisesRegex(RuntimeError, "not a directory"):
                    plan.apply(force=True)
            finally:
                plan.cleanup()

            self.assertEqual(target.read_text(encoding="utf-8"), "file")

    def test_force_refuses_symlink_target(self):
        """Generation never follows a symlink target."""
        with TemporaryDirectory() as tmp:
            real = Path(tmp) / "real"
            real.mkdir()
            target = Path(tmp) / "link"
            target.symlink_to(real)

            builder = PlanBuilder(target)
            builder.add_file("a.txt", "hello")

            plan = builder.preflight()
            try:
                with self.assertRaisesRegex(RuntimeError, "symlink"):
                    plan.apply(force=True)
            finally:
                plan.cleanup()

    def test_idempotent_generation(self):
        """Regenerating the same content into a fresh target is identical."""
        with TemporaryDirectory() as tmp:
            targets = [Path(tmp) / "idempotent1", Path(tmp) / "idempotent2"]
            for target in targets:
                builder = PlanBuilder(target)
                builder.add_file("a.txt", "hello")
                builder.add_file("sub/b.txt", "world")
                plan = builder.preflight()
                try:
                    plan.apply()
                finally:
                    plan.cleanup()

            self.assertEqual(
                (targets[0] / "a.txt").read_bytes(),
                (targets[1] / "a.txt").read_bytes(),
            )

    def test_executable_bit_set_on_gradlew(self):
        """gradlew files get 0o755 mode during staging."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "exec-target"

            builder = PlanBuilder(target)
            builder.add_file("gradlew", "#!/bin/bash\necho hi\n")

            plan = builder.preflight()
            try:
                plan.apply()
            finally:
                plan.cleanup()

            gradlew = target / "gradlew"
            self.assertTrue(gradlew.is_file())
            file_mode = gradlew.stat().st_mode
            self.assertTrue(file_mode & stat.S_IXUSR, f"gradlew not executable: {oct(file_mode)}")
            self.assertTrue(file_mode & stat.S_IXGRP, f"gradlew not group-executable: {oct(file_mode)}")

    def test_deeply_nested_files(self):
        """Deep nesting creates all intermediate directories."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "deep"
            builder = PlanBuilder(target)
            builder.add_file("a/b/c/d/e/f.txt", "deep")

            plan = builder.preflight()
            try:
                plan.apply()
            finally:
                plan.cleanup()

            self.assertTrue((target / "a" / "b" / "c" / "d" / "e" / "f.txt").is_file())
            self.assertEqual(
                (target / "a" / "b" / "c" / "d" / "e" / "f.txt").read_text(),
                "deep",
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

    # --- GN-2: path validation ---

    def test_absolute_path_rejected(self):
        """Absolute paths are rejected."""
        with TemporaryDirectory() as tmp:
            builder = PlanBuilder(Path(tmp) / "abs-test")
            with self.assertRaises(RuntimeError):
                builder.add_file("/etc/passwd", "bad")

    def test_dotdot_escape_rejected(self):
        """Paths with .. segments are rejected."""
        with TemporaryDirectory() as tmp:
            builder = PlanBuilder(Path(tmp) / "dotdot-test")
            with self.assertRaises(RuntimeError):
                builder.add_file("../outside.txt", "bad")

    def test_dotdot_escape_in_subpath_rejected(self):
        """.. in nested path segments is rejected."""
        with TemporaryDirectory() as tmp:
            builder = PlanBuilder(Path(tmp) / "dotdot-sub-test")
            with self.assertRaises(RuntimeError):
                builder.add_file("sub/../../outside.txt", "bad")

    def test_empty_path_rejected(self):
        """Empty relative path is rejected."""
        with TemporaryDirectory() as tmp:
            builder = PlanBuilder(Path(tmp) / "empty-path-test")
            with self.assertRaises(RuntimeError):
                builder.add_file("", "empty")

    # --- lifecycle guards ---

    def test_preflight_double_call_rejected(self):
        """Calling preflight() twice raises RuntimeError."""
        with TemporaryDirectory() as tmp:
            builder = PlanBuilder(Path(tmp) / "target")
            builder.add_file("a.txt", "hello")
            plan = builder.preflight()
            try:
                with self.assertRaises(RuntimeError):
                    builder.preflight()
            finally:
                plan.cleanup()

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

    def test_cleanup_after_success_leaves_no_debris(self):
        """After a successful apply + cleanup, no staging debris remains."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "clean-target"
            builder = PlanBuilder(target)
            builder.add_file("hello.txt", "world")

            plan = builder.preflight()
            plan.apply()
            plan.cleanup()

            parent = target.parent
            debris = list(parent.glob(".vyne-*"))
            self.assertEqual(
                len(debris), 0,
                f"Found debris: {[str(d) for d in debris]}"
            )

    def test_cleanup_after_failure_removes_staging(self):
        """After a refused apply, staging is cleaned up."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "fail-target"
            target.mkdir()
            (target / "keep.txt").write_text("keep", encoding="utf-8")

            builder = PlanBuilder(target)
            builder.add_file("a.txt", "hello")
            plan = builder.preflight()
            try:
                with self.assertRaises(RuntimeError):
                    plan.apply()
            finally:
                plan.cleanup()

            parent = target.parent
            debris = list(parent.glob(".vyne-stage-*"))
            self.assertEqual(
                len(debris), 0,
                f"Found staging debris: {[str(d) for d in debris]}"
            )


if __name__ == "__main__":
    unittest.main()
