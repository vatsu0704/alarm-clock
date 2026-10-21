"""Tests for the pure time logic in alarmclock.core.

Every test supplies its own `now`, so nothing here sleeps or depends on the real
clock.
"""

import datetime as dt
import unittest

from alarmclock.core import (
    Alarm,
    AlarmError,
    due_alarms,
    find_alarm,
    format_time,
    is_due,
    mark_fired,
    minute_stamp,
    next_occurrence,
    normalize_time,
    parse_time,
)


def at(year, month, day, hour, minute, second=0):
    """Shorthand for a fixed point in time."""
    return dt.datetime(year, month, day, hour, minute, second)


class ParseTimeTests(unittest.TestCase):
    def test_accepts_padded_and_unpadded_times(self):
        self.assertEqual(parse_time("07:30"), dt.time(7, 30))
        self.assertEqual(parse_time("7:30"), dt.time(7, 30))

    def test_accepts_the_boundaries_of_the_day(self):
        self.assertEqual(parse_time("00:00"), dt.time(0, 0))
        self.assertEqual(parse_time("23:59"), dt.time(23, 59))

    def test_ignores_surrounding_whitespace(self):
        self.assertEqual(parse_time("  07:30 "), dt.time(7, 30))

    def test_rejects_out_of_range_and_malformed_times(self):
        for text in ["25:00", "7:60", "-1:00", "abc", "", "0730", "07:30:00", "7.30"]:
            with self.subTest(text=text):
                with self.assertRaises(AlarmError):
                    parse_time(text)

    def test_error_message_shows_the_expected_format(self):
        with self.assertRaises(AlarmError) as caught:
            parse_time("25:00")
        self.assertIn("HH:MM", str(caught.exception))

    def test_normalize_pads_to_two_digits(self):
        self.assertEqual(normalize_time("7:30"), "07:30")
        self.assertEqual(normalize_time("0:05"), "00:05")

    def test_format_time(self):
        self.assertEqual(format_time(dt.time(7, 5)), "07:05")


class NextOccurrenceTests(unittest.TestCase):
    def test_later_today_stays_today(self):
        alarm = Alarm(id=1, time="07:30")
        self.assertEqual(
            next_occurrence(alarm, at(2026, 10, 21, 6, 0)),
            at(2026, 10, 21, 7, 30),
        )

    def test_earlier_today_rolls_to_tomorrow(self):
        alarm = Alarm(id=1, time="07:30")
        self.assertEqual(
            next_occurrence(alarm, at(2026, 10, 21, 9, 0)),
            at(2026, 10, 22, 7, 30),
        )

    def test_the_current_minute_counts_as_now(self):
        # Mid-minute, the alarm is still due to ring, so it must not jump a day.
        alarm = Alarm(id=1, time="07:30")
        self.assertEqual(
            next_occurrence(alarm, at(2026, 10, 21, 7, 30, 42)),
            at(2026, 10, 21, 7, 30),
        )

    def test_midnight_alarm_late_at_night_rolls_over(self):
        alarm = Alarm(id=1, time="00:00")
        self.assertEqual(
            next_occurrence(alarm, at(2026, 10, 21, 23, 59)),
            at(2026, 10, 22, 0, 0),
        )

    def test_rollover_crosses_month_and_year_boundaries(self):
        alarm = Alarm(id=1, time="06:00")
        self.assertEqual(
            next_occurrence(alarm, at(2026, 12, 31, 23, 0)),
            at(2027, 1, 1, 6, 0),
        )

    def test_seconds_are_dropped_from_the_result(self):
        alarm = Alarm(id=1, time="07:30")
        result = next_occurrence(alarm, at(2026, 10, 21, 6, 0, 37))
        self.assertEqual((result.second, result.microsecond), (0, 0))

    def test_malformed_stored_time_is_reported(self):
        alarm = Alarm(id=1, time="99:99")
        with self.assertRaises(AlarmError):
            next_occurrence(alarm, at(2026, 10, 21, 6, 0))


class IsDueTests(unittest.TestCase):
    def setUp(self):
        self.alarm = Alarm(id=1, time="07:30", label="Wake up")

    def test_due_anywhere_inside_its_minute(self):
        for second in (0, 1, 30, 59):
            with self.subTest(second=second):
                self.assertTrue(is_due(self.alarm, at(2026, 10, 21, 7, 30, second)))

    def test_not_due_in_the_minutes_either_side(self):
        self.assertFalse(is_due(self.alarm, at(2026, 10, 21, 7, 29, 59)))
        self.assertFalse(is_due(self.alarm, at(2026, 10, 21, 7, 31, 0)))

    def test_not_due_once_it_has_already_rung_this_minute(self):
        now = at(2026, 10, 21, 7, 30, 2)
        self.assertTrue(is_due(self.alarm, now))
        mark_fired(self.alarm, now)
        # The watcher polls every second; the alarm must ring only on the first pass.
        self.assertFalse(is_due(self.alarm, now))
        self.assertFalse(is_due(self.alarm, at(2026, 10, 21, 7, 30, 59)))

    def test_a_daily_alarm_is_due_again_the_next_day(self):
        mark_fired(self.alarm, at(2026, 10, 21, 7, 30))
        self.assertTrue(is_due(self.alarm, at(2026, 10, 22, 7, 30)))

    def test_a_disabled_alarm_never_rings(self):
        self.alarm.enabled = False
        self.assertFalse(is_due(self.alarm, at(2026, 10, 21, 7, 30)))

    def test_a_one_shot_alarm_rings_exactly_once(self):
        alarm = Alarm(id=1, time="07:30", repeat="once")
        self.assertTrue(is_due(alarm, at(2026, 10, 21, 7, 30)))
        mark_fired(alarm, at(2026, 10, 21, 7, 30))
        self.assertFalse(alarm.enabled)
        self.assertFalse(is_due(alarm, at(2026, 10, 22, 7, 30)))

    def test_mark_fired_leaves_a_daily_alarm_enabled(self):
        mark_fired(self.alarm, at(2026, 10, 21, 7, 30))
        self.assertTrue(self.alarm.enabled)
        self.assertEqual(self.alarm.last_fired, "2026-10-21T07:30")

    def test_minute_stamp_ignores_seconds(self):
        self.assertEqual(minute_stamp(at(2026, 10, 21, 7, 30, 59)), "2026-10-21T07:30")


class DueAlarmsTests(unittest.TestCase):
    def test_selects_only_the_alarms_set_for_this_minute(self):
        alarms = [
            Alarm(id=1, time="07:30", label="daily"),
            Alarm(id=2, time="07:30", label="once", repeat="once"),
            Alarm(id=3, time="07:30", label="muted", enabled=False),
            Alarm(id=4, time="08:00", label="later"),
        ]
        # Two alarms sharing a minute must both ring.
        self.assertEqual([a.id for a in due_alarms(alarms, at(2026, 10, 21, 7, 30))], [1, 2])
        self.assertEqual([a.id for a in due_alarms(alarms, at(2026, 10, 21, 8, 0))], [4])

    def test_returns_empty_when_nothing_is_due(self):
        alarms = [Alarm(id=1, time="07:30")]
        self.assertEqual(due_alarms(alarms, at(2026, 10, 21, 9, 15)), [])
        self.assertEqual(due_alarms([], at(2026, 10, 21, 7, 30)), [])

    def test_results_come_back_in_id_order(self):
        alarms = [Alarm(id=9, time="07:30"), Alarm(id=2, time="07:30")]
        self.assertEqual([a.id for a in due_alarms(alarms, at(2026, 10, 21, 7, 30))], [2, 9])


class FindAlarmTests(unittest.TestCase):
    def test_returns_the_matching_alarm(self):
        alarms = [Alarm(id=1, time="07:30"), Alarm(id=2, time="08:00")]
        self.assertIs(find_alarm(alarms, 2), alarms[1])

    def test_unknown_id_raises_with_a_hint(self):
        with self.assertRaises(AlarmError) as caught:
            find_alarm([Alarm(id=1, time="07:30")], 99)
        self.assertIn("99", str(caught.exception))
        self.assertIn("list", str(caught.exception))


class AlarmRecordTests(unittest.TestCase):
    def test_round_trips_through_its_dict_form(self):
        alarm = Alarm(id=3, time="07:30", label="Wake up", repeat="once")
        self.assertEqual(Alarm.from_dict(alarm.to_dict()), alarm)

    def test_defaults_fill_in_missing_optional_fields(self):
        alarm = Alarm.from_dict({"id": 1, "time": "07:30"})
        self.assertEqual(alarm.label, "")
        self.assertEqual(alarm.repeat, "daily")
        self.assertTrue(alarm.enabled)
        self.assertIsNone(alarm.last_fired)


if __name__ == "__main__":
    unittest.main()
