"""Shared formatting utilities for reports."""

from ..core.timer import format_duration


def color_for_latency(ms: float) -> str:
    """Return a rich-style color tag based on latency in milliseconds."""
    if ms < 100:
        return "green"
    elif ms < 500:
        return "yellow"
    elif ms < 1000:
        return "orange1"
    else:
        return "red"


def format_percentile_row(label: str, value_ms: float) -> str:
    """Format a single percentile row for display."""
    color = color_for_latency(value_ms)
    if value_ms < 1:
        val_str = f"{value_ms * 1000:.0f} us"
    elif value_ms < 1000:
        val_str = f"{value_ms:.1f} ms"
    else:
        val_str = f"{value_ms / 1000:.2f} s"
    return f"  {label:<12} [{color}]{val_str:>12}[/{color}]"


def format_rate(rps: float) -> str:
    """Format requests per second."""
    if rps < 1:
        return f"{rps:.2f} req/s"
    elif rps < 1000:
        return f"{rps:.1f} req/s"
    else:
        return f"{rps / 1000:.1f}k req/s"


def format_percent(value: float) -> str:
    """Format a percentage value."""
    return f"{value:.1f}%"
