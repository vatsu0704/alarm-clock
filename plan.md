# Alarm Clock — Plan

A command-line alarm clock in Python. This document fixes the scope, records the
engineering decisions behind it, and breaks the build into steps that can each be
tested before the next one starts.

- **Constraints:** Python CLI only. No web UI, no React, no database.
- **Budget:** ~30 minutes of implementation.
- **Environment:** Python 3.14, Windows 11 (the code stays cross-platform).

---

## 1. Problem statement

A terminal alarm clock. The user schedules alarms by clock time, inspects and removes
them, and runs a foreground watcher that visibly and audibly rings when an alarm's
time arrives. Alarms persist between invocations.

## 2. Scope

### Core features

1. `add HH:MM [--label TEXT] [--once | --daily]` — schedule an alarm.
2. `list` — show every alarm with id, time, label, repeat mode and next fire time.
3. `remove <id>` — delete an alarm. `disable <id>` / `enable <id>` — toggle one without deleting it.
4. `run` — blocking watcher: polls every second and rings when an alarm is due.
5. Ring mechanism — visual banner plus the terminal bell (`\a`), and `winsound.Beep` on Windows when a sound device is available.
6. Persistence — a single JSON file (`alarms.json`), overridable with `--file`.
7. Unit tests for the time and scheduling logic; clear error messages and exit codes.

### Non-goals

Listed so each omission reads as a decision rather than an oversight:

- No background daemon, service or OS scheduler integration. `run` is a foreground process; Ctrl-C stops it.
- No timezone or DST handling. Local wall-clock time only.
- No catch-up for alarms missed while the machine was asleep or `run` was not active.
- No GUI, no audio files, no third-party packages.

Stretch goals, only if time remains: `snooze` when an alarm fires, weekday-only repeats.

## 3. Key engineering decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Dependencies | Standard library only (`argparse`, `json`, `datetime`, `time`, `dataclasses`) | Zero install friction — clone and run, no venv |
| Persistence | One JSON file, path overridable with `--file` | No database per the constraint; JSON stays human-inspectable, and `--file` makes tests hermetic |
| What gets stored | `HH:MM` plus a repeat mode — **not** an absolute datetime | A daily alarm has to survive a day change, so the next fire time is derived, never stored |
| Time source | `now` is passed into every pure function | Tests run instantly against a fake clock instead of sleeping or patching the system clock |
| Due detection | Fire when `now` matches the alarm's hour and minute and that minute has not already fired (`last_fired`) | Idempotent against a one-second poll; no drift arithmetic to get wrong |
| Layout | `alarmclock/` package, run with `python -m alarmclock` | Keeps pure logic (`core.py`) apart from I/O (`storage.py`) and interface (`cli.py`), so the part worth unit testing has no side effects |
| Ring behaviour | Banner plus a bounded number of beeps, then keep watching | No blocking prompt, so `run` still handles later alarms |

## 4. Structure

```
alarmclock/
  __init__.py
  __main__.py      # python -m alarmclock
  core.py          # Alarm, parse_time, next_occurrence, due_alarms  (pure, no I/O)
  storage.py       # load_alarms / save_alarms, corrupt-file handling
  cli.py           # argparse subcommands -> core + storage, exit codes
tests/
  test_core.py     # stdlib unittest, fake clock
  test_cli.py      # CLI driven against a temporary --file
plan.md
README.MD          # usage
alarms.json        # runtime data, gitignored
```

An alarm record:

```json
{
  "id": 1,
  "time": "07:30",
  "label": "Wake up",
  "repeat": "daily",
  "enabled": true,
  "last_fired": "2026-10-21T07:30"
}
```

## 5. Implementation steps

Every step ends in something runnable. Work stops after each step and waits for test
results before the next one begins.

### Step 1 — `add` and `list`, end to end (~7 min)

- `core.py`: the `Alarm` dataclass, `parse_time("HH:MM")` with validation, and
  `next_occurrence(alarm, now)` (today if the time is still ahead, otherwise tomorrow).
- `storage.py`: `load_alarms(path)` (missing file yields an empty list),
  `save_alarms(path, alarms)`, and next-id assignment.
- `cli.py` and `__main__.py`: the `add` and `list` subcommands plus the global `--file` option.
- `tests/test_core.py`: valid and invalid times, midnight rollover.

Validate:

```
python -m alarmclock add 07:30 --label "Wake up"
python -m alarmclock list
python -m unittest discover -s tests
```

### Step 2 — mutate and inspect (~5 min)

- `remove <id>`, `enable <id>`, `disable <id>`.
- A friendly message for an empty list; an unknown id prints a message and exits 1;
  an invalid time exits 1 with no traceback; a corrupt JSON file reports clearly
  without destroying data.

Validate: remove an id that does not exist and check `$LASTEXITCODE`; hand-corrupt
`alarms.json` and run `list`.

### Step 3 — the ring mechanism (~7 min)

- `core.due_alarms(alarms, now)` — pure selection of the alarms that should fire now.
- `cli.run` — one-second poll loop; `daily` alarms keep going, `once` alarms are
  disabled after firing, `last_fired` is written back so a restart does not re-ring,
  and Ctrl-C exits cleanly.
- `ring()` — banner and `\a`, plus `winsound.Beep` on Windows inside a `try/except`
  so a missing sound device can never crash the alarm.

Validate: add an alarm a minute out, start `run`, watch it fire.

### Step 4 — deterministic verification (~6 min)

- `run --at HH:MM` evaluates the alarms once against a supplied time and exits, so
  firing can be tested without waiting on the wall clock.
- `tests/test_core.py`: due and not-due, already fired this minute, disabled alarm,
  `once` versus `daily`.
- `tests/test_cli.py`: `add`, `list` and `remove` against a temporary `--file`.

Validate: `python -m unittest discover -s tests -v` — all green, under a second.

### Step 5 — polish (~5 min)

- `README.MD`: install-free usage, a command table, and the known limitations taken
  from the non-goals above.
- `.gitignore`: `alarms.json`, `__pycache__/`.
- A final read-through for consistent error wording and accurate `--help` text.

## 6. Testing strategy

- **Unit tests (primary).** The pure functions in `core.py` take a fake `now`, so
  scheduling edge cases are covered in milliseconds with no sleeping and no clock patching.
- **CLI integration.** Subcommands run against a temporary JSON file via `--file`,
  asserting output and exit code. This proves the wiring without touching real data.
- **Manual acceptance per step.** The commands listed under each step above are run by
  hand and the result confirmed before the next step starts.
- **Edge cases covered:** `25:00`, `7:60` and `abc` rejected; `00:00` and midnight
  rollover; an alarm time equal to now; two alarms in the same minute both ringing; an
  empty alarm list; a missing or corrupt `alarms.json`; a disabled alarm never firing;
  a `once` alarm firing exactly once; Ctrl-C during `run`.
- **Deliberately not tested:** real audio output (device-dependent, guarded by
  `try/except`) and multi-hour drift.

## 7. Risks

- Some Windows terminals silence the bell character — hence the visual banner and the
  `winsound` path alongside it.
- A one-second poll can be up to a second late. Acceptable for an alarm clock, so it is
  documented rather than engineered away.

## 8. Acceptance check for the finished project

1. `python -m unittest discover -s tests -v` — all tests pass.
2. `python -m alarmclock add 07:30 --label "Wake up" --daily` then
   `python -m alarmclock list` — the alarm appears with its next fire time.
3. `python -m alarmclock run --at 07:30` — the alarm rings immediately and exits.
4. Add an alarm a minute ahead and leave `python -m alarmclock run` in the foreground —
   it rings on the real clock, and Ctrl-C exits cleanly.
5. `python -m alarmclock remove 1` then `list` — the empty-list message appears;
   `remove 99` prints an error and exits 1.
