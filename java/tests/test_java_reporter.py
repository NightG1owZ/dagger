"""Tests for report output: console table, JSON and CSV export."""

from __future__ import annotations

import csv
import io
import json

import pytest
from rich.console import Console

from java.models import (
    STATUS_FAILED,
    STATUS_INSUFFICIENT,
    STATUS_OK,
    STATUS_SKIPPED,
    ApiEndpoint,
    EndpointResult,
)
from java.reporter import endpoint_dicts, print_table, write_output


def _result(
    path,
    status=STATUS_OK,
    p95=None,
    p99=None,
    requests=0,
    success=0,
    failed=0,
    reason="",
    dropped=False,
):
    return EndpointResult(
        endpoint=ApiEndpoint("GET", path),
        status=status,
        requests=requests,
        success=success,
        failed=failed,
        p95=p95,
        p99=p99,
        reason=reason,
        dropped=dropped,
    )


def test_endpoint_dicts_sorted_by_p95_desc():
    results = [
        _result("/fast", p95=0.5, p99=0.9, requests=10, success=10),
        _result("/slow", p95=2.0, p99=3.0, requests=10, success=10),
        _result("/empty", status=STATUS_INSUFFICIENT, requests=5, success=5),
        _result("/broken", status=STATUS_FAILED, reason="HTTP 500"),
        _result("/skip", status=STATUS_SKIPPED, reason="HTTP 400"),
    ]
    rows = endpoint_dicts(results)
    assert [r["path"] for r in rows] == ["/slow", "/fast", "/empty", "/broken", "/skip"]
    assert rows[0]["p95_ms"] == 2000.0
    assert rows[0]["p99_ms"] == 3000.0
    assert rows[2]["p95_ms"] is None
    assert rows[2]["dropped"] is False


def test_write_output_json(tmp_path):
    results = [
        _result(
            "/api/a",
            p95=0.5,
            p99=0.7,
            requests=10,
            success=10,
            dropped=True,
        )
    ]
    path = write_output(results, tmp_path / "report.json", "http://localhost:8101")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["base_url"] == "http://localhost:8101"
    assert data["total"] == 1
    assert data["endpoints"][0]["method"] == "GET"
    assert data["endpoints"][0]["path"] == "/api/a"
    assert data["endpoints"][0]["status"] == STATUS_OK
    assert data["endpoints"][0]["p95_ms"] == 500.0
    assert data["endpoints"][0]["dropped"] is True


def test_write_output_csv(tmp_path):
    results = [
        _result("/api/a", status=STATUS_OK, p95=0.5, p99=0.7, requests=10, success=9, failed=1),
        _result("/api/b", status=STATUS_FAILED, reason="HTTP 400", dropped=True),
    ]
    path = write_output(results, tmp_path / "report.csv", "http://x")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert rows[0]["path"] == "/api/a"
    assert rows[0]["p95_ms"] == "500.0"
    assert rows[0]["dropped"] == "False"
    assert rows[1]["status"] == STATUS_FAILED
    assert rows[1]["reason"] == "HTTP 400"
    assert rows[1]["dropped"] == "True"


def test_write_output_rejects_other_extensions(tmp_path):
    with pytest.raises(ValueError, match="json"):
        write_output([], tmp_path / "report.txt", "http://x")


def test_print_table_renders(openapi_server):
    console = Console(file=io.StringIO(), width=120)
    results = [
        _result("/api/fast", p95=0.5, p99=0.9, requests=10, success=10),
        _result("/api/bad", status=STATUS_FAILED, reason="HTTP 400: bad request"),
        _result("/api/biz", status=STATUS_FAILED, reason="业务码 500", dropped=True),
    ]
    print_table(results, console)
    output = console.file.getvalue()
    assert "接口 P95/P99 排名" in output
    assert "GET /api/fast" in output
    assert "GET /api/bad" in output
    assert "HTTP 400: bad request" in output
    assert "已丢弃" in output
