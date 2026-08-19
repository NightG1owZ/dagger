"""Click CLI for the OpenAPI-based Java load tester (``python -m java``)."""

from __future__ import annotations

import asyncio
import logging
import random
import sys
from pathlib import Path

import aiohttp
import click
from rich.console import Console

from . import __version__
from .analyzer import mark_failed
from .engine import LoadEngine
from .models import (
    ApiEndpoint,
    EndpointResult,
    SmokeResult,
    STATUS_FAILED,
    STATUS_INSUFFICIENT,
    STATUS_OK,
    STATUS_SKIPPED,
)
from .openapi import OpenApiError, fetch_spec, parse_spec
from .reporter import format_ms, print_table, write_output
from .smoke import smoke_endpoint

logger = logging.getLogger("java")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "--version", prog_name="java-openapi")
@click.option(
    "--openapi-url",
    required=True,
    help="OpenAPI (Swagger) 文档 URL, 如 http://localhost:8101/api/v3/api-docs",
)
@click.option(
    "--concurrency",
    default=10,
    show_default=True,
    type=int,
    help="每个接口的并发协程数.",
)
@click.option(
    "--total-requests",
    default=1000,
    show_default=True,
    type=int,
    help="每个接口的总请求数 (指定 --duration 时忽略).",
)
@click.option(
    "--duration",
    default=None,
    type=float,
    help="每个接口的压测时长 (秒), 指定后忽略 --total-requests.",
)
@click.option(
    "--output",
    default=None,
    type=click.Path(path_type=Path),
    help="报告文件路径 (.json 或 .csv), 默认仅打印到控制台.",
)
@click.option(
    "--skip-error-apis",
    is_flag=True,
    default=False,
    help="跳过冒烟测试失败的接口, 只压测通过冒烟的接口.",
)
@click.option(
    "--base-url",
    default=None,
    help="覆盖 OpenAPI 中 servers 字段的 base URL.",
)
@click.option(
    "--timeout",
    default=10.0,
    show_default=True,
    type=float,
    help="单次请求超时 (秒), 超时计为失败且不重试.",
)
@click.option(
    "--drop-failure-rate",
    default=0.5,
    show_default=True,
    type=float,
    help="压测中失败率达到该阈值(0~1)后丢弃此接口, 停止继续请求; 设为大于 1 可禁用丢弃.",
)
@click.option(
    "--min-requests-before-drop",
    default=10,
    show_default=True,
    type=int,
    help="至少完成多少请求后才允许触发丢弃.",
)
@click.option("--verbose", is_flag=True, help="输出调试日志.")
def main(
    openapi_url: str,
    concurrency: int,
    total_requests: int,
    duration: float | None,
    output: Path | None,
    skip_error_apis: bool,
    base_url: str | None,
    timeout: float,
    drop_failure_rate: float,
    min_requests_before_drop: int,
    verbose: bool,
) -> None:
    """基于 OpenAPI 文档的 Java API 压力测试与 P95/P99 排名工具."""
    _setup_logging(verbose)
    console = Console()
    if drop_failure_rate > 1.0:
        drop_failure_rate = None
    try:
        asyncio.run(
            _run(
                console,
                openapi_url=openapi_url,
                concurrency=concurrency,
                total_requests=total_requests,
                duration=duration,
                output=output,
                skip_error_apis=skip_error_apis,
                base_url=base_url,
                timeout=timeout,
                drop_failure_rate=drop_failure_rate,
                min_requests_before_drop=min_requests_before_drop,
            )
        )
    except OpenApiError as exc:
        console.print(f"[red]错误: {exc}[/red]")
        sys.exit(1)


async def _run(
    console: Console,
    *,
    openapi_url: str,
    concurrency: int,
    total_requests: int,
    duration: float | None,
    output: Path | None,
    skip_error_apis: bool,
    base_url: str | None,
    timeout: float,
    drop_failure_rate: float | None,
    min_requests_before_drop: int,
) -> None:
    logger.info("获取 OpenAPI 文档: %s", openapi_url)
    spec = await fetch_spec(openapi_url, timeout=timeout)
    base, endpoints = parse_spec(spec, base_url)
    components = spec.get("components") or {}
    logger.info("解析到 %d 个接口, base URL: %s", len(endpoints), base)
    if not endpoints:
        console.print("[yellow]OpenAPI 文档中未发现任何接口[/yellow]")
        return

    engine = LoadEngine(
        concurrency=concurrency,
        timeout=timeout,
        components=components,
        drop_failure_rate=drop_failure_rate,
        min_requests_before_drop=min_requests_before_drop,
    )
    rng = random.Random()
    results: list[EndpointResult] = []

    async with aiohttp.ClientSession() as session:
        # 1. 冒烟测试 (预检): 每个接口发一次请求.
        smoke: dict[str, SmokeResult] = {}
        console.print("\n[bold]冒烟测试 (预检)[/bold]")
        for ep in endpoints:
            sr = await smoke_endpoint(session, ep, base, components, rng, timeout)
            smoke[ep.label] = sr
            state = "通过" if sr.passed else f"失败: {sr.reason}"
            logger.info("冒烟 %s: %s", ep.label, state)
            if not sr.passed:
                console.print(f"  {ep.label}: [red]冒烟失败[/red] — {sr.reason}")

        # 2. 决定压测列表: --skip-error-apis 时跳过冒烟失败的接口.
        test_list = [
            ep for ep in endpoints if not (skip_error_apis and not smoke[ep.label].passed)
        ]

        # 3. 压力测试: 依次压测每个接口.
        if duration and duration > 0:
            mode = f"时长 {duration}s"
            total = None
        else:
            mode = f"{total_requests} 请求"
            total = total_requests
        console.print(
            f"\n[bold]压力测试[/bold] (并发 {concurrency}, 每接口 {mode}, 超时 {timeout}s)"
        )
        for i, ep in enumerate(test_list, 1):
            logger.info("压测 [%d/%d] %s ...", i, len(test_list), ep.label)
            result = await engine.load_endpoint(
                session, ep, base, total_requests=total, duration=duration
            )
            if not smoke[ep.label].passed:
                mark_failed(result, smoke[ep.label].reason)
            results.append(result)
            dropped = "，已丢弃" if result.dropped else ""
            console.print(
                f"  完成 {ep.label}: {result.requests} 请求 / "
                f"成功 {result.success} / 失败 {result.failed}"
                f"{f' / P95 {format_ms(result.p95)}ms' if result.p95 is not None else ''}"
                f"{dropped}"
            )

        # 4. 被跳过的接口直接标记.
        for ep in endpoints:
            if ep not in test_list:
                results.append(
                    EndpointResult(
                        endpoint=ep,
                        status=STATUS_SKIPPED,
                        reason=smoke[ep.label].reason,
                    )
                )

    # 5. 输出报告.
    print_table(results, console)
    counts = {s: 0 for s in (STATUS_OK, STATUS_INSUFFICIENT, STATUS_FAILED, STATUS_SKIPPED)}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    console.print(
        f"共 {len(results)} 个接口: 成功 {counts[STATUS_OK]}, "
        f"数据不足 {counts[STATUS_INSUFFICIENT]}, "
        f"失败 {counts[STATUS_FAILED]}, 跳过 {counts[STATUS_SKIPPED]}"
    )
    if output is not None:
        path = write_output(results, output, base)
        console.print(f"报告已写入: {path}")


if __name__ == "__main__":
    main()
