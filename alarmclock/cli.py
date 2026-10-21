"""Command-line interface: argparse subcommands wired to `core` and `storage`."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

from . import storage
from .core import (
    DAILY,
    ONCE,
    Alarm,
    AlarmError,
    due_alarms,
    find_alarm,
    format_time,
    mark_fired,
    next_occurrence,
    normalize_time,
    parse_time,
)

POLL_SECONDS = 1.0
RING_BEEPS = 5
BEEP_HZ = 880
BEEP_MS = 300


def cmd_add(args: argparse.Namespace) -> int:
    """Add an alarm and report the time it will next ring."""
    alarm = Alarm(
        id=0,
        time=normalize_time(args.time),
        label=args.label or "",
        repeat=ONCE if args.once else DAILY,
    )
    alarms = storage.load_alarms(args.file)
    alarm.id = storage.next_id(alarms)
    alarms.append(alarm)
    storage.save_alarms(args.file, alarms)

    now = dt.datetime.now()
    label = f" ({alarm.label})" if alarm.label else ""
    print(f"Added alarm {alarm.id}: {alarm.time} {alarm.repeat}{label}")
    print(f"Next ring: {describe_next(next_occurrence(alarm, now), now)}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Print every alarm with its next fire time."""
    alarms = storage.load_alarms(args.file)
    if not alarms:
        print("No alarms set. Add one with: python -m alarmclock add 07:30")
        return 0

    now = dt.datetime.now()
    print(f"{'ID':>3}  {'TIME':<5}  {'REPEAT':<6}  {'STATUS':<8}  {'NEXT RING':<14}  LABEL")
    for alarm in sorted(alarms, key=lambda a: (a.time, a.id)):
        status = "enabled" if alarm.enabled else "disabled"
        when = describe_next(next_occurrence(alarm, now), now) if alarm.enabled else "-"
        print(
            f"{alarm.id:>3}  {alarm.time:<5}  {alarm.repeat:<6}  {status:<8}  "
            f"{when:<14}  {alarm.label}"
        )
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    """Delete one alarm by id."""
    alarms = storage.load_alarms(args.file)
    alarm = find_alarm(alarms, args.id)
    alarms.remove(alarm)
    storage.save_alarms(args.file, alarms)
    print(f"Removed alarm {alarm.id}: {alarm.time} {alarm.repeat}{_label_suffix(alarm)}")
    return 0


def cmd_enable(args: argparse.Namespace) -> int:
    """Turn an alarm back on."""
    return _set_enabled(args, enabled=True)


def cmd_disable(args: argparse.Namespace) -> int:
    """Silence an alarm without deleting it."""
    return _set_enabled(args, enabled=False)


def _set_enabled(args: argparse.Namespace, enabled: bool) -> int:
    """Shared body of `enable` and `disable`; both are idempotent."""
    word = "enabled" if enabled else "disabled"
    alarms = storage.load_alarms(args.file)
    alarm = find_alarm(alarms, args.id)
    if alarm.enabled == enabled:
        print(f"Alarm {alarm.id} ({alarm.time}) is already {word}.")
        return 0
    alarm.enabled = enabled
    storage.save_alarms(args.file, alarms)
    print(f"Alarm {alarm.id} ({alarm.time}) {word}.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Ring alarms: once against `--at`, or continuously against the real clock."""
    if args.at:
        return _run_once(args)
    return _watch(args)


def _run_once(args: argparse.Namespace) -> int:
    """Evaluate the alarms against the time given by `--at`, then exit.

    This is the deterministic path: it makes the ring mechanism testable without
    waiting for the wall clock to reach the alarm.
    """
    at = parse_time(args.at)
    now = dt.datetime.now().replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    if not tick(args.file, now):
        print(f"No alarms due at {format_time(at)}.")
    return 0


def _watch(args: argparse.Namespace) -> int:
    """Watch the clock and ring alarms as they come due, until Ctrl-C."""
    now = dt.datetime.now()
    # Load once up front so a corrupt alarm file fails immediately rather than a
    # second later inside the loop.
    enabled = [alarm for alarm in storage.load_alarms(args.file) if alarm.enabled]
    if enabled:
        soonest = min(next_occurrence(alarm, now) for alarm in enabled)
        print(
            f"Watching {len(enabled)} alarm(s). "
            f"Next ring: {describe_next(soonest, now)}. Ctrl-C to stop."
        )
    else:
        print(
            "No enabled alarms yet. Watching anyway - alarms added from another "
            "terminal are picked up live. Ctrl-C to stop."
        )

    try:
        while True:
            tick(args.file, dt.datetime.now())
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped watching.")
        return 0


def tick(path, now: dt.datetime) -> list[Alarm]:
    """Run one pass of the watcher: ring whatever is due at `now`.

    The alarm file is re-read every pass, so alarms added or removed elsewhere take
    effect without restarting the watcher. The fired state is saved *before*
    ringing, so an interrupt mid-ring cannot cause the same alarm to ring twice.
    """
    alarms = storage.load_alarms(path)
    due = due_alarms(alarms, now)
    if not due:
        return []
    for alarm in due:
        mark_fired(alarm, now)
    storage.save_alarms(path, alarms)
    for alarm in due:
        ring(alarm, now)
    return due


def ring(alarm: Alarm, now: dt.datetime) -> None:
    """Announce an alarm on screen and make whatever noise the terminal allows."""
    bar = "=" * 60
    print(bar)
    print(f"  *** ALARM {alarm.time} ***{_label_suffix(alarm)}")
    print(f"  {now:%a %d %b %Y %H:%M:%S}")
    if alarm.repeat == ONCE:
        print("  one-shot alarm - now disabled")
    print(bar, flush=True)
    for _ in range(RING_BEEPS):
        print("\a", end="", flush=True)
        _beep()
        time.sleep(0.3)


def _beep() -> None:
    """Best-effort audible tone.

    A missing or busy sound device must never take the alarm down, so every
    failure here is swallowed; the banner and the bell character still got through.
    """
    if sys.platform != "win32":
        return
    try:
        import winsound

        winsound.Beep(BEEP_HZ, BEEP_MS)
    except Exception:
        pass


def _label_suffix(alarm: Alarm) -> str:
    """Render an alarm's label for a one-line message, or nothing if it has none."""
    return f" {alarm.label}" if alarm.label else ""


def describe_next(when: dt.datetime, now: dt.datetime) -> str:
    """Describe a fire time relative to today, e.g. "today 07:30"."""
    day = "today" if when.date() == now.date() else "tomorrow"
    return f"{day} {when:%H:%M}"


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for every subcommand."""
    parser = argparse.ArgumentParser(
        prog="python -m alarmclock",
        description="A command-line alarm clock.",
    )
    parser.add_argument(
        "--file",
        default=storage.DEFAULT_PATH,
        metavar="PATH",
        help=f"alarm file to use (default: {storage.DEFAULT_PATH})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add", help="schedule a new alarm")
    add.add_argument("time", help="24-hour time to ring at, e.g. 07:30")
    add.add_argument("--label", help="a note to show when the alarm rings")
    repeat = add.add_mutually_exclusive_group()
    repeat.add_argument(
        "--daily",
        action="store_true",
        help="ring every day at this time (default)",
    )
    repeat.add_argument("--once", action="store_true", help="ring once, then stop")
    add.set_defaults(func=cmd_add)

    listing = subparsers.add_parser("list", help="show all alarms")
    listing.set_defaults(func=cmd_list)

    remove = subparsers.add_parser("remove", help="delete an alarm by id")
    remove.add_argument("id", type=int, help="id of the alarm, as shown by 'list'")
    remove.set_defaults(func=cmd_remove)

    enable = subparsers.add_parser("enable", help="turn an alarm back on")
    enable.add_argument("id", type=int, help="id of the alarm, as shown by 'list'")
    enable.set_defaults(func=cmd_enable)

    disable = subparsers.add_parser(
        "disable", help="silence an alarm without deleting it"
    )
    disable.add_argument("id", type=int, help="id of the alarm, as shown by 'list'")
    disable.set_defaults(func=cmd_disable)

    run = subparsers.add_parser("run", help="watch the clock and ring alarms when due")
    run.add_argument(
        "--at",
        metavar="HH:MM",
        help="ring whatever is due at this time and exit, instead of watching "
        "the clock (useful for testing without waiting)",
    )
    run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except AlarmError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
