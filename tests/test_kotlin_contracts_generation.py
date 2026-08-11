"""Kotlin contract-generation drift tests (KOTLIN-SCHEMA-01).

Verifies that the checked-in Android ``ElementContracts.kt`` is regenerated
from ``vyne.spec.schema_v2`` and has not drifted.  The Kotlin contracts are
produced by ``tools/generate_schema.py``; ``--check`` compares without
writing anything, so this test never creates build artifacts.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "tools" / "generate_schema.py"
OUTPUT = (
    REPO_ROOT
    / "android"
    / "host"
    / "src"
    / "main"
    / "java"
    / "dev"
    / "vyne"
    / "generated"
    / "ElementContracts.kt"
)


def _run_check() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


class KotlinContractGenerationTests(unittest.TestCase):
    """The generated Kotlin contracts match the schema authority."""

    def test_generator_script_exists(self) -> None:
        self.assertTrue(GENERATOR.is_file(), "tools/generate_schema.py missing")
        self.assertTrue(OUTPUT.is_file(), "ElementContracts.kt missing")

    def test_kotlin_contracts_are_up_to_date(self) -> None:
        """``--check`` is the CI gate: drift must fail the suite loudly.

        When the schema gains or changes a prop/event, run
        ``python tools/generate_schema.py`` and commit the regenerated
        ``ElementContracts.kt``.
        """
        result = _run_check()
        self.assertEqual(
            result.returncode,
            0,
            "Kotlin ElementContracts drifted from vyne.spec.schema_v2; "
            f"run: python tools/generate_schema.py\n{result.stdout}{result.stderr}",
        )
        # --check never writes: the generator only compares.
        self.assertNotIn(
            "Wrote",
            result.stdout,
            "--check must not write the output file",
        )

    def test_generated_file_embeds_the_schema_hash(self) -> None:
        import hashlib

        from vyne.spec import schema_v2

        source = Path(schema_v2.__file__).read_bytes()
        expected_hash = hashlib.sha256(source).hexdigest()[:16]
        text = OUTPUT.read_text(encoding="utf-8")
        self.assertIn(f"hash={expected_hash}", text)


if __name__ == "__main__":
    unittest.main()
