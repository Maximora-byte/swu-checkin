"""Windowed frozen application entry point (also accepts --scheduled/--self-test)."""

import os
import sys

# PyInstaller's windowed bootloader sets these streams to None. Some numerical
# libraries and argparse still write to them. Never redirect them to a user log.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from swu_checkin.desktop import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
