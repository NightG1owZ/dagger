"""Data analysis: request classification, percentile computation, ranking."""

from __future__ import annotations

import math

from .models import (
    EndpointMetrics,
    EndpointResult,
    RequestCategory,
    RequestSample,
)

# Error-rate thresholds for the quality gate (percent).
WARN_ERROR_RATE = 1.0
CRITICAL_ERROR_RATE = 5.0


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


def classify_request(
    *,
    status: int | None,
    elapsed: float,
    timeout: float,
    transport_error: bool = False,
    timed_out: bool = False,
    harness_hint: bool = False,
) -> RequestCategory:
    """Classify one request into a mutually-exclusive :class:`RequestCategory`.

    Ordering matters: transport/timeout errors win over status-based buckets,
    because they mean no meaningful HTTP response was received.
    """
    if transport_error:
        return RequestCategory.HARNESS_ERROR
    if timed_out:
        return RequestCategory.TIMEOUT
    if status is None:
        return RequestCategory.HARNESS_ERROR
    if elapsed >= timeout:
        # A response arrived at/after the deadline; treat it as a timeout so it
        # does not pollute the success latency distribution.
        return RequestCategory.TIMEOUT
    if 200 <= status < 400:
        return RequestCategory.SUCCESS
    if 500 <= status < 600:
        return RequestCategory.SERVER_ERROR
    # 4xx: a valid request that was rejected. When the tool knows it built the
    # request incorrectly (missing params/auth), that's a harness error.
    if harness_hint:
        return RequestCategory.HARNESS_ERROR
    return RequestCategory.CLIENT_ERROR


def quality_flag(error_rate: float, success_count: int) -> str:
    """Map an endpoint's error rate to a quality-gate label."""
    if success_count == 0:
        return "critical"
    if error_rate > CRITICAL_ERROR_RATE:
        return "critical"
    if error_rate > WARN_ERROR_RATE:
        return "warn"
    return "ok"


def compute_metrics(
    samples: list[RequestSample],
    phase: str = "quick",
    retry_count: int = 0,
    dropped: bool = False,
) -> EndpointMetrics:
    """Aggregate classified request samples into stratified endpoint metrics.

    Only ``SUCCESS`` samples feed the latency percentiles (P95/P99/mean/...);
    every other category is counted separately. ``error_rate`` is the share of
    *system* errors (server + client + timeout) among effective requests, i.e.
    after excluding harness errors. ``retry_count`` and ``dropped`` carry the
    retry/drop bookkeeping done by the engine.
    """
    success_latencies = [
        s.elapsed for s in samples if s.category is RequestCategory.SUCCESS
    ]
    ordered = sorted(success_latencies)

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

    status_codes: dict[int, int] = {}
    counts = {c: 0 for c in RequestCategory}
    for s in samples:
        counts[s.category] += 1
        if s.status is not None:
            status_codes[s.status] = status_codes.get(s.status, 0) + 1

    total = len(samples)
    harness = counts[RequestCategory.HARNESS_ERROR]
    server = counts[RequestCategory.SERVER_ERROR]
    client = counts[RequestCategory.CLIENT_ERROR]
    timeout = counts[RequestCategory.TIMEOUT]
    success = counts[RequestCategory.SUCCESS]
    system_errors = server + client + timeout
    effective = total - harness

    if effective > 0:
        success_rate = 100.0 * success / effective
        error_rate = 100.0 * system_errors / effective
    else:
        success_rate = error_rate = 0.0

    return EndpointMetrics(
        count=total,
        success_count=success,
        error_count=system_errors,
        server_error_count=server,
        client_error_count=client,
        timeout_count=timeout,
        harness_error_count=harness,
        p95=p95,
        p99=p99,
        mean=mean,
        median=median,
        min=minimum,
        max=maximum,
        success_rate=success_rate,
        error_rate=error_rate,
        status_codes=status_codes,
        phase=phase,
        requests_sent=total,
        retry_count=retry_count,
        dropped=dropped,
        quality=quality_flag(error_rate, success),
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
    """Return the slowest (by success P95) endpoints that enter phase two."""
    ranked = sorted(results, key=lambda r: r.metrics.p95, reverse=True)
    return ranked[: select_deep_count(len(ranked), threshold)]


def rank_key(result: EndpointResult) -> tuple[int, float]:
    """Sort key for the final ranking.

    Endpoints with no successful requests are the worst case and surface first;
    among the rest, slower P95 ranks higher. Tuple sorts ascending, hence the
    negated P95 for descending latency.
    """
    m = result.metrics
    return (0 if m.success_count == 0 else 1, -m.p95)


def merge_results(
    quick_results: list[EndpointResult],
    deep_results: list[EndpointResult],
) -> list[EndpointResult]:
    """Combine phase-one and phase-two results, preferring deep metrics.

    The final list puts no-success endpoints first, then orders by success P95
    descending (slowest first).
    """
    deep_by_key = {
        (r.endpoint.http_method, r.endpoint.path): r for r in deep_results
    }
    merged: list[EndpointResult] = []
    for r in quick_results:
        key = (r.endpoint.http_method, r.endpoint.path)
        merged.append(deep_by_key.get(key, r))
    merged.sort(key=rank_key)
    return merged
