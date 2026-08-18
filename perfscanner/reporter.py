"""Report output: JSON data file + static HTML report (Jinja2 + Chart.js)."""

from __future__ import annotations

import json
from pathlib import Path

from .models import EndpointResult

TEMPLATE_DIR = Path(__file__).parent / "templates"


def build_report_data(
    results: list[EndpointResult], base_url: str, generated_at: str
) -> dict:
    """Assemble the canonical report dict shared by JSON and HTML exporters."""
    endpoints = []
    for rank, r in enumerate(results, 1):
        m = r.metrics
        endpoints.append(
            {
                "rank": rank,
                "method": r.endpoint.http_method,
                "path": r.endpoint.path,
                "url": r.endpoint.full_url,
                "p95_ms": round(m.p95 * 1000.0, 2),
                "p99_ms": round(m.p99 * 1000.0, 2),
                "mean_ms": round(m.mean * 1000.0, 2),
                "median_ms": round(m.median * 1000.0, 2),
                "min_ms": round(m.min * 1000.0, 2),
                "max_ms": round(m.max * 1000.0, 2),
                "success_rate": round(m.success_rate, 2),
                "error_rate": round(m.error_rate, 2),
                "success_count": m.success_count,
                "server_errors": m.server_error_count,
                "client_errors": m.client_error_count,
                "timeouts": m.timeout_count,
                "harness_errors": m.harness_error_count,
                "retries": m.retry_count,
                "dropped": m.dropped,
                "requests": m.requests_sent,
                "phase": m.phase,
                "quality": m.quality,
                "status_codes": {str(k): v for k, v in sorted(m.status_codes.items())},
                "class_name": r.endpoint.class_name,
                "method_name": r.endpoint.method_name,
                "source_file": r.endpoint.source_file,
            }
        )

    with_success = [e for e in endpoints if e["success_count"] > 0]
    p95s = [e["p95_ms"] for e in with_success]
    slowest = with_success[0] if with_success else None
    return {
        "generated_at": generated_at,
        "base_url": base_url,
        "total_endpoints": len(endpoints),
        "deep_tested": sum(1 for e in endpoints if e["phase"] == "deep"),
        "unstable_endpoints": sum(1 for e in endpoints if e["quality"] != "ok"),
        "critical_endpoints": sum(1 for e in endpoints if e["quality"] == "critical"),
        "slowest_endpoint": slowest["path"] if slowest else None,
        "average_p95_ms": round(sum(p95s) / len(p95s), 2) if p95s else 0.0,
        "endpoints": endpoints,
    }


class Reporter:
    """Writes the JSON data file and renders the HTML report."""

    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_json(self, report: dict, filepath: Path) -> Path:
        filepath = self.output_dir / filepath
        filepath.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return filepath

    def write_html(self, report: dict, filepath: Path) -> Path:
        filepath = self.output_dir / filepath
        html = self._render(report)
        filepath.write_text(html, encoding="utf-8")
        return filepath

    def _render(self, report: dict) -> str:
        from jinja2 import Environment, FileSystemLoader

        env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=True,
        )
        template = env.get_template("report.html")
        chart_labels = [e["method"] + " " + e["path"] for e in report["endpoints"]]
        chart_data = [e["p95_ms"] for e in report["endpoints"]]
        return template.render(
            report=report,
            chart_labels_json=json.dumps(chart_labels),
            chart_data_json=json.dumps(chart_data),
        )
