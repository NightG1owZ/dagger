import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def resolve_url(url: str) -> str:
    """Ensure URL has a scheme, defaulting to https."""
    if not url:
        return url
    parsed = urlparse(url)
    if not parsed.scheme:
        return f"https://{url}"
    return url


def parse_duration(value: str) -> float:
    """Parse a human-readable duration string into seconds.

    Examples: '30s' -> 30.0, '5m' -> 300.0, '1h' -> 3600.0, '500ms' -> 0.5
    """
    value = value.strip().lower()
    if not value:
        raise ValueError("Duration string is empty")

    match = re.match(r"^(\d+(?:\.\d+)?)\s*(h|m|s|ms)?$", value)
    if not match:
        raise ValueError(f"Invalid duration format: {value!r}")

    num = float(match.group(1))
    unit = match.group(2) or "s"

    multipliers = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    return num * multipliers[unit]


def parse_size(value: str) -> int:
    """Parse human-readable byte size string.

    Examples: '1KB' -> 1024, '5MB' -> 5242880
    """
    value = value.strip().upper()
    match = re.match(r"^(\d+(?:\.\d+)?)\s*(B|KB|MB|GB)?$", value)
    if not match:
        raise ValueError(f"Invalid size format: {value!r}")

    num = float(match.group(1))
    unit = match.group(2) or "B"

    multipliers = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}
    return int(num * multipliers[unit])


def human_readable_size(n: int) -> str:
    """Convert bytes to human-readable string."""
    if n < 1024:
        return f"{n} B"
    elif n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    elif n < 1024 ** 3:
        return f"{n / (1024 ** 2):.1f} MB"
    else:
        return f"{n / (1024 ** 3):.2f} GB"


def safe_filename(name: str) -> str:
    """Convert a string to a filesystem-safe filename."""
    return re.sub(r"[^\w\-_\.]", "_", name).strip("_") or "output"


def now_iso() -> str:
    """ISO 8601 timestamp for file naming."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
