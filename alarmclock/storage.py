"""Reading and writing the alarm file.

This is the only module that touches the filesystem, so `core` stays pure and the
tests can point the CLI at a temporary file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .core import Alarm, AlarmError

DEFAULT_PATH = Path("alarms.json")


def load_alarms(path: str | Path) -> list[Alarm]:
    """Load the alarms from `path`. A file that does not exist means no alarms yet."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        # utf-8-sig tolerates the byte-order mark that Notepad and PowerShell add
        # when someone hand-edits the alarm file; plain utf-8 would reject it.
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise AlarmError(f"could not read {path}: {exc}") from None
    try:
        records = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AlarmError(
            f"{path} is not valid JSON ({exc}); fix the file, or delete it to start over"
        ) from None
    if not isinstance(records, list):
        raise AlarmError(f"{path} should hold a list of alarms, not {type(records).__name__}")
    try:
        return [Alarm.from_dict(record) for record in records]
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise AlarmError(f"{path} contains a malformed alarm: {exc}") from None


def save_alarms(path: str | Path, alarms: list[Alarm]) -> None:
    """Write the alarms to `path`.

    Writes a temporary file and renames it over the target, so an interrupted save
    cannot leave the alarm file truncated.
    """
    path = Path(path)
    payload = json.dumps([alarm.to_dict() for alarm in alarms], indent=2)
    temp_path = path.with_name(path.name + ".tmp")
    try:
        temp_path.write_text(payload + "\n", encoding="utf-8")
        os.replace(temp_path, path)
    except OSError as exc:
        raise AlarmError(f"could not write {path}: {exc}") from None


def next_id(alarms: list[Alarm]) -> int:
    """Return the id to give the next alarm: one past the highest in use."""
    return max((alarm.id for alarm in alarms), default=0) + 1
