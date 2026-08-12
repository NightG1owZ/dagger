"""Builds the final MetricsSummary for report generation."""

from ..models.metrics import MetricsCollector, MetricsSummary
from ..models.config import TestConfig


class SummaryBuilder:
    """Aggregates raw metrics into a structured summary for reporting."""

    def __init__(self, collector: MetricsCollector, config: TestConfig):
        self._collector = collector
        self._config = config

    def build(self) -> MetricsSummary:
        config_summary = {
            "url": self._config.target.url,
            "method": self._config.target.method.value,
            "concurrency": self._config.concurrency,
            "duration_seconds": (
                self._config.duration.total_seconds()
                if self._config.duration else 0
            ),
            "total_requests_target": self._config.total_requests,
            "ramp_up": (
                self._config.ramp_up.total_seconds()
                if self._config.ramp_up else None
            ),
            "ramp_down": (
                self._config.ramp_down.total_seconds()
                if self._config.ramp_down else None
            ),
            "tags": self._config.tags,
        }
        return self._collector.finalize(config_summary)
