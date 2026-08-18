"""Tests for classification, percentile computation, metrics aggregation, selection."""

import pytest

from perfscanner.analyzer import (
    classify_request,
    compute_metrics,
    merge_results,
    percentile,
    quality_flag,
    select_deep,
    select_deep_count,
)
from perfscanner.models import (
    Endpoint,
    EndpointMetrics,
    EndpointResult,
    RequestCategory,
    RequestSample,
)


def _sample(elapsed, category, status=None):
    return RequestSample(elapsed=elapsed, category=category, status=status)


def _result(path, p95, phase="quick", success_count=1):
    ep = Endpoint(
        http_method="GET",
        path=path,
        resolved_path=path,
        full_url="http://x" + path,
        class_name="C",
        method_name="m",
    )
    return EndpointResult(
        ep, EndpointMetrics(p95=p95, phase=phase, success_count=success_count)
    )


def test_percentile_linear_interpolation():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 50.0) == 3.0
    assert percentile(values, 95.0) == pytest.approx(4.8)


def test_percentile_edge_cases():
    assert percentile([], 95.0) == 0.0
    assert percentile([7.0], 95.0) == 7.0
    assert percentile([1.0, 2.0, 3.0], 100.0) == 3.0


# --- Request classification -------------------------------------------------


def test_classify_success():
    assert (
        classify_request(status=200, elapsed=0.1, timeout=1.0)
        is RequestCategory.SUCCESS
    )
    # 3xx also counts as success (server answered, no error semantics).
    assert (
        classify_request(status=302, elapsed=0.1, timeout=1.0)
        is RequestCategory.SUCCESS
    )


def test_classify_server_and_client_errors():
    assert (
        classify_request(status=500, elapsed=0.1, timeout=1.0)
        is RequestCategory.SERVER_ERROR
    )
    assert (
        classify_request(status=404, elapsed=0.1, timeout=1.0)
        is RequestCategory.CLIENT_ERROR
    )


def test_classify_timeout_via_flag_and_elapsed():
    assert (
        classify_request(status=None, elapsed=1.2, timeout=1.0, timed_out=True)
        is RequestCategory.TIMEOUT
    )
    # A late response past the deadline is a timeout, not a success.
    assert (
        classify_request(status=200, elapsed=1.2, timeout=1.0)
        is RequestCategory.TIMEOUT
    )


def test_classify_transport_and_harness_errors():
    assert (
        classify_request(status=None, elapsed=0.0, timeout=1.0, transport_error=True)
        is RequestCategory.HARNESS_ERROR
    )
    # A 400 the tool knows it caused (missing params/auth) is a harness error.
    assert (
        classify_request(status=400, elapsed=0.1, timeout=1.0, harness_hint=True)
        is RequestCategory.HARNESS_ERROR
    )


# --- Stratified metrics -----------------------------------------------------


def test_compute_metrics_success_only_percentiles():
    samples = [_sample(elapsed, RequestCategory.SUCCESS, 200) for elapsed in [0.1, 0.2, 0.3, 0.4, 0.5]]
    metrics = compute_metrics(samples, phase="deep")
    assert metrics.count == 5
    assert metrics.success_count == 5
    assert metrics.success_rate == 100.0
    assert metrics.error_rate == 0.0
    assert metrics.p95 == pytest.approx(0.48)
    assert metrics.p99 == pytest.approx(0.496)
    assert metrics.mean == pytest.approx(0.3)
    assert metrics.phase == "deep"
    assert metrics.quality == "ok"


def test_compute_metrics_excludes_failures_from_percentiles():
    # Two fast failures and two slow-ish successes: the fast failures must NOT
    # pull P95 down, and a slow timeout must not push it up.
    samples = [
        _sample(0.001, RequestCategory.CLIENT_ERROR, 400),  # fast validation failure
        _sample(0.002, RequestCategory.CLIENT_ERROR, 400),
        _sample(0.4, RequestCategory.SUCCESS, 200),
        _sample(0.5, RequestCategory.SUCCESS, 200),
        _sample(5.0, RequestCategory.TIMEOUT, None),  # slow timeout
    ]
    metrics = compute_metrics(samples)
    assert metrics.success_count == 2
    assert metrics.error_count == 3  # 2 client + 1 timeout
    # success-only P95 over [0.4, 0.5] via linear interpolation = 0.495.
    assert metrics.p95 == pytest.approx(0.495)
    assert metrics.error_rate == pytest.approx(60.0)
    assert metrics.timeout_count == 1
    assert metrics.client_error_count == 2


def test_compute_metrics_harness_errors_excluded_from_rates():
    samples = [
        _sample(0.001, RequestCategory.HARNESS_ERROR, None),  # connection refused
        _sample(0.2, RequestCategory.SUCCESS, 200),
        _sample(0.3, RequestCategory.SUCCESS, 200),
    ]
    metrics = compute_metrics(samples)
    # Effective requests = 2 (harness error excluded from the denominator).
    assert metrics.success_rate == pytest.approx(100.0)
    assert metrics.error_rate == pytest.approx(0.0)
    assert metrics.harness_error_count == 1


def test_compute_metrics_no_success_is_critical():
    samples = [_sample(0.05, RequestCategory.SERVER_ERROR, 500) for _ in range(3)]
    metrics = compute_metrics(samples)
    assert metrics.p95 == 0.0  # no success samples
    assert metrics.error_rate == pytest.approx(100.0)
    assert metrics.quality == "critical"


def test_quality_flag_thresholds():
    assert quality_flag(0.0, 10) == "ok"
    assert quality_flag(1.0, 10) == "ok"
    assert quality_flag(1.5, 10) == "warn"
    assert quality_flag(5.1, 10) == "critical"
    assert quality_flag(0.0, 0) == "critical"  # no successes


def test_status_codes_preserved():
    samples = [
        _sample(0.1, RequestCategory.SUCCESS, 200),
        _sample(0.2, RequestCategory.SUCCESS, 200),
        _sample(0.3, RequestCategory.SERVER_ERROR, 500),
    ]
    metrics = compute_metrics(samples)
    assert metrics.status_codes == {200: 2, 500: 1}


def test_compute_metrics_carries_retry_and_drop():
    samples = [_sample(0.2, RequestCategory.SUCCESS, 200)]
    metrics = compute_metrics(samples, retry_count=2, dropped=True)
    assert metrics.retry_count == 2
    assert metrics.dropped is True
    assert metrics.count == 1  # logical requests, retries tracked separately


# --- Selection & ranking ----------------------------------------------------


def test_select_deep_count():
    assert select_deep_count(100, 20) == 20  # count
    assert select_deep_count(100, 0.2) == 20  # fraction
    assert select_deep_count(7, 0.2) == 2  # ceil
    assert select_deep_count(5, 100) == 5  # capped at total
    assert select_deep_count(0, 20) == 0


def test_select_deep_returns_slowest():
    results = [
        _result("/fast", 0.01),
        _result("/slow", 0.9),
        _result("/mid", 0.5),
    ]
    selected = select_deep(results, 2)
    assert [r.endpoint.path for r in selected] == ["/slow", "/mid"]


def test_merge_results_prefers_deep_and_sorts():
    quick = [_result("/fast", 0.01), _result("/slow", 0.5)]
    deep = [_result("/slow", 1.0, phase="deep")]
    merged = merge_results(quick, deep)
    assert merged[0].endpoint.path == "/slow"
    assert merged[0].metrics.p95 == 1.0
    assert merged[0].metrics.phase == "deep"
    assert merged[1].endpoint.path == "/fast"
    assert merged[1].metrics.phase == "quick"


def test_merge_results_no_success_ranks_first():
    broken = _result("/broken", 0.0, success_count=0)
    ok = _result("/ok", 0.2, success_count=1)
    merged = merge_results([ok, broken], [])
    assert merged[0].endpoint.path == "/broken"  # worst case surfaces first
