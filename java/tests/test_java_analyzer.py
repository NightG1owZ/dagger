"""Tests for P95/P99 computation, aggregation and ranking."""

from __future__ import annotations

import random

from java.analyzer import (
    MIN_SAMPLES,
    aggregate,
    compute_p95_p99,
    percentile_index,
    sort_results,
)
from java.models import (
    STATUS_FAILED,
    STATUS_INSUFFICIENT,
    STATUS_OK,
    STATUS_SKIPPED,
    ApiEndpoint,
    EndpointResult,
    Outcome,
)


def test_percentile_index_uses_int_q_times_len():
    values = list(range(100))
    assert percentile_index(values, 0.95) == 95
    assert percentile_index(values, 0.99) == 99
    # Single element stays in range.
    assert percentile_index([5], 0.95) == 0


def test_compute_p95_p99_matches_index_formula():
    times = [float(i) for i in range(100)]
    p95, p99 = compute_p95_p99(times)
    assert p95 == 95.0
    assert p99 == 99.0


def test_compute_p95_p99_insufficient_data():
    assert compute_p95_p99([]) == (None, None)
    assert compute_p95_p99([0.1] * (MIN_SAMPLES - 1)) == (None, None)


def test_compute_p95_p99_exactly_min_samples():
    times = [float(i) for i in range(MIN_SAMPLES)]
    p95, p99 = compute_p95_p99(times)
    assert p95 == times[-1]
    assert p99 == times[-1]


def test_aggregate_counts_and_percentiles():
    endpoint = ApiEndpoint(method="GET", path="/api/x")
    outcomes = [Outcome(0.1, True, 200)] * 20 + [
        Outcome(0.2, False, 500, "http"),
        Outcome(0.3, False, None, "timeout"),
    ]
    result = aggregate(endpoint, outcomes, retries=4)
    assert result.status == STATUS_OK
    assert result.requests == 22
    assert result.success == 20
    assert result.failed == 2
    assert result.retries == 4
    assert result.p95 is not None and result.p95 == 0.1
    assert result.p99 == 0.1


def test_aggregate_insufficient_data():
    endpoint = ApiEndpoint(method="GET", path="/api/x")
    result = aggregate(endpoint, [Outcome(0.1, True, 200)] * 3)
    assert result.status == STATUS_INSUFFICIENT
    assert result.p95 is None and result.p99 is None


def test_aggregate_all_failed():
    endpoint = ApiEndpoint(method="GET", path="/api/x")
    result = aggregate(endpoint, [Outcome(0.1, False, 500, "http")] * 12)
    assert result.status == STATUS_INSUFFICIENT
    assert result.success == 0
    assert result.failed == 12


def test_sort_results_by_p95_desc_then_no_data_last():
    def res(path, p95):
        return EndpointResult(
            endpoint=ApiEndpoint("GET", path),
            status=STATUS_OK,
            p95=p95,
            p99=p95,
        )

    slow = res("/slow", 2.0)
    fast = res("/fast", 0.5)
    no_data = EndpointResult(
        endpoint=ApiEndpoint("GET", "/empty"),
        status=STATUS_INSUFFICIENT,
        requests=5,
        success=5,
    )
    failed = EndpointResult(
        endpoint=ApiEndpoint("GET", "/broken"),
        status=STATUS_FAILED,
        reason="HTTP 500",
    )
    skipped = EndpointResult(
        endpoint=ApiEndpoint("GET", "/skip"),
        status=STATUS_SKIPPED,
        reason="HTTP 400",
    )
    ranked = sort_results([fast, no_data, slow, failed, skipped])
    assert [r.endpoint.path for r in ranked] == [
        "/slow",
        "/fast",
        "/empty",
        "/broken",
        "/skip",
    ]
