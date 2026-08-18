"""Orchestration shared by CLI frontends: scan -> test -> report."""

from __future__ import annotations

import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from .analyzer import select_deep_count
from .engine import LoadEngine
from .models import Endpoint, EndpointResult
from .reporter import Reporter, build_report_data
from .scanner import JavaScanner

DEFAULT_OUTPUT = "./perf_results"


@dataclass
class ScanOutcome:
    endpoints: list[Endpoint]
    results: list[EndpointResult]
    report: dict | None
    json_path: Path | None
    html_path: Path | None


async def run_scan(
    project_path: Path | str,
    base_url: str,
    *,
    git_diff: str | None = None,
    max_parallel: int = 5,
    quick_requests: int = 50,
    deep_requests: int = 2000,
    deep_threshold: float = 20.0,
    timeout: float = 30.0,
    max_retries: int = 3,
    drop_failure_rate: float | None = 0.5,
    min_requests_before_drop: int = 10,
    output: Path | str = DEFAULT_OUTPUT,
    open_browser: bool = False,
    console: Console | None = None,
) -> ScanOutcome:
    """Run the full pipeline and print progress; returns the outcome."""
    if console is None:
        console = Console()

    console.print(f"[bold]扫描 Java 项目:[/bold] {project_path}")
    endpoints = JavaScanner(base_url).scan(project_path, git_diff)

    if not endpoints:
        console.print("[yellow]未发现任何 Controller 接口.[/yellow]")
        return ScanOutcome([], [], None, None, None)

    console.print(f"[green]发现 {len(endpoints)} 个接口.[/green]")

    deep_count = select_deep_count(len(endpoints), deep_threshold)
    total_work = len(endpoints) + deep_count

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[cyan]{task.fields[label]}"),
        TimeElapsedColumn(),
        console=console,
    )
    task_id = progress.add_task("压测中", total=total_work, label="")

    async def on_endpoint(result: EndpointResult) -> None:
        label = (
            f"{result.endpoint.http_method} {result.endpoint.path}"
            f" · P95 {result.metrics.p95_ms:.1f}ms"
        )
        progress.update(task_id, advance=1, label=label)

    engine = LoadEngine(
        base_url,
        timeout=timeout,
        max_parallel=max_parallel,
        max_retries=max_retries,
        drop_failure_rate=drop_failure_rate,
        min_requests_before_drop=min_requests_before_drop,
    )
    with progress:
        results = await engine.run_funnel(
            endpoints,
            quick_requests,
            deep_requests,
            deep_threshold,
            on_endpoint=on_endpoint,
        )

    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    report = build_report_data(results, base_url, generated_at)

    reporter = Reporter(output)
    json_path = reporter.write_json(report, Path("report_data.json"))
    html_path = reporter.write_html(report, Path("report.html"))

    _print_summary(results, console)
    console.print(f"[green]JSON 报告:[/green] {json_path}")
    console.print(f"[green]HTML 报告:[/green] {html_path}")

    if open_browser:
        webbrowser.open(html_path.resolve().as_uri())

    return ScanOutcome(endpoints, results, report, json_path, html_path)


def _print_summary(results: list[EndpointResult], console: Console) -> None:
    table = Table(title="接口性能排行 (按成功请求 P95 从慢到快)", title_style="bold cyan")
    table.add_column("排名", justify="right", style="dim")
    table.add_column("方法", style="cyan")
    table.add_column("路径")
    table.add_column("P95 (ms)", justify="right", style="red")
    table.add_column("P99 (ms)", justify="right")
    table.add_column("成功率", justify="right")
    table.add_column("错误率", justify="right")
    table.add_column("质量", justify="center")

    for rank, r in enumerate(results[:20], 1):
        m = r.metrics
        p95 = f"{m.p95_ms:.2f}" if m.has_success else "N/A"
        p99 = f"{m.p99_ms:.2f}" if m.has_success else "N/A"
        flag = {
            "ok": "[green]正常[/green]",
            "warn": "[yellow]警告[/yellow]",
            "critical": "[red]异常[/red]",
        }.get(m.quality, "—")
        if m.dropped:
            flag += " [dim]已丢弃[/dim]"
        table.add_row(
            str(rank),
            r.endpoint.http_method,
            r.endpoint.path,
            p95,
            p99,
            f"{m.success_rate:.1f}%",
            f"{m.error_rate:.1f}%",
            flag,
        )
    console.print(table)
