"""Tests for the async load-test engine."""

from __future__ import annotations

import time

import aiohttp
import pytest

from java.engine import LoadEngine
from java.models import ApiEndpoint, Outcome, STATUS_INSUFFICIENT, STATUS_OK


@pytest.mark.asyncio
async def test_count_mode_exact_requests(openapi_server):
    async with aiohttp.ClientSession() as session:
        engine = LoadEngine(concurrency=4, timeout=10.0)
        result = await engine.load_endpoint(
            session,
            ApiEndpoint("GET", "/api/fast"),
            openapi_server["base"],
            total_requests=37,
        )
    assert result.requests == 37
    assert result.success == 37
    assert result.failed == 0
    assert result.status == STATUS_OK
    assert result.p95 is not None and result.p99 is not None


@pytest.mark.asyncio
async def test_http_errors_never_retried(openapi_server):
    async with aiohttp.ClientSession() as session:
        engine = LoadEngine(concurrency=1, timeout=10.0, max_retries=2)
        result = await engine.load_endpoint(
            session,
            ApiEndpoint("GET", "/api/boom"),
            openapi_server["base"],
            total_requests=5,
        )
    assert result.requests == 5
    assert result.success == 0
    assert result.failed == 5
    assert result.retries == 0  # 5xx is deterministic -> no extra attempts
    assert result.status == STATUS_INSUFFICIENT


@pytest.mark.asyncio
async def test_timeouts_count_as_failures_and_are_not_retried(openapi_server):
    async with aiohttp.ClientSession() as session:
        engine = LoadEngine(concurrency=1, timeout=0.1, max_retries=2)
        result = await engine.load_endpoint(
            session,
            ApiEndpoint("GET", "/api/sleep"),  # handler sleeps 0.5s
            openapi_server["base"],
            total_requests=3,
        )
    assert result.requests == 3
    assert result.success == 0
    assert result.failed == 3
    assert result.retries == 0  # timeouts are never retried


@pytest.mark.asyncio
async def test_connection_errors_are_retried_up_to_max():
    async with aiohttp.ClientSession() as session:
        engine = LoadEngine(concurrency=1, timeout=5.0, max_retries=2)
        # Port 0 is never connectable -> every attempt is a connection error.
        result = await engine.load_endpoint(
            session,
            ApiEndpoint("GET", "/api/x"),
            "http://127.0.0.1:0",
            total_requests=3,
        )
    assert result.requests == 3
    assert result.success == 0
    assert result.failed == 3
    assert result.retries == 6  # 3 logical requests x 2 retries each


@pytest.mark.asyncio
async def test_duration_mode_ignores_total_requests(openapi_server):
    async with aiohttp.ClientSession() as session:
        engine = LoadEngine(concurrency=4, timeout=10.0)
        start = time.monotonic()
        result = await engine.load_endpoint(
            session,
            ApiEndpoint("GET", "/api/fast"),
            openapi_server["base"],
            total_requests=100000,
            duration=0.2,
        )
        elapsed = time.monotonic() - start
    assert result.requests > 0
    assert result.success == result.requests
    assert result.status == STATUS_OK
    assert elapsed >= 0.15  # actually ran for roughly the requested duration


@pytest.mark.asyncio
async def test_generated_params_work_end_to_end(openapi_server):
    from java.models import ApiParam

    endpoint = ApiEndpoint(
        method="GET",
        path="/api/users/{id}",
        params=[
            ApiParam("id", "path", True, {"type": "integer"}),
            ApiParam("verbose", "query", False, {"type": "boolean"}),
        ],
    )
    async with aiohttp.ClientSession() as session:
        engine = LoadEngine(concurrency=2, timeout=10.0)
        result = await engine.load_endpoint(
            session, endpoint, openapi_server["base"], total_requests=12
        )
    assert result.success == 12


@pytest.mark.asyncio
async def test_fire_retries_connection_then_succeeds(monkeypatch):
    engine = LoadEngine(concurrency=1, max_retries=2)
    calls = {"n": 0}

    async def fake_attempt(session, endpoint, url, kwargs, timeout):
        calls["n"] += 1
        if calls["n"] <= 2:
            return Outcome(0.001, False, None, "connection")
        return Outcome(0.01, True, 200)

    monkeypatch.setattr(engine, "_attempt", fake_attempt)
    outcome, retried = await engine._fire(
        None, ApiEndpoint("GET", "/x"), "http://x", {}, None
    )
    assert outcome.ok and outcome.status == 200
    assert retried == 2
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_fire_does_not_retry_http_or_timeout(monkeypatch):
    engine = LoadEngine(concurrency=1, max_retries=2)
    calls = {"n": 0}

    async def fake_attempt(session, endpoint, url, kwargs, timeout):
        calls["n"] += 1
        return Outcome(0.001, False, 500, "http")

    monkeypatch.setattr(engine, "_attempt", fake_attempt)
    outcome, retried = await engine._fire(
        None, ApiEndpoint("GET", "/x"), "http://x", {}, None
    )
    assert not outcome.ok and outcome.error == "http"
    assert retried == 0 and calls["n"] == 1


# --- Business-code validation during the load test ---------------------------


@pytest.mark.asyncio
async def test_business_code_rejection_counts_as_failure(openapi_server):
    """HTTP 200 + {"code": 500} is a failure, and it is never retried."""
    async with aiohttp.ClientSession() as session:
        engine = LoadEngine(
            concurrency=2,
            timeout=10.0,
            drop_failure_rate=None,
        )
        result = await engine.load_endpoint(
            session,
            ApiEndpoint("GET", "/api/biz"),
            openapi_server["base"],
            total_requests=12,
        )
    assert result.success == 0
    assert result.failed == 12
    assert result.retries == 0  # business rejections are deterministic


@pytest.mark.asyncio
async def test_business_code_0_is_success(openapi_server):
    async with aiohttp.ClientSession() as session:
        engine = LoadEngine(concurrency=2, timeout=10.0)
        result = await engine.load_endpoint(
            session,
            ApiEndpoint("GET", "/api/code0"),
            openapi_server["base"],
            total_requests=12,
        )
    assert result.success == 12
    assert result.failed == 0
    assert result.dropped is False


# --- Drop policy -------------------------------------------------------------


@pytest.mark.asyncio
async def test_drop_abandons_endpoint_on_high_failure_rate(openapi_server):
    """All requests fail -> the endpoint is dropped right after the minimum."""
    async with aiohttp.ClientSession() as session:
        engine = LoadEngine(
            concurrency=2,
            timeout=10.0,
            drop_failure_rate=0.5,
            min_requests_before_drop=5,
        )
        result = await engine.load_endpoint(
            session,
            ApiEndpoint("GET", "/api/biz"),
            openapi_server["base"],
            total_requests=100,
        )
    assert result.dropped is True
    # Stopped right at the drop threshold; in-flight requests (at most
    # concurrency - 1 extra) are settled normally.
    assert 5 <= result.requests <= 6
    assert result.failed == result.requests
    assert result.success == 0


@pytest.mark.asyncio
async def test_no_drop_when_healthy(openapi_server):
    async with aiohttp.ClientSession() as session:
        engine = LoadEngine(
            concurrency=2,
            timeout=10.0,
            drop_failure_rate=0.5,
            min_requests_before_drop=5,
        )
        result = await engine.load_endpoint(
            session,
            ApiEndpoint("GET", "/api/fast"),
            openapi_server["base"],
            total_requests=20,
        )
    assert result.dropped is False
    assert result.requests == 20
    assert result.success == 20


@pytest.mark.asyncio
async def test_drop_disabled_when_rate_is_none(openapi_server):
    async with aiohttp.ClientSession() as session:
        engine = LoadEngine(
            concurrency=1,
            timeout=10.0,
            drop_failure_rate=None,
            min_requests_before_drop=5,
        )
        result = await engine.load_endpoint(
            session,
            ApiEndpoint("GET", "/api/biz"),
            openapi_server["base"],
            total_requests=12,
        )
    assert result.dropped is False
    assert result.requests == 12


@pytest.mark.asyncio
async def test_drop_requires_threshold(monkeypatch):
    """A low failure rate (2/8 = 0.25 < 0.5) never triggers the drop."""
    engine = LoadEngine(
        concurrency=1, drop_failure_rate=0.5, min_requests_before_drop=4
    )
    calls = {"n": 0}

    async def fake_attempt(session, endpoint, url, kwargs, timeout):
        calls["n"] += 1
        fail = calls["n"] in (1, 8)
        return Outcome(
            0.001, not fail, 500 if fail else 200, "http" if fail else ""
        )

    monkeypatch.setattr(engine, "_attempt", fake_attempt)
    result = await engine.load_endpoint(
        None, ApiEndpoint("GET", "/x"), "http://x", total_requests=8
    )
    assert result.dropped is False
    assert result.requests == 8
    assert result.failed == 2


@pytest.mark.asyncio
async def test_drop_stops_at_min_requests(monkeypatch):
    engine = LoadEngine(
        concurrency=1, drop_failure_rate=0.5, min_requests_before_drop=4
    )

    async def fake_attempt(session, endpoint, url, kwargs, timeout):
        return Outcome(0.001, False, 500, "http")

    monkeypatch.setattr(engine, "_attempt", fake_attempt)
    result = await engine.load_endpoint(
        None, ApiEndpoint("GET", "/x"), "http://x", total_requests=50
    )
    assert result.dropped is True
    assert result.requests == 4
    assert result.failed == 4
