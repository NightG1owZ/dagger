"""CSV exporter for per-second time series data."""

import csv
from pathlib import Path

from ...models.metrics import MetricsSummary


class CsvExporter:
    """Exports time series data as a CSV file for external analysis."""

    def export(self, summary: MetricsSummary, filepath: Path) -> None:
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "elapsed_seconds", "rps", "p50_ms", "p90_ms", "p99_ms", "error_rate_pct"
            ])

            for point in summary.time_series:
                writer.writerow([
                    round(point.elapsed, 2),
                    round(point.rps, 2),
                    round(point.p50, 2),
                    round(point.p90, 2),
                    round(point.p99, 2),
                    round(point.error_rate, 2),
                ])
