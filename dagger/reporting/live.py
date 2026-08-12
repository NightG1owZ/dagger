"""Real-time live display using rich."""

import time
from typing import Optional

from rich.live import Live
from rich.table import Table
from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich import box

from ..models.metrics import MetricsSnapshot
from ..core.timer import format_duration
from .formatters import format_percentile_row, format_rate, format_percent


class LiveDisplay:
    """Real-time metrics display using rich.Live for smooth terminal updates."""

    def __init__(
        self,
        console: Optional[Console] = None,
        refresh_per_second: int = 5,
        no_color: bool = False,
    ):
        self._console = console or Console(no_color=no_color)
        self._live: Optional[Live] = None
        self._refresh_per_second = refresh_per_second
        self._start_time: float = 0.0

    def start(self) -> None:
        self._start_time = time.monotonic()
        table = self._build_table(MetricsSnapshot())
        self._live = Live(
            table,
            console=self._console,
            refresh_per_second=self._refresh_per_second,
            transient=False,
        )
        self._live.start()

    def stop(self) -> None:
        if self._live:
            self._live.stop()

    def update(self, snapshot: MetricsSnapshot) -> None:
        """Update the live display with latest metrics."""
        if self._live:
            self._live.update(self._build_table(snapshot))

    async def async_update(self, snapshot: MetricsSnapshot) -> None:
        """Async-compatible update method for use as callback."""
        self.update(snapshot)

    def _build_table(self, snapshot: MetricsSnapshot) -> Table:
        """Build a rich Table with current metrics."""
        elapsed = time.monotonic() - self._start_time if self._start_time > 0 else snapshot.elapsed

        table = Table(
            title=f"[bold]Dagger Stress Test[/] [dim]running for {format_duration(elapsed)}[/]",
            box=box.ROUNDED,
            expand=True,
            show_header=True,
            header_style="bold cyan",
        )

        table.add_column("Metric", style="dim", width=22)
        table.add_column("Value", justify="right", width=20)
        table.add_column("Metric", style="dim", width=22)
        table.add_column("Value", justify="right", width=20)

        # Row 1: Requests and RPS
        table.add_row(
            "Total Requests",
            str(snapshot.total_requests),
            "Current RPS",
            format_rate(snapshot.requests_per_second),
        )

        # Row 2: Success/Fail
        failed = snapshot.failed
        success = snapshot.successful
        table.add_row(
            "Successful",
            f"[green]{success}[/green]",
            "Failed",
            f"[red]{failed}[/red]" if failed > 0 else str(failed),
        )

        # Row 3: Success rate
        if snapshot.total_requests > 0:
            success_rate = success / snapshot.total_requests * 100
            error_rate = failed / snapshot.total_requests * 100
        else:
            success_rate = error_rate = 0.0
        table.add_row(
            "Success Rate",
            f"[green]{format_percent(success_rate)}[/green]",
            "Error Rate",
            f"[red]{format_percent(error_rate)}[/red]" if error_rate > 0 else format_percent(error_rate),
        )

        # Row 4: Active users
        table.add_row(
            "Active Users",
            str(snapshot.active_users),
            "Bytes Received",
            _format_bytes(snapshot.bytes_received),
        )

        # Separator
        table.add_section()
        table.add_row(
            "[bold]Latency[/bold]", "", "", ""
        )

        # Latency rows
        p = snapshot.latencies
        table.add_row(
            format_percentile_row("Min", p.min),
            "",
            format_percentile_row("Mean", p.mean),
            "",
        )
        table.add_row(
            format_percentile_row("P50", p.p50),
            "",
            format_percentile_row("P75", p.p75),
            "",
        )
        table.add_row(
            format_percentile_row("P90", p.p90),
            "",
            format_percentile_row("P95", p.p95),
            "",
        )
        table.add_row(
            format_percentile_row("P99", p.p99),
            "",
            format_percentile_row("Max", p.max),
            "",
        )

        # Status codes
        if snapshot.status_codes:
            table.add_section()
            codes_text = " ".join(
                f"[{'green' if 200 <= c < 300 else 'yellow' if c < 400 else 'red'}]{c}:{n}[/]"
                for c, n in sorted(snapshot.status_codes.items())
            )
            table.add_row("Status Codes", codes_text, "", "")

        # Errors
        if snapshot.errors:
            table.add_section()
            error_lines = []
            for err_type, count in snapshot.errors.most_common(3):
                error_lines.append(f"[red]{err_type}: {count}[/red]")
            table.add_row("Top Errors", "\n".join(error_lines), "", "")

        return table


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    elif n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    else:
        return f"{n / (1024 ** 2):.1f} MB"
