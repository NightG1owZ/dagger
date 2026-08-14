"""Data analysis: percentile computation, two-phase selection, sorting."""

from __future__ import annotations

import math

from .models import EndpointMetrics, EndpointResult


def percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation percentile (numpy 'linear' method) over sorted values."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]

    n = len(sorted_values)
    rank = (q / 100.0) * (n - 1)
    lo = int(rank)
    hi = lo + 1
    frac = rank - lo
    if hi >= n:
        return sorted_values[-1]
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def compute_metrics(
    latencies: list[float],
    status_codes: dict[int, int],
    phase: str = "quick",
) -> EndpointMetrics:
    """Aggregate raw per-request data into endpoint metrics.

    ``latencies`` holds one duration per request (successful or failed); a
    timeout records its elapsed time so slow timeouts are not mistaken for fast
    endpoints. ``status_codes`` holds counts only for requests that received an
    HTTP response.
    """
    total = len(latencies)
    http_success = sum(c for s, c in status_codes.items() if s < 400)
    ordered = sorted(latencies)

    if ordered:
        mean = sum(ordered) / len(ordered)
        mid = len(ordered) // 2
        median = (
            ordered[mid]
            if len(ordered) % 2 == 1
            else (ordered[mid - 1] + ordered[mid]) / 2.0
        )
        p95 = percentile(ordered, 95.0)
        p99 = percentile(ordered, 99.0)
        minimum = ordered[0]
        maximum = ordered[-1]
    else:
        mean = median = p95 = p99 = minimum = maximum = 0.0

    success_rate = (100.0 * http_success / total) if total else 0.0

    return EndpointMetrics(
        count=total,
        success_count=http_success,
        error_count=total - http_success,
        p95=p95,
        p99=p99,
        mean=mean,
        median=median,
        min=minimum,
        max=maximum,
        success_rate=success_rate,
        status_codes=dict(status_codes),
        phase=phase,
        requests_sent=total,
    )


def select_deep_count(total: int, threshold: float) -> int:
    """How many endpoints enter the deep-test phase.

    A threshold in (0, 1) is treated as a fraction (e.g. 0.2 = top 20%);
    otherwise it is a count (e.g. 20 = top 20 endpoints).
    """
    if total <= 0:
        return 0
    if 0.0 < threshold < 1.0:
        return max(1, math.ceil(total * threshold))
    return min(int(threshold), total)


def select_deep(results: list[EndpointResult], threshold: float) -> list[EndpointResult]:
    """Return the slowest (by P95) endpoints that enter phase two."""
    ranked = sorted(results, key=lambda r: r.metrics.p95, reverse=True)
    return ranked[: select_deep_count(len(ranked), threshold)]


def merge_results(
    quick_results: list[EndpointResult],
    deep_results: list[EndpointResult],
) -> list[EndpointResult]:
    """Combine phase-one and phase-two results, preferring deep metrics.

    The final list is sorted by P95 descending (slowest first).
    """
    deep_by_key = {
        (r.endpoint.http_method, r.endpoint.path): r for r in deep_results
    }
    merged: list[EndpointResult] = []
    for r in quick_results:
        key = (r.endpoint.http_method, r.endpoint.path)
        merged.append(deep_by_key.get(key, r))
    merged.sort(key=lambda r: r.metrics.p95, reverse=True)
    return merged
