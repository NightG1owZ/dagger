"""Tests for JSON + HTML report generation."""

import json

from perfscanner.models import Endpoint, EndpointMetrics, EndpointResult
from perfscanner.reporter import Reporter, build_report_data


def _result(path, p95, phase="deep"):
    ep = Endpoint(
        http_method="GET",
        path=path,
        resolved_path=path,
        full_url="http://x" + path,
        class_name="C",
        method_name="m",
        source_file="C.java",
    )
    return EndpointResult(
        ep,
        EndpointMetrics(
            p95=p95,
            p99=p95 * 1.2,
            mean=p95 * 0.8,
            median=p95,
            min=p95 * 0.5,
            max=p95 * 1.5,
            success_rate=100.0,
            status_codes={200: 2000},
            phase=phase,
            requests_sent=2000,
        ),
    )


def test_build_report_data():
    results = [_result("/slow", 0.5), _result("/fast", 0.01, phase="quick")]
    report = build_report_data(results, "http://x", "2026-01-01")

    assert report["total_endpoints"] == 2
    assert report["deep_tested"] == 1
    assert report["slowest_endpoint"] == "/slow"
    assert report["endpoints"][0]["p95_ms"] == 500.0
    assert report["endpoints"][1]["phase"] == "quick"


def test_reporter_writes_json_and_html(tmp_path):
    results = [_result("/slow", 0.5)]
    report = build_report_data(results, "http://x", "2026-01-01")
    reporter = Reporter(tmp_path)

    json_path = reporter.write_json(report, "report_data.json")
    html_path = reporter.write_html(report, "report.html")

    assert json_path.exists()
    assert html_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["total_endpoints"] == 1

    html = html_path.read_text(encoding="utf-8")
    assert "PerfScanner" in html
    assert "rankChart" in html  # Chart.js canvas is present
    assert "/slow" in html
