"""Pretty-printed terminal text report."""

import sys
from typing import TextIO

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from ...models.metrics import MetricsSummary
from ...core.timer import format_duration, format_bytes
from ..formatters import format_percentile_row, format_rate, format_percent, color_for_latency


class TextExporter:
    """Exports a MetricsSummary as a formatted terminal report."""

    def __init__(self, console: Console | None = None):
        self._console = console or Console()

    def export(self, summary: MetricsSummary, stream: TextIO | None = None) -> None:
        if stream is not None:
            self._console = Console(file=stream, force_terminal=False)

        self._console.print()
        self._console.rule("[bold cyan]DAGGER STRESS TEST REPORT[/bold cyan]")
        self._console.print()

        # Overview
        self._print_overview(summary)
        self._console.print()

        # Latency percentiles
        self._print_latency(summary)
        self._console.print()

        # Status codes
        self._print_status_codes(summary)
        self._console.print()

        # Throughput
        self._print_throughput(summary)
        self._console.print()

        # Errors
        if summary.errors:
            self._print_errors(summary)
            self._console.print()

        # Latency distribution chart
        if summary.histogram_buckets:
            self._print_histogram(summary)

        self._console.rule("[dim]End of Report[/dim]")
        self._console.print()

    def _print_overview(self, s: MetricsSummary) -> None:
        config = s.config_summary
        table = Table(title="Overview", box=box.ROUNDED, show_header=False, expand=True)
        table.add_column(style="dim", width=22)
        table.add_column(width=40)
        table.add_column(style="dim", width=22)
        table.add_column(width=40)

        table.add_row("Target URL", config.get("url", "N/A"), "HTTP Method", config.get("method", "N/A"))
        table.add_row("Concurrency", str(config.get("concurrency", "N/A")), "Duration", format_duration(s.duration))
        table.add_row("Total Requests", str(s.total_requests), "Avg RPS", format_rate(s.avg_rps))
        table.add_row("Peak RPS", format_rate(s.peak_rps), "Bytes Received", format_bytes(s.bytes_received))

        color = "green" if s.success_rate >= 99 else "yellow" if s.success_rate >= 95 else "red"
        table.add_row(
            "Successful", f"[green]{s.successful}[/green]",
            "Success Rate", f"[{color}]{format_percent(s.success_rate)}[/{color}]",
        )
        err_color = "green" if s.failed == 0 else "red"
        table.add_row(
            "Failed", f"[{err_color}]{s.failed}[/{err_color}]",
            "Error Rate", f"[{err_color}]{format_percent(100 - s.success_rate)}[/{err_color}]",
        )

        self._console.print(table)

    def _print_latency(self, s: MetricsSummary) -> None:
        table = Table(title="Latency Distribution (ms)", box=box.ROUNDED, show_header=True)
        table.add_column("Percentile", style="dim")
        table.add_column("Latency", justify="right")
        table.add_column("Percentile", style="dim")
        table.add_column("Latency", justify="right")

        p = s.latencies
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
            format_percentile_row("P99.9", p.p99_9),
            "",
        )
        table.add_row(
            format_percentile_row("Max", p.max),
            "",
            format_percentile_row("StdDev", p.stddev),
            "",
        )

        self._console.print(table)

    def _print_status_codes(self, s: MetricsSummary) -> None:
        if not s.status_codes:
            return

        table = Table(title="Status Code Distribution", box=box.ROUNDED, show_header=True)
        table.add_column("Status Code", justify="center")
        table.add_column("Count", justify="right")
        table.add_column("Percentage", justify="right")

        total = sum(s.status_codes.values())
        for code in sorted(s.status_codes.keys()):
            count = s.status_codes[code]
            pct = count / total * 100 if total > 0 else 0
            color = "green" if 200 <= code < 300 else "yellow" if code < 400 else "red"
            table.add_row(
                f"[{color}]{code}[/{color}]",
                str(count),
                format_percent(pct),
            )

        self._console.print(table)

    def _print_throughput(self, s: MetricsSummary) -> None:
        table = Table(title="Throughput", box=box.ROUNDED, show_header=False)
        table.add_column(style="dim", width=22)
        table.add_column(width=40)

        table.add_row("Average RPS", format_rate(s.avg_rps))
        table.add_row("Peak RPS", format_rate(s.peak_rps))
        table.add_row("Total Data Received", format_bytes(s.bytes_received))
        table.add_row("Total Data Sent", format_bytes(s.bytes_sent))
        table.add_row("Total Duration", format_duration(s.duration))

        self._console.print(table)

    def _print_errors(self, s: MetricsSummary) -> None:
        table = Table(title="Error Analysis", box=box.ROUNDED, show_header=True)
        table.add_column("Error Type", style="red")
        table.add_column("Count", justify="right")
        table.add_column("Rate", justify="right")
        table.add_column("Example", overflow="fold", max_width=50)

        for err in s.errors[:20]:
            table.add_row(
                err.error_type,
                str(err.count),
                format_percent(err.percentage),
                err.example if len(err.example) <= 80 else err.example[:77] + "...",
            )

        self._console.print(table)

    def _print_histogram(self, s: MetricsSummary) -> None:
        self._console.print("[bold]Latency Distribution[/bold]")
        if not s.histogram_buckets:
            self._console.print("  [dim](no data)[/dim]")
            return

        max_count = max(c for _, c in s.histogram_buckets)
        bar_width = 50

        for boundary_ms, count in s.histogram_buckets:
            if max_count > 0:
                bar_len = int(count / max_count * bar_width)
            else:
                bar_len = 0
            bar = "█" * bar_len
            label = f"> {boundary_ms:.0f} ms" if boundary_ms != float("inf") else "∞"
            color = color_for_latency(boundary_ms if boundary_ms != float("inf") else 10000)
            self._console.print(f"  {label:<10} [{color}]{bar}[/{color}] {count}")
