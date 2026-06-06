"""Apply sysguard and exec a command.

This module is used as a tiny child-process wrapper so the parent does not
need to run Python-level sandbox setup inside subprocess ``preexec_fn``.
"""

from __future__ import annotations

import argparse
import os
import sys

if sys.platform != "win32":
    import fcntl
    import termios

import contextlib

from agent.utils import sysguard


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("missing command")

    _claim_controlling_tty()
    sysguard.apply(args.workspace)
    os.execvp(command[0], command)


def _claim_controlling_tty() -> None:
    if sys.platform == "win32" or not os.isatty(0):
        return
    with contextlib.suppress(OSError):
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)


if __name__ == "__main__":
    main()
