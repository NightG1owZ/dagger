"""End-to-end CLI tests (click CliRunner against a live local server)."""

from __future__ import annotations

import json

from click.testing import CliRunner

from java.cli import main

SPEC_ENDPOINT_COUNT = 7  # fast, slow, bad, boom, biz, users/{id}, users


def test_cli_requires_openapi_url():
    runner = CliRunner()
    result = runner.invoke(main, ["--concurrency", "5"])
    assert result.exit_code == 2


def test_cli_skips_error_apis(openapi_http_server, tmp_path):
    out = tmp_path / "report.json"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--openapi-url",
            openapi_http_server["spec_url"],
            "--total-requests",
            "20",
            "--concurrency",
            "4",
            "--timeout",
            "10",
            "--skip-error-apis",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["total"] == SPEC_ENDPOINT_COUNT
    statuses = {e["path"]: e["status"] for e in data["endpoints"]}
    assert statuses["/api/fast"] == "成功"
    assert statuses["/api/slow"] == "成功"
    assert statuses["/api/users"] == "成功"
    assert statuses["/api/users/{id}"] == "成功"
    assert statuses["/api/bad"] == "跳过"
    assert statuses["/api/boom"] == "跳过"
    assert statuses["/api/biz"] == "跳过"
    # Skipped endpoints were never load-tested, so never dropped.
    assert all(e["dropped"] is False for e in data["endpoints"])
    # Ranked by P95 descending: the slow endpoint comes first.
    tested = [e for e in data["endpoints"] if e["p95_ms"] is not None]
    assert tested[0]["path"] == "/api/slow"


def test_cli_tests_error_apis_by_default(openapi_http_server, tmp_path):
    out = tmp_path / "report.csv"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--openapi-url",
            openapi_http_server["spec_url"],
            "--total-requests",
            "10",
            "--concurrency",
            "3",
            "--timeout",
            "10",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    import csv

    with out.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == SPEC_ENDPOINT_COUNT
    statuses = {r["path"]: r["status"] for r in rows}
    # Smoke-failed endpoints are still load-tested, but flagged as 失败.
    assert statuses["/api/bad"] == "失败"
    assert statuses["/api/boom"] == "失败"
    assert statuses["/api/biz"] == "失败"
    assert statuses["/api/fast"] == "成功"
    reasons = {r["path"]: r["reason"] for r in rows}
    assert "HTTP 400" in reasons["/api/bad"]
    assert "HTTP 500" in reasons["/api/boom"]
    assert "业务码 500" in reasons["/api/biz"]
    # Every request to these endpoints fails -> they were dropped early.
    dropped = {r["path"]: r["dropped"] for r in rows}
    assert dropped["/api/bad"] == "True"
    assert dropped["/api/boom"] == "True"
    assert dropped["/api/biz"] == "True"
    assert dropped["/api/fast"] == "False"
    assert dropped["/api/slow"] == "False"


def test_cli_base_url_override(openapi_http_server, tmp_path):
    out = tmp_path / "report.json"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--openapi-url",
            openapi_http_server["spec_url"],
            "--base-url",
            openapi_http_server["base"] + "/sub",
            "--total-requests",
            "5",
            "--concurrency",
            "2",
            "--timeout",
            "10",
            "--output",
            str(out),
        ],
    )
    # Every endpoint 404s against the wrong base URL -> smoke fails, still runs.
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["base_url"] == openapi_http_server["base"] + "/sub"
    statuses = {e["path"]: e["status"] for e in data["endpoints"]}
    assert statuses["/api/fast"] == "失败"
