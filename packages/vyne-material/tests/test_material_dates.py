"""MATERIAL-02: DatePicker and date-range boundary safety.

Tests for:
- Bool/type rejection for year, month, first_weekday
- Selected date type validation
- Date-range ordering and type validation
- Boundary navigation disabled at year 1 and year 9999 limits
- Safe calendar grid without year 0/10000
- All weekdays work at boundaries
"""

from __future__ import annotations

import unittest
from datetime import date

from vyne_material import DatePicker, DateRangePicker


class DatePickerTypeValidationTests(unittest.TestCase):
    """Reject bools and non-ints for year/month/first_weekday."""

    def test_rejects_bool_year(self):
        with self.assertRaises(TypeError):
            DatePicker(year=True, month=1)

    def test_rejects_bool_month(self):
        with self.assertRaises(TypeError):
            DatePicker(year=2026, month=True)

    def test_rejects_bool_first_weekday(self):
        with self.assertRaises(TypeError):
            DatePicker(year=2026, month=7, first_weekday=False)

    def test_rejects_string_year(self):
        with self.assertRaises(TypeError):
            DatePicker(year="2026", month=1)

    def test_rejects_year_and_month_out_of_bounds(self):
        """Year 0/10000 and month 0/13 are rejected."""
        with self.assertRaises(ValueError):
            DatePicker(year=0, month=1)
        with self.assertRaises(ValueError):
            DatePicker(year=10000, month=1)
        with self.assertRaises(ValueError):
            DatePicker(year=2026, month=0)
        with self.assertRaises(ValueError):
            DatePicker(year=2026, month=13)

    def test_accepts_year_boundaries(self):
        """Year 1 and 9999 are valid."""
        self.assertIsNotNone(DatePicker(year=1, month=1))
        self.assertIsNotNone(DatePicker(year=9999, month=11))

    def test_rejects_non_date_selected(self):
        with self.assertRaises(TypeError):
            DatePicker(year=2026, month=7, selected="2026-07-16")

    def test_accepts_none_selected(self):
        picker = DatePicker(year=2026, month=7, selected=None)
        self.assertIsNotNone(picker)

    def test_accepts_valid_date_selected(self):
        picker = DatePicker(year=2026, month=7, selected=date(2026, 7, 16))
        self.assertIsNotNone(picker)

    def test_rejects_invalid_range_type(self):
        with self.assertRaises(TypeError):
            DatePicker(year=2026, month=7, selected_range=(date(2026, 7, 1),))

    def test_rejects_non_date_in_range(self):
        with self.assertRaises(TypeError):
            DatePicker(year=2026, month=7, selected_range=("2026-07-01", None))


class DatePickerBoundaryNavigationTests(unittest.TestCase):
    """Boundary navigation disabled at year limits."""

    def test_prev_disabled_at_year_1_month_1(self):
        picker = DatePicker(year=1, month=1)
        # Header children: [prev_icon, spacer(8,1), title_text, spacer(8,1), next_icon]
        prev_button = picker.children[0].children[0]
        self.assertIsNone(prev_button.props.get("on_click"))
        self.assertFalse(prev_button.props.get("enabled", True))

    def test_next_disabled_at_year_9999_month_12(self):
        picker = DatePicker(year=9999, month=12)
        next_button = picker.children[0].children[4]
        self.assertIsNone(next_button.props.get("on_click"))
        self.assertFalse(next_button.props.get("enabled", True))

    def test_prev_enabled_at_year_2_month_1(self):
        picker = DatePicker(year=2, month=1, on_month_change=lambda ym: None)
        prev_button = picker.children[0].children[0]
        self.assertIsNotNone(prev_button.props.get("on_click"))
        self.assertTrue(prev_button.props.get("enabled", True))

    def test_next_enabled_at_year_9998_month_12(self):
        picker = DatePicker(year=9998, month=12, on_month_change=lambda ym: None)
        next_button = picker.children[0].children[4]
        self.assertIsNotNone(next_button.props.get("on_click"))
        self.assertTrue(next_button.props.get("enabled", True))

    def test_prev_navigates_to_december(self):
        received: list[tuple[int, int]] = []
        picker = DatePicker(year=2, month=1, on_month_change=received.append)
        prev_button = picker.children[0].children[0]
        prev_button.props["on_click"](None)
        self.assertEqual(received, [(1, 12)])

    def test_next_navigates_to_january(self):
        received: list[tuple[int, int]] = []
        picker = DatePicker(year=2026, month=12, on_month_change=received.append)
        next_button = picker.children[0].children[4]
        next_button.props["on_click"](None)
        self.assertEqual(received, [(2027, 1)])


class DatePickerBoundaryGridTests(unittest.TestCase):
    """Safe calendar grid at year boundaries."""

    def test_all_weekdays_work_at_boundaries(self):
        """All first_weekday values 0-6 work at boundary (year, month) pairs."""
        for year, month in ((1, 1), (1, 2), (1, 12), (9999, 11), (9999, 12)):
            for weekday in range(7):
                with self.subTest(year=year, month=month, first_weekday=weekday):
                    picker = DatePicker(year=year, month=month, first_weekday=weekday)
                    self.assertIsNotNone(picker)


class DateRangePickerValidationTests(unittest.TestCase):
    """DateRangePicker validates and orders ranges."""

    def test_accepts_ordered_range(self):
        picker = DateRangePicker(
            year=2026, month=7,
            start=date(2026, 7, 3),
            end=date(2026, 7, 18),
        )
        self.assertIsNotNone(picker)

    def test_rejects_reversed_range(self):
        """start after end is rejected before grid construction."""
        with self.assertRaises(ValueError):
            DateRangePicker(
                year=2026, month=7,
                start=date(2026, 7, 18),
                end=date(2026, 7, 3),
            )

    def test_accepts_open_start(self):
        picker = DateRangePicker(
            year=2026, month=7,
            start=None,
            end=date(2026, 7, 18),
        )
        self.assertIsNotNone(picker)

    def test_accepts_open_end(self):
        picker = DateRangePicker(
            year=2026, month=7,
            start=date(2026, 7, 3),
            end=None,
        )
        self.assertIsNotNone(picker)

    def test_accepts_fully_open(self):
        picker = DateRangePicker(
            year=2026, month=7,
            start=None,
            end=None,
        )
        self.assertIsNotNone(picker)


class DatePickerCallbackReuseTests(unittest.TestCase):
    """DatePicker prepares one adapter per callback, reused across cells."""

    def test_on_select_emits_date(self):
        received: list[date] = []
        picker = DatePicker(
            year=2026, month=7,
            on_select=received.append,
        )
        # Find a clickable day cell.  The grid is at children[2:] (after
        # header and weekday row, accounting for spacers).
        # header: children[0], weekday: children[1], weeks: children[2:]
        for week_row in picker.children[2:]:
            for cell in week_row.children:
                if cell.props.get("on_click") is not None:
                    cell.props["on_click"](None)
                    break
            if received:
                break
        self.assertEqual(len(received), 1)
        self.assertIsInstance(received[0], date)

    def test_on_month_change_emits_tuple(self):
        received: list[tuple[int, int]] = []
        picker = DatePicker(
            year=2026, month=7,
            on_month_change=received.append,
        )
        next_button = picker.children[0].children[4]
        next_button.props["on_click"](None)
        self.assertEqual(received, [(2026, 8)])


if __name__ == "__main__":
    unittest.main()
