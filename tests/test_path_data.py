from __future__ import annotations

import unittest

from vyne.path_data import compile_path_data


class PathDataTests(unittest.TestCase):
    def test_supported_commands_and_repeated_coordinates_are_lowered(self):
        commands = compile_path_data(
            "M 0 0 10 10 L 20 20 C 1 2 3 4 5 6 Q 7 8 9 10 Z"
        )

        self.assertEqual(
            [command["cmd"] for command in commands],
            ["M", "L", "L", "C", "Q", "Z"],
        )
        self.assertEqual(commands[3]["values"], [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])

    def test_relative_commands_and_compact_number_separators_work(self):
        commands = compile_path_data("m10-10 l.5e1-.25 z")

        self.assertEqual(commands[0], {"cmd": "m", "values": [10.0, -10.0]})
        self.assertEqual(commands[1], {"cmd": "l", "values": [5.0, -0.25]})
        self.assertEqual(commands[2], {"cmd": "z", "values": []})

    def test_commands_can_be_separated_by_commas(self):
        self.assertEqual(
            compile_path_data("M0,0L1,2"),
            [
                {"cmd": "M", "values": [0.0, 0.0]},
                {"cmd": "L", "values": [1.0, 2.0]},
            ],
        )

    def test_path_must_start_with_a_command(self):
        with self.assertRaisesRegex(ValueError, "begin with a command"):
            compile_path_data("1 2")

    def test_empty_path_is_rejected(self):
        for value in ("", "   ", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "non-empty"):
                    compile_path_data(value)

    def test_missing_coordinates_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "incomplete coordinates"):
            compile_path_data("M 1")
        with self.assertRaisesRegex(ValueError, "incomplete coordinates"):
            compile_path_data("C 1 2")

    def test_unsupported_syntax_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported path syntax"):
            compile_path_data("M0 0 H10 10")
        with self.assertRaisesRegex(ValueError, "Unsupported path syntax"):
            compile_path_data("M0 0;L1 1")

    def test_non_finite_coordinates_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            compile_path_data("M1e309 0")


if __name__ == "__main__":
    unittest.main()
