"""Argument validators for argparse type= arguments."""

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

from ..utils.misc import parse_duration as _parse_duration
from ..models.enums import ReportFormat


def validate_url(value: str) -> str:
    """Validate and normalize a URL."""
    if not value:
        raise argparse.ArgumentTypeError("URL must not be empty")
    parsed = urlparse(value)
    if not parsed.scheme:
        value = f"https://{value}"
        parsed = urlparse(value)
    if not parsed.netloc:
        raise argparse.ArgumentTypeError(f"Invalid URL: {value!r}")
    return value


def validate_duration(value: str) -> float:
    """Parse a duration string (30s, 5m, 1h, 500ms) into seconds."""
    try:
        return _parse_duration(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


def validate_concurrency(value: str) -> int:
    """Validate concurrency is a positive integer."""
    try:
        num = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid concurrency: {value!r}")
    if num < 1:
        raise argparse.ArgumentTypeError(f"Concurrency must be >= 1, got {num}")
    if num > 100000:
        raise argparse.ArgumentTypeError(f"Concurrency must be <= 100000, got {num}")
    return num


def validate_positive_int(value: str) -> int:
    """Validate a positive integer."""
    try:
        num = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid integer: {value!r}")
    if num < 0:
        raise argparse.ArgumentTypeError(f"Value must be >= 0, got {num}")
    return num


def validate_rate(value: str) -> int:
    """Validate requests per second rate limit."""
    try:
        num = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid rate: {value!r}")
    if num < 0:
        raise argparse.ArgumentTypeError(f"Rate must be >= 0, got {num}")
    return num


def validate_report_format(value: str) -> list[ReportFormat]:
    """Parse report format specifier."""
    formats = [f.strip().lower() for f in value.split(",")]
    result = []
    for fmt in formats:
        if fmt == "all":
            return list(ReportFormat)[:-1]  # exclude ALL itself
        try:
            result.append(ReportFormat(fmt))
        except ValueError:
            valid = ", ".join(f.value for f in ReportFormat)
            raise argparse.ArgumentTypeError(
                f"Invalid report format: {fmt!r}. Valid: {valid}"
            )
    return result


def validate_header(value: str) -> tuple[str, str]:
    """Parse 'Key: Value' header string."""
    match = re.match(r"^([\w\-]+):\s*(.+)$", value)
    if not match:
        raise argparse.ArgumentTypeError(
            f"Invalid header format: {value!r}. Expected: 'Key: Value'"
        )
    return match.group(1), match.group(2)


def validate_file_exists(value: str) -> Path:
    """Validate that a file path exists."""
    path = Path(value)
    if not path.exists():
        raise argparse.ArgumentTypeError(f"File not found: {value}")
    return path
