from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "run_generated_project_smoke.py"
)
SPEC = importlib.util.spec_from_file_location(
    "run_generated_project_smoke",
    SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


class GeneratedProjectSmokeRunnerTests(unittest.TestCase):
    def test_missing_command_is_a_failed_gate_not_an_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            result = SMOKE.run_gate(
                "missing",
                [str(Path(directory) / "does-not-exist")],
                cwd=Path(directory),
                env={},
            )

        self.assertEqual(result["name"], "missing")
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_finish_persists_truthful_failure_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with redirect_stdout(io.StringIO()):
                exit_code = SMOKE.finish(
                    [
                        {"name": "first", "ok": True},
                        {"name": "second", "ok": False},
                    ],
                    root,
                )
            evidence = json.loads(
                (root / "smoke-results.json").read_text(encoding="utf-8")
            )

        self.assertEqual(exit_code, 1)
        self.assertFalse(evidence["ok"])
        self.assertEqual([gate["name"] for gate in evidence["gates"]], [
            "first",
            "second",
        ])


if __name__ == "__main__":
    unittest.main()
