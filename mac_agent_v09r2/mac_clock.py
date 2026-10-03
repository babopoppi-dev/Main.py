"""System-wide monotonic deadline for macOS, including Python3.9 runtimes."""
import math
import time


def shared_now():
    return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)


def lease_deadline(parent_until):
    remaining = max(0.0, parent_until - time.monotonic())
    if not math.isfinite(remaining) or remaining > 14401:
        raise ValueError('invalid remaining lease')
    return shared_now() + remaining + 1.0


def valid_deadline(value):
    now = shared_now()
    if not math.isfinite(value) or not now < value <= now + 14402:
        raise ValueError('bad watchdog deadline')
    return value
