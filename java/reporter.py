"""Report output: console table plus JSON / CSV export."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .analyzer import sort_results
from .models import STATUS_FAILED, STATUS_INSUFFICIENT, STATUS_OK, STATUS_SKIPPED, EndpointResult

_STATUS_STYLE = {
    STATUS_OK: "green",
    STATUS_INSUFFICIENT: "yellow",
    STATUS_FAILED: "red",
    STATUS_SKIPPED: "dim",
}

_FIELDS = [
    "rank",
    "method",
    "path",
    "status",
    "p95_ms",
    "p99_ms",
    "requests",
    "success",
    "failed",
    "retries",
    "dropped",
    "reason",
]


def format_ms(value: float | None) -> str:
    return "—" if value is None else f"{value * 1000.0:.2f}"


def endpoint_dicts(results: list[EndpointResult]) -> list[dict]:
    """Serialize results (P95-descending) to plain dicts for JSON/CSV."""
    rows = []
    for rank, r in enumerate(sort_results(results), 1):
        rows.append(
            {
                "rank": rank,
                "method": r.endpoint.method,
                "path": r.endpoint.path,
                "status": r.status,
                "p95_ms": round(r.p95 * 1000.0, 2) if r.p95 is not None else None,
                "p99_ms": round(r.p99 * 1000.0, 2) if r.p99 is not None else None,
                "requests": r.requests,
                "success": r.success,
                "failed": r.failed,
                "retries": r.retries,
                "dropped": r.dropped,
                "reason": r.reason,
            }
        )
    return rows


def _note(result: EndpointResult) -> str:
    note = result.reason
    if result.dropped:
        note = (note + "，" if note else "") + "已丢弃(失败率过高)"
    return note


def print_table(results: list[EndpointResult], console: Console) -> None:
    """Print the ranking table sorted by P95 descending."""
    ranked = sort_results(results)
    table = Table(title="接口 P95/P99 排名 (按 P95 从高到低)", show_lines=True)
    table.add_column("排名", justify="right", no_wrap=True)
    table.add_column("接口", no_wrap=True)
    table.add_column("状态")
    table.add_column("P95 (ms)", justify="right")
    table.add_column("P99 (ms)", justify="right")
    table.add_column("请求数", justify="right")
    table.add_column("成功", justify="right")
    table.add_column("失败", justify="right")
    table.add_column("说明")
    for rank, r in enumerate(ranked, 1):
        style = _STATUS_STYLE.get(r.status, "")
        status = f"[{style}]{r.status}[/{style}]" if style else r.status
        table.add_row(
            str(rank),
            r.endpoint.label,
            status,
            format_ms(r.p95),
            format_ms(r.p99),
            str(r.requests),
            str(r.success),
            str(r.failed),
            _note(r),
        )
    console.print(table)


def write_output(results: list[EndpointResult], path: str | Path, base_url: str) -> Path:
    """Write the report to a .json or .csv file (inferred from the extension)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = endpoint_dicts(results)
    if path.suffix.lower() == ".json":
        payload = {
            "base_url": base_url,
            "total": len(rows),
            "endpoints": rows,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    elif path.suffix.lower() == ".csv":
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    else:
        raise ValueError("--output 仅支持 .json 或 .csv 文件路径")
    return path
