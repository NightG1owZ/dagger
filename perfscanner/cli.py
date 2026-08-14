"""Standalone click CLI for PerfScanner (also exposed as ``dagger scan``)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console

from . import __version__
from .core import run_scan

console = Console()


@click.group(no_args_is_help=True)
@click.version_option(__version__, "--version", prog_name="perf-tool")
def cli() -> None:
    """PerfScanner — 智能 Java API 压力测试与排名工具."""


@cli.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--base-url", "-b", required=True, help="目标服务器基础地址 (如 http://localhost:8080/api).")
@click.option("--git-diff", default=None, help="增量扫描的 git 范围 (如 main..HEAD).")
@click.option("--max-parallel", "-c", default=5, show_default=True, type=int, help="同时压测的接口数量.")
@click.option("--quick-requests", "-q", default=50, show_default=True, type=int, help="第一阶段每个接口的请求数.")
@click.option("--deep-requests", "-n", default=2000, show_default=True, type=int, help="第二阶段(慢接口)每个接口的请求数.")
@click.option(
    "--deep-threshold",
    default=20,
    show_default=True,
    type=float,
    help="进入第二阶段的接口数量(整数)或比例(0~1 之间的小数).",
)
@click.option("--timeout", "-t", default=30, show_default=True, type=int, help="单次请求超时时间(秒).")
@click.option("--output", "-o", default="./perf_results", show_default=True, type=click.Path(path_type=Path), help="输出目录.")
@click.option("--open-browser", is_flag=True, help="报告生成后自动在浏览器打开.")
def start(
    project_path: Path,
    base_url: str,
    git_diff: str | None,
    max_parallel: int,
    quick_requests: int,
    deep_requests: int,
    deep_threshold: float,
    timeout: int,
    output: Path,
    open_browser: bool,
) -> None:
    """扫描 Java 项目并对接口进行压测排名."""
    asyncio.run(
        run_scan(
            project_path,
            base_url,
            git_diff=git_diff,
            max_parallel=max_parallel,
            quick_requests=quick_requests,
            deep_requests=deep_requests,
            deep_threshold=deep_threshold,
            timeout=timeout,
            output=output,
            open_browser=open_browser,
            console=console,
        )
    )


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
