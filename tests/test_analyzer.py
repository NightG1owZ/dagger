"""Tests for percentile computation, metrics aggregation, and selection."""

import pytest

from perfscanner.analyzer import (
    compute_metrics,
    merge_results,
    percentile,
    select_deep,
    select_deep_count,
)
from perfscanner.models import Endpoint, EndpointResult


def _result(path, p95, phase="quick"):
    ep = Endpoint(
        http_method="GET",
        path=path,
        resolved_path=path,
        full_url="http://x" + path,
        class_name="C",
        method_name="m",
    )
    from perfscanner.models import EndpointMetrics

    return EndpointResult(ep, EndpointMetrics(p95=p95, phase=phase))


def test_percentile_linear_interpolation():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 50.0) == 3.0
    assert percentile(values, 95.0) == pytest.approx(4.8)


def test_percentile_edge_cases():
    assert percentile([], 95.0) == 0.0
    assert percentile([7.0], 95.0) == 7.0
    assert percentile([1.0, 2.0, 3.0], 100.0) == 3.0


def test_compute_metrics():
    latencies = [0.1, 0.2, 0.3, 0.4, 0.5]
    metrics = compute_metrics(latencies, {200: 5}, phase="deep")
    assert metrics.count == 5
    assert metrics.success_rate == 100.0
    assert metrics.p95 == pytest.approx(0.48)
    assert metrics.p99 == pytest.approx(0.496)
    assert metrics.mean == pytest.approx(0.3)
    assert metrics.phase == "deep"


def test_compute_metrics_with_errors():
    # 4 requests: two succeeded (200), two failed (no HTTP status recorded).
    metrics = compute_metrics([0.1, 0.2, 0.05, 0.06], {200: 2})
    assert metrics.count == 4
    assert metrics.error_count == 2
    assert metrics.success_rate == pytest.approx(50.0)


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
