"""P95/P99 computation, endpoint aggregation and ranking."""

from __future__ import annotations

from .models import (
    STATUS_FAILED,
    STATUS_INSUFFICIENT,
    STATUS_OK,
    STATUS_SKIPPED,
    ApiEndpoint,
    EndpointResult,
    Outcome,
)

# Fewer valid samples than this -> the endpoint is marked "数据不足".
MIN_SAMPLES = 10

# Sort order for statuses without a computable P95.
_STATUS_RANK = {
    STATUS_INSUFFICIENT: 0,
    STATUS_FAILED: 1,
    STATUS_SKIPPED: 2,
}


def percentile_index(values: list[float], q: float) -> int:
    """Index of the ``q``-th percentile, per the spec: ``int(q * len)``."""
    n = len(values)
    if n == 0:
        return 0
    return min(int(q * n), n - 1)


def compute_p95_p99(times: list[float]) -> tuple[float | None, float | None]:
    """P95/P99 over sorted valid response times (seconds).

    Returns ``(None, None)`` when there are fewer than :data:`MIN_SAMPLES`
    valid samples (insufficient data).
    """
    if len(times) < MIN_SAMPLES:
        return None, None
    ordered = sorted(times)
    return (
        ordered[percentile_index(ordered, 0.95)],
        ordered[percentile_index(ordered, 0.99)],
    )


def aggregate(
    endpoint: ApiEndpoint,
    outcomes: list[Outcome],
    retries: int = 0,
    dropped: bool = False,
) -> EndpointResult:
    """Turn per-request outcomes into an endpoint result.

    Only ``ok`` requests (valid 2xx + business-code responses) feed the
    percentiles; every other outcome counts as a failure and is excluded from
    them.
    """
    valid = [o.elapsed for o in outcomes if o.ok]
    p95, p99 = compute_p95_p99(valid)
    status = STATUS_OK if p95 is not None else STATUS_INSUFFICIENT
    return EndpointResult(
        endpoint=endpoint,
        status=status,
        requests=len(outcomes),
        success=len(valid),
        failed=len(outcomes) - len(valid),
        retries=retries,
        p95=p95,
        p99=p99,
        dropped=dropped,
    )


def sort_results(results: list[EndpointResult]) -> list[EndpointResult]:
    """Rank endpoints by P95 descending; data-less ones come last."""

    def key(r: EndpointResult) -> tuple[int, float, int]:
        has_p95 = r.p95 is not None
        return (
            0 if has_p95 else 1,
            -(r.p95 if has_p95 else 0.0),
            _STATUS_RANK.get(r.status, 9),
        )

    return sorted(results, key=key)


def mark_failed(result: EndpointResult, reason: str) -> EndpointResult:
    """Flag an endpoint that could not be properly load-tested."""
    result.status = STATUS_FAILED
    result.reason = reason
    return result
