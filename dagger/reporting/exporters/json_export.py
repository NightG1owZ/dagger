"""JSON exporter for machine-readable results."""

import json
from pathlib import Path
from collections import Counter

from ...models.metrics import MetricsSummary


class JsonExporter:
    """Exports MetricsSummary as a JSON file."""

    def export(self, summary: MetricsSummary, filepath: Path) -> None:
        data = {
            "config": summary.config_summary,
            "duration_seconds": summary.duration,
            "total_requests": summary.total_requests,
            "successful": summary.successful,
            "failed": summary.failed,
            "success_rate": round(summary.success_rate, 2),
            "avg_rps": round(summary.avg_rps, 2),
            "peak_rps": round(summary.peak_rps, 2),
            "latency_ms": {
                "min": round(summary.latencies.min, 2),
                "p50": round(summary.latencies.p50, 2),
                "p75": round(summary.latencies.p75, 2),
                "p90": round(summary.latencies.p90, 2),
                "p95": round(summary.latencies.p95, 2),
                "p99": round(summary.latencies.p99, 2),
                "p99_9": round(summary.latencies.p99_9, 2),
                "max": round(summary.latencies.max, 2),
                "mean": round(summary.latencies.mean, 2),
                "stddev": round(summary.latencies.stddev, 2),
                "count": summary.latencies.count,
            },
            "status_codes": {str(k): v for k, v in summary.status_codes.items()},
            "errors": [
                {
                    "type": e.error_type,
                    "count": e.count,
                    "percentage": round(e.percentage, 2),
                    "example": e.example,
                }
                for e in summary.errors
            ],
            "bytes_received": summary.bytes_received,
            "bytes_sent": summary.bytes_sent,
            "histogram_buckets": [
                {"boundary_ms": round(b, 2) if b != float("inf") else "inf", "count": c}
                for b, c in summary.histogram_buckets
            ],
            "time_series": [
                {
                    "elapsed": round(p.elapsed, 2),
                    "rps": round(p.rps, 2),
                    "p50_ms": round(p.p50, 2),
                    "p90_ms": round(p.p90, 2),
                    "p99_ms": round(p.p99, 2),
                    "error_rate": round(p.error_rate, 2),
                }
                for p in summary.time_series
            ],
        }

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
