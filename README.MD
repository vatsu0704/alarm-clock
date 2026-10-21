# Alarm Clock

A command-line alarm clock in Python. Schedule alarms by clock time, list and edit
them, and run a watcher that rings when one comes due.

Standard library only — no `pip install`, no virtual environment, no database.
Requires Python 3.10 or newer (developed on 3.14).

## Quick start

From the project root:

```powershell
python -m alarmclock add 07:30 --label "Wake up"
python -m alarmclock list
python -m alarmclock run
```

`run` holds the terminal and rings alarms as they come due. Ctrl-C stops it.

## Commands

| Command | What it does |
| --- | --- |
| `add HH:MM [--label TEXT] [--daily \| --once]` | Schedule an alarm. 24-hour time; `7:30` is accepted and stored as `07:30`. Repeats daily unless `--once`. |
| `list` | Show every alarm with its id, time, repeat mode, status and next ring time. |
| `remove ID` | Delete an alarm. |
| `disable ID` / `enable ID` | Silence or restore an alarm without deleting it. |
| `run` | Watch the clock and ring alarms until Ctrl-C. |
| `run --at HH:MM` | Ring whatever is due at the given time, then exit — for testing without waiting. |

`--file PATH` chooses a different alarm file. It is a global option, so it goes
**before** the subcommand:

```powershell
python -m alarmclock --file test.json add 09:00
```

### Example

```
> python -m alarmclock add 07:30 --label "Wake up"
Added alarm 1: 07:30 daily (Wake up)
Next ring: tomorrow 07:30

> python -m alarmclock add 13:00 --once --label "Standup"
Added alarm 2: 13:00 once (Standup)
Next ring: today 13:00

> python -m alarmclock list
 ID  TIME   REPEAT  STATUS    NEXT RING       LABEL
  1  07:30  daily   enabled   tomorrow 07:30  Wake up
  2  13:00  once    enabled   today 13:00     Standup

> python -m alarmclock run
Watching 2 alarm(s). Next ring: today 13:00. Ctrl-C to stop.
============================================================
  *** ALARM 13:00 *** Standup
  Wed 21 Oct 2026 13:00:00
  one-shot alarm - now disabled
============================================================
```

## How it works

Alarms live in `alarms.json` next to where you run the command — a plain list of
records you can read or hand-edit:

```json
[
  {
    "id": 1,
    "time": "07:30",
    "label": "Wake up",
    "repeat": "daily",
    "enabled": true,
    "last_fired": "2026-10-21T07:30"
  }
]
```

The time is stored as `HH:MM`, never as an absolute date, so a daily alarm keeps
working as the days roll over; the next ring time is always derived from the current
time. `run` polls once a second, and an alarm is due when the current hour and minute
match and `last_fired` does not already name the current minute. That stamp is what
stops an alarm ringing five times in the same minute, and what stops it ringing again
if the watcher is restarted.

The watcher re-reads the file on every pass, so an alarm added or removed in another
terminal takes effect without restarting it.

### Layout

```
alarmclock/
  core.py      # Alarm, time parsing, next_occurrence, due_alarms  (pure, no I/O)
  storage.py   # the only module that touches the filesystem
  cli.py       # argparse subcommands, ring mechanism, watch loop
tests/
  test_core.py # the time and scheduling logic, against a fake clock
  test_cli.py  # the CLI end to end, against a temporary alarm file
plan.md        # scope, decisions and the step-by-step build
```

`core.py` never reads the system clock: `now` is always passed in. That is what lets
the tests cover midnight rollover, double-firing and one-shot retirement in
milliseconds, with no sleeping and no clock patching.

## Running the tests

```powershell
python -m unittest discover -s tests -t . -v
```

54 tests, well under a second. The `-t .` matters — it roots discovery at the project
so `alarmclock` imports.

To exercise the ring path without waiting for the clock:

```powershell
python -m alarmclock add 07:30 --label "Test"
python -m alarmclock run --at 07:30
```

## Known limitations

These are deliberate omissions for a small tool, not oversights:

- **Foreground only.** `run` is a process you leave open; there is no daemon, service
  or Task Scheduler integration, so nothing rings when `run` is not active.
- **No catch-up.** An alarm whose minute passed while the watcher was stopped or the
  machine was asleep does not ring late.
- **Local wall-clock time.** No timezone or DST handling.
- **Up to a second late.** The poll interval is one second.
- **Ids can be reused.** Removing the highest-numbered alarm frees its id for the next
  one, which keeps the file a plain list with no counter to maintain.
- **Sound is best-effort.** The terminal bell plus `winsound` on Windows; a muted
  terminal or a busy sound device leaves only the on-screen banner.
