"""Core data models for the OpenAPI-based load tester."""

from __future__ import annotations

from dataclasses import dataclass, field

# Endpoint status values (also used in reports).
STATUS_OK = "成功"
STATUS_INSUFFICIENT = "数据不足"
STATUS_FAILED = "失败"
STATUS_SKIPPED = "跳过"


@dataclass
class ApiParam:
    """A single request parameter declared in the OpenAPI document."""

    name: str
    location: str  # "query" | "path" | "header"
    required: bool = False
    schema: dict | None = None


@dataclass
class ApiEndpoint:
    """A single endpoint parsed from the OpenAPI ``paths`` section."""

    method: str  # GET / POST / PUT / DELETE / PATCH ...
    path: str  # URL path template, e.g. /user/{id}
    params: list[ApiParam] = field(default_factory=list)
    body_schema: dict | None = None  # resolved requestBody JSON schema
    operation_id: str = ""
    summary: str = ""

    @property
    def label(self) -> str:
        return f"{self.method} {self.path}"


@dataclass
class SmokeResult:
    """Outcome of the single smoke-test request for an endpoint."""

    passed: bool
    status: int | None = None
    reason: str = ""  # why it failed, e.g. "HTTP 400: ..." / "业务码 500: ..."


@dataclass
class Outcome:
    """One request's result during the load test.

    ``ok`` requests feed the P95/P99 percentiles; everything else is a
    failure. ``error`` distinguishes the failure kind: "http" (a deterministic
    4xx/5xx answer), "business" (HTTP 2xx but the business ``code`` is not
    0/200), "timeout" (deadline exceeded) and "harness" (tool-side
    construction bug) are never retried; "connection" (transport error, no
    response received) is retried up to ``max_retries`` times.
    """

    elapsed: float  # seconds
    ok: bool
    status: int | None = None
    error: str = ""  # "" | "http" | "business" | "timeout" | "connection" | "harness"


@dataclass
class EndpointResult:
    """An endpoint paired with its load-test outcome and status."""

    endpoint: ApiEndpoint
    status: str = STATUS_OK
    requests: int = 0  # logical requests sent (final attempts only)
    success: int = 0  # requests with a valid (2xx + business code) response
    failed: int = 0
    retries: int = 0  # extra attempts triggered by connection errors
    p95: float | None = None  # seconds; None when valid samples < MIN_SAMPLES
    p99: float | None = None
    reason: str = ""  # smoke-failure reason / note
    dropped: bool = False  # abandoned early because the failure rate was too high

    @property
    def p95_ms(self) -> float | None:
        return None if self.p95 is None else self.p95 * 1000.0

    @property
    def p99_ms(self) -> float | None:
        return None if self.p99 is None else self.p99 * 1000.0
