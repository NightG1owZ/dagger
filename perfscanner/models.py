"""Core data models for PerfScanner."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Endpoint:
    """A single discovered HTTP API endpoint from Java Controller scanning."""

    http_method: str  # GET / POST / PUT / DELETE / PATCH ...
    path: str  # URL path template, e.g. /api/users/{id}
    resolved_path: str  # path with @PathVariable placeholders substituted
    full_url: str  # base_url + resolved_path
    class_name: str
    method_name: str
    source_file: str = ""
    source_line: int = 0
    params: list[str] = field(default_factory=list)  # path variables / request params

    @property
    def label(self) -> str:
        return f"{self.http_method} {self.path}"


@dataclass
class EndpointMetrics:
    """Aggregated timing/status metrics for a single endpoint."""

    count: int = 0
    success_count: int = 0
    error_count: int = 0
    p95: float = 0.0  # seconds
    p99: float = 0.0
    mean: float = 0.0
    median: float = 0.0
    min: float = 0.0
    max: float = 0.0
    success_rate: float = 0.0  # 0..100
    status_codes: dict[int, int] = field(default_factory=dict)
    phase: str = "quick"  # quick | deep
    requests_sent: int = 0

    @property
    def p95_ms(self) -> float:
        return self.p95 * 1000.0

    @property
    def p99_ms(self) -> float:
        return self.p99 * 1000.0


@dataclass
class EndpointResult:
    """An endpoint paired with its measured metrics."""

    endpoint: Endpoint
    metrics: EndpointMetrics
