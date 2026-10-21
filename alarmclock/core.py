"""Alarm model and time arithmetic.

Everything here is pure: no file access, no console output, and no reading of the
system clock. The current time is always passed in as `now`, which is what lets the
tests cover scheduling edge cases without sleeping or patching the clock.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

DAILY = "daily"
ONCE = "once"
REPEAT_MODES = (DAILY, ONCE)


class AlarmError(Exception):
    """A problem the user can fix, such as a malformed time or an unknown id.

    The CLI turns this into a one-line message and a non-zero exit code instead of
    a traceback.
    """


@dataclass
class Alarm:
    """One scheduled alarm.

    The time is stored as an "HH:MM" string rather than an absolute datetime so a
    daily alarm keeps working as the days roll over; the next fire time is always
    derived from the current time.
    """

    id: int
    time: str
    label: str = ""
    repeat: str = DAILY
    enabled: bool = True
    last_fired: str | None = None

    def to_dict(self) -> dict:
        """Return the JSON-serialisable form written to the alarm file."""
        return {
            "id": self.id,
            "time": self.time,
            "label": self.label,
            "repeat": self.repeat,
            "enabled": self.enabled,
            "last_fired": self.last_fired,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Alarm":
        """Build an alarm from one record of the alarm file."""
        return cls(
            id=int(data["id"]),
            time=data["time"],
            label=data.get("label", ""),
            repeat=data.get("repeat", DAILY),
            enabled=bool(data.get("enabled", True)),
            last_fired=data.get("last_fired"),
        )


def parse_time(text: str) -> dt.time:
    """Parse a 24-hour "HH:MM" string, e.g. "07:30" or "7:30".

    Raises AlarmError for anything else, including "25:00" and "7:60".
    """
    try:
        return dt.datetime.strptime(text.strip(), "%H:%M").time()
    except (ValueError, AttributeError):
        raise AlarmError(
            f"invalid time {text!r}: expected 24-hour HH:MM, for example 07:30"
        ) from None


def format_time(value: dt.time) -> str:
    """Render a time as a zero-padded "HH:MM" string."""
    return f"{value.hour:02d}:{value.minute:02d}"


def normalize_time(text: str) -> str:
    """Validate a user-supplied time and return it in canonical "HH:MM" form."""
    return format_time(parse_time(text))


def next_occurrence(alarm: Alarm, now: dt.datetime) -> dt.datetime:
    """Return the next datetime at which `alarm` is scheduled to ring.

    Today if that minute has not passed yet, otherwise tomorrow. An alarm set for
    the current minute counts as now, not as tomorrow, because it is still due to
    ring during this minute.
    """
    at = parse_time(alarm.time)
    this_minute = now.replace(second=0, microsecond=0)
    candidate = this_minute.replace(hour=at.hour, minute=at.minute)
    if candidate < this_minute:
        candidate += dt.timedelta(days=1)
    return candidate


def find_alarm(alarms: list[Alarm], alarm_id: int) -> Alarm:
    """Return the alarm with `alarm_id`, or raise AlarmError if there is none."""
    for alarm in alarms:
        if alarm.id == alarm_id:
            return alarm
    raise AlarmError(f"no alarm with id {alarm_id}; run 'list' to see the ids in use")


def minute_stamp(now: dt.datetime) -> str:
    """Identify the minute `now` falls in, e.g. "2026-10-21T07:30".

    Stored in `last_fired` so an alarm rings once per minute however often the
    watcher polls, and does not ring again if the watcher is restarted.
    """
    return now.strftime("%Y-%m-%dT%H:%M")


def is_due(alarm: Alarm, now: dt.datetime) -> bool:
    """Should `alarm` ring at `now`?

    True when the alarm is enabled, its time matches the current hour and minute,
    and it has not already rung during this minute.
    """
    if not alarm.enabled:
        return False
    at = parse_time(alarm.time)
    if (now.hour, now.minute) != (at.hour, at.minute):
        return False
    return alarm.last_fired != minute_stamp(now)


def due_alarms(alarms: list[Alarm], now: dt.datetime) -> list[Alarm]:
    """Return every alarm that should ring at `now`, in id order."""
    return [alarm for alarm in sorted(alarms, key=lambda a: a.id) if is_due(alarm, now)]


def mark_fired(alarm: Alarm, now: dt.datetime) -> None:
    """Record that `alarm` just rang, and retire it if it was a one-shot."""
    alarm.last_fired = minute_stamp(now)
    if alarm.repeat == ONCE:
        alarm.enabled = False
