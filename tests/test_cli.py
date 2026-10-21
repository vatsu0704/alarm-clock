"""End-to-end tests for the CLI.

Each test drives `cli.main` against a throwaway alarm file in a temporary
directory, so nothing here touches the real `alarms.json`. Ringing is silenced by
patching the beep count to zero, which also keeps the suite instant.
"""

import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from alarmclock import cli


class CliTestCase(unittest.TestCase):
    """Base class providing a temporary alarm file and a CLI runner."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = pathlib.Path(directory.name) / "alarms.json"
        patcher = mock.patch.object(cli, "RING_BEEPS", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *argv):
        """Run the CLI and return (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--file", str(self.path), *argv])
        return code, out.getvalue(), err.getvalue()

    def records(self):
        """Return the raw JSON records currently on disk."""
        return json.loads(self.path.read_text(encoding="utf-8"))


class AddAndListTests(CliTestCase):
    def test_listing_with_no_file_yet_is_not_an_error(self):
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("No alarms set", out)

    def test_add_then_list_shows_the_alarm(self):
        self.run_cli("add", "07:30", "--label", "Wake up")
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("07:30", out)
        self.assertIn("Wake up", out)
        self.assertIn("daily", out)

    def test_add_writes_the_expected_record(self):
        self.run_cli("add", "7:05", "--once", "--label", "Standup")
        self.assertEqual(
            self.records(),
            [
                {
                    "id": 1,
                    "time": "07:05",  # normalised from 7:05
                    "label": "Standup",
                    "repeat": "once",
                    "enabled": True,
                    "last_fired": None,
                }
            ],
        )

    def test_repeat_defaults_to_daily(self):
        self.run_cli("add", "07:30")
        self.assertEqual(self.records()[0]["repeat"], "daily")

    def test_invalid_time_is_rejected_without_writing_a_file(self):
        code, _, err = self.run_cli("add", "25:00")
        self.assertEqual(code, 1)
        self.assertIn("invalid time", err)
        self.assertFalse(self.path.exists())

    def test_ids_are_reused_once_the_highest_alarm_is_removed(self):
        # Ids are "one past the highest in use", so removing the last alarm frees
        # its id for the next one. Deliberate: it keeps ids short and the file a
        # plain list of alarms, with no separate counter to store. Fine for a tool
        # holding a handful of alarms, and asserted here so the choice is visible.
        self.run_cli("add", "07:00")
        self.run_cli("add", "08:00")
        self.run_cli("remove", "2")
        self.run_cli("add", "09:00")
        self.assertEqual([record["id"] for record in self.records()], [1, 2])

    def test_ids_are_not_reused_while_a_higher_alarm_survives(self):
        self.run_cli("add", "07:00")
        self.run_cli("add", "08:00")
        self.run_cli("remove", "1")
        self.run_cli("add", "09:00")
        self.assertEqual([record["id"] for record in self.records()], [2, 3])

    def test_alarms_persist_across_invocations(self):
        self.run_cli("add", "07:30")
        _, first, _ = self.run_cli("list")
        _, second, _ = self.run_cli("list")
        self.assertEqual(first, second)


class RemoveEnableDisableTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("add", "07:30", "--label", "Wake up")

    def test_remove_deletes_the_alarm(self):
        code, out, _ = self.run_cli("remove", "1")
        self.assertEqual(code, 0)
        self.assertIn("Removed alarm 1", out)
        self.assertEqual(self.records(), [])

    def test_remove_unknown_id_reports_and_exits_one(self):
        code, _, err = self.run_cli("remove", "99")
        self.assertEqual(code, 1)
        self.assertIn("no alarm with id 99", err)
        self.assertEqual(len(self.records()), 1)  # nothing was lost

    def test_disable_then_enable_round_trip(self):
        self.run_cli("disable", "1")
        self.assertFalse(self.records()[0]["enabled"])
        _, out, _ = self.run_cli("list")
        self.assertIn("disabled", out)

        self.run_cli("enable", "1")
        self.assertTrue(self.records()[0]["enabled"])

    def test_disable_is_idempotent(self):
        self.run_cli("disable", "1")
        code, out, _ = self.run_cli("disable", "1")
        self.assertEqual(code, 0)
        self.assertIn("already disabled", out)

    def test_enable_unknown_id_exits_one(self):
        code, _, err = self.run_cli("enable", "42")
        self.assertEqual(code, 1)
        self.assertIn("no alarm with id 42", err)


class RunAtTests(CliTestCase):
    """Covers the ring path through `run --at`, with no waiting on the clock."""

    def test_a_due_alarm_rings(self):
        self.run_cli("add", "07:30", "--label", "Wake up")
        code, out, _ = self.run_cli("run", "--at", "07:30")
        self.assertEqual(code, 0)
        self.assertIn("ALARM 07:30", out)
        self.assertIn("Wake up", out)

    def test_nothing_rings_at_another_time(self):
        self.run_cli("add", "07:30")
        code, out, _ = self.run_cli("run", "--at", "09:15")
        self.assertEqual(code, 0)
        self.assertIn("No alarms due at 09:15", out)
        self.assertIsNone(self.records()[0]["last_fired"])

    def test_firing_is_recorded_so_it_does_not_ring_twice(self):
        self.run_cli("add", "07:30")
        self.run_cli("run", "--at", "07:30")
        self.assertIsNotNone(self.records()[0]["last_fired"])

        code, out, _ = self.run_cli("run", "--at", "07:30")
        self.assertEqual(code, 0)
        self.assertIn("No alarms due", out)

    def test_a_one_shot_alarm_is_disabled_after_ringing(self):
        self.run_cli("add", "07:30", "--once")
        _, out, _ = self.run_cli("run", "--at", "07:30")
        self.assertIn("one-shot alarm", out)
        self.assertFalse(self.records()[0]["enabled"])

    def test_a_daily_alarm_stays_enabled_after_ringing(self):
        self.run_cli("add", "07:30")
        self.run_cli("run", "--at", "07:30")
        self.assertTrue(self.records()[0]["enabled"])

    def test_a_disabled_alarm_does_not_ring(self):
        self.run_cli("add", "07:30")
        self.run_cli("disable", "1")
        _, out, _ = self.run_cli("run", "--at", "07:30")
        self.assertIn("No alarms due", out)

    def test_two_alarms_in_the_same_minute_both_ring(self):
        self.run_cli("add", "07:30", "--label", "First")
        self.run_cli("add", "07:30", "--label", "Second")
        _, out, _ = self.run_cli("run", "--at", "07:30")
        self.assertIn("First", out)
        self.assertIn("Second", out)

    def test_an_invalid_at_time_exits_one(self):
        code, _, err = self.run_cli("run", "--at", "nope")
        self.assertEqual(code, 1)
        self.assertIn("invalid time", err)


class CorruptFileTests(CliTestCase):
    def test_unparseable_file_reports_clearly_and_changes_nothing(self):
        self.path.write_text("this is not json", encoding="utf-8")
        code, _, err = self.run_cli("list")
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", err)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "this is not json")

    def test_a_byte_order_mark_is_tolerated(self):
        # Notepad, VS Code and PowerShell all write a BOM; it must not look corrupt.
        self.path.write_text(
            '[{"id": 1, "time": "07:30", "label": "", "repeat": "daily", '
            '"enabled": true, "last_fired": null}]',
            encoding="utf-8-sig",
        )
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("07:30", out)

    def test_wrong_top_level_shape_is_reported(self):
        self.path.write_text('{"id": 1}', encoding="utf-8")
        code, _, err = self.run_cli("list")
        self.assertEqual(code, 1)
        self.assertIn("should hold a list of alarms", err)

    def test_malformed_record_is_reported(self):
        self.path.write_text('[{"nope": true}]', encoding="utf-8")
        code, _, err = self.run_cli("list")
        self.assertEqual(code, 1)
        self.assertIn("malformed alarm", err)


if __name__ == "__main__":
    unittest.main()
