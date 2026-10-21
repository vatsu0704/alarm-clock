"""Allows the package to run as `python -m alarmclock`."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
