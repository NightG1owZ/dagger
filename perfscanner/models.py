"""Core data models for PerfScanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RequestCategory(str, Enum):
    """Bucket a single request falls into for stratified statistics.

    The categories are mutually exclusive and answer two orthogonal questions:

    * ``SUCCESS`` / ``SERVER_ERROR`` / ``CLIENT_ERROR`` / ``TIMEOUT`` describe the
      *system under test* (they feed the error rate and, for SUCCESS, the P95/P99).
    * ``HARNESS_ERROR`` describes the *tool itself* (bad URL, missing auth, ...) and
      is excluded from all performance statistics.
    """

    SUCCESS = "success"  # 2xx / 3xx — the happy path, drives P95/P99
    CLIENT_ERROR = "client_error"  # 4xx with a valid request (business rejection)
    SERVER_ERROR = "server_error"  # 5xx — real system failure
    TIMEOUT = "timeout"  # no response within the deadline
    HARNESS_ERROR = "harness_error"  # transport error / tool-side construction error


@dataclass
class RequestSample:
    """One request's outcome: elapsed time plus its classification."""

    elapsed: float  # seconds
    category: RequestCategory
    status: int | None = None  # HTTP status; None for transport errors / timeouts


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
    """Aggregated metrics for a single endpoint.

    ``p95`` / ``p99`` (and mean/median/min/max) are computed **only from
    successful requests** so that fast failures and slow timeouts no longer
    distort the latency ranking. Failures are reported through the error-rate
    and per-category counts instead.
    """

    count: int = 0  # total requests sent (all categories)
    success_count: int = 0  # 2xx / 3xx
    error_count: int = 0  # system errors = server + client + timeout
    server_error_count: int = 0  # 5xx
    client_error_count: int = 0  # 4xx business rejections
    timeout_count: int = 0  # exceeded the deadline
    harness_error_count: int = 0  # tool-side errors, excluded from stats

    p95: float = 0.0  # seconds, success-only
    p99: float = 0.0
    mean: float = 0.0
    median: float = 0.0
    min: float = 0.0
    max: float = 0.0

    success_rate: float = 0.0  # 0..100, over effective requests (excl. harness)
    error_rate: float = 0.0  # 0..100, over effective requests
    status_codes: dict[int, int] = field(default_factory=dict)
    phase: str = "quick"  # quick | deep
    requests_sent: int = 0
    retry_count: int = 0  # total retry attempts across logical requests
    dropped: bool = False  # endpoint was abandoned mid-run (failure threshold hit)
    quality: str = "ok"  # ok | warn | critical

    @property
    def p95_ms(self) -> float:
        return self.p95 * 1000.0

    @property
    def p99_ms(self) -> float:
        return self.p99 * 1000.0

    @property
    def has_success(self) -> bool:
        return self.success_count > 0


@dataclass
class EndpointResult:
    """An endpoint paired with its measured metrics."""

    endpoint: Endpoint
    metrics: EndpointMetrics
