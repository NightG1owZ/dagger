"""Time-related utilities."""

import time


def monotonic() -> float:
    """Return monotonic clock value (not subject to system clock adjustments)."""
    return time.monotonic()


def format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.0f} us"
    elif seconds < 1:
        return f"{seconds * 1000:.1f} ms"
    elif seconds < 60:
        return f"{seconds:.2f} s"
    elif seconds < 3600:
        m = int(seconds // 60)
        s = seconds % 60
        return f"{m}m {s:.0f}s"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"


def format_bytes(n: int) -> str:
    """Format byte count to human-readable string."""
    if n < 1024:
        return f"{n} B"
    elif n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    elif n < 1024 ** 3:
        return f"{n / (1024 ** 2):.1f} MB"
    else:
        return f"{n / (1024 ** 3):.2f} GB"
