from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_emulator_tests.py"
SPEC = importlib.util.spec_from_file_location("run_emulator_tests", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class AdbDeviceSelectionTests(unittest.TestCase):
    def test_online_devices_ignores_offline_and_unauthorized(self):
        output = """List of devices attached
emulator-5554 device product:sdk model:Pixel_2 transport_id:1
phone-1 offline transport_id:2
phone-2 unauthorized transport_id:3
"""
        self.assertEqual(
            runner.online_devices(output),
            [
                (
                    "emulator-5554",
                    "product:sdk model:Pixel_2 transport_id:1",
                )
            ],
        )

    def test_one_emulator_is_selected_automatically(self):
        selected = runner.select_serial(
            [("emulator-5554", "model:Pixel")],
            None,
            allow_physical=False,
        )
        self.assertEqual(selected, "emulator-5554")

    def test_requested_online_emulator_is_selected(self):
        selected = runner.select_serial(
            [
                ("emulator-5554", ""),
                ("emulator-5556", ""),
            ],
            "emulator-5556",
            allow_physical=False,
        )
        self.assertEqual(selected, "emulator-5556")

    def test_multiple_devices_require_explicit_serial(self):
        with self.assertRaisesRegex(RuntimeError, "--serial"):
            runner.select_serial(
                [("emulator-5554", ""), ("emulator-5556", "")],
                None,
                allow_physical=False,
            )

    def test_missing_requested_device_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "not online"):
            runner.select_serial(
                [("emulator-5554", "")],
                "emulator-9999",
                allow_physical=False,
            )

    def test_no_devices_explains_that_tester_must_start_one(self):
        with self.assertRaisesRegex(RuntimeError, "Start an emulator"):
            runner.select_serial([], None, allow_physical=False)

    def test_physical_device_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(RuntimeError, "--allow-physical"):
            runner.select_serial(
                [("10BF3", "model:Phone")],
                None,
                allow_physical=False,
            )

    def test_physical_device_can_be_explicitly_allowed(self):
        self.assertEqual(
            runner.select_serial(
                [("10BF3", "model:Phone")],
                None,
                allow_physical=True,
            ),
            "10BF3",
        )


class InstrumentationEvidenceTests(unittest.TestCase):
    def test_multiple_class_filters_are_one_gradle_argument(self):
        self.assertEqual(
            runner.test_class_argument(["dev.vyne.One", "dev.vyne.Two"]),
            "-Pandroid.testInstrumentationRunnerArguments.class="
            "dev.vyne.One,dev.vyne.Two",
        )

    def test_empty_class_filter_adds_no_gradle_argument(self):
        self.assertIsNone(runner.test_class_argument([]))

    def test_zero_discovered_tests_cannot_report_success(self):
        self.assertFalse(
            runner.run_succeeded(
                0,
                {"tests": 0, "failures": 0, "errors": 0, "skipped": 0},
            )
        )

    def test_failures_cannot_report_success(self):
        self.assertFalse(
            runner.run_succeeded(
                0,
                {"tests": 4, "failures": 1, "errors": 0, "skipped": 0},
            )
        )

    def test_passing_discovered_tests_report_success(self):
        self.assertTrue(
            runner.run_succeeded(
                0,
                {"tests": 4, "failures": 0, "errors": 0, "skipped": 1},
            )
        )

    def test_xml_counts_are_aggregated_across_devices_and_classes(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "one").mkdir()
            (root / "two").mkdir()
            (root / "one" / "TEST-a.xml").write_text(
                '<testsuite tests="7" failures="1" errors="0" skipped="2">',
                encoding="utf-8",
            )
            (root / "two" / "TEST-b.xml").write_text(
                '<testsuite tests="5" failures="0" errors="1" skipped="0">',
                encoding="utf-8",
            )

            self.assertEqual(
                runner.instrumentation_counts(root),
                {
                    "tests": 12,
                    "failures": 1,
                    "errors": 1,
                    "skipped": 2,
                },
            )

    def test_non_test_xml_is_ignored(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "metadata.xml").write_text(
                "<device><testsuite-not-really tests=\"99\" /></device>",
                encoding="utf-8",
            )
            self.assertEqual(
                runner.instrumentation_counts(root),
                {
                    "tests": 0,
                    "failures": 0,
                    "errors": 0,
                    "skipped": 0,
                },
            )


if __name__ == "__main__":
    unittest.main()
