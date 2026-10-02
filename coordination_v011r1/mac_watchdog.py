#!/usr/bin/env python3
"""Trusted, unsandboxed uid5000 watchdog: EOF/deadline clears this dedicated UID."""
import os
from pathlib import Path
import select
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mac_guard import require_identity, stop_dedicated_children
from mac_clock import shared_now, valid_deadline


def main():
    require_identity()
    deadline = 0.0
    buffer = b''
    while True:
        readable, _, _ = select.select([0], [], [], .2)
        if readable:
            chunk = os.read(0, 1024)
            if not chunk:
                stop_dedicated_children(); return
            buffer += chunk
            if len(buffer) > 4096:
                stop_dedicated_children(); return
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                try:
                    deadline = valid_deadline(float(line))
                except ValueError:
                    stop_dedicated_children(); return
        if deadline and shared_now() >= deadline:
            stop_dedicated_children(); return


if __name__ == '__main__':
    main()
