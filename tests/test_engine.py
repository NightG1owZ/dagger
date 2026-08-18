"""Tests for the async load engine against an in-process aiohttp server."""

import asyncio
from collections.abc import Callable

import pytest
from aiohttp import web

from perfscanner.engine import LoadEngine
from perfscanner.models import Endpoint

SLOW_PATH = "/api/slow"
FAST_PATH = "/api/fast"


def _endpoint(base_url, path):
    return Endpoint(
        http_method="GET",
        path=path,
        resolved_path=path,
        full_url=base_url + path,
        class_name="C",
        method_name="m",
    )


async def _serve(routes: dict[str, Callable[[web.Request], web.Response]]):
    """Spin up an ephemeral aiohttp server; returns ``(base_url, cleanup)``."""
    app = web.Application()
    for path, handler in routes.items():
        app.router.add_get(path, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = site._server.sockets[0].getsockname()[:2]  # noqa: SLF001
    return f"http://{host}:{port}", runner.cleanup


@pytest.mark.asyncio
async def test_run_collects_metrics(async_server):
    engine = LoadEngine(async_server, timeout=5, max_parallel=2)
    endpoints = [_endpoint(async_server, SLOW_PATH), _endpoint(async_server, FAST_PATH)]

    results = await engine.run(endpoints, requests_per_endpoint=20)

    assert len(results) == 2
    for r in results:
        assert r.metrics.requests_sent == 20
        assert r.metrics.success_rate == 100.0
        assert r.metrics.error_rate == 0.0
        assert r.metrics.quality == "ok"
        assert r.metrics.phase == "quick"

    slow = next(r for r in results if r.endpoint.path == SLOW_PATH)
    fast = next(r for r in results if r.endpoint.path == FAST_PATH)
    assert slow.metrics.p95 > fast.metrics.p95


@pytest.mark.asyncio
async def test_run_funnel_marks_slow_as_deep(async_server):
    engine = LoadEngine(async_server, timeout=5, max_parallel=2)
    endpoints = [_endpoint(async_server, SLOW_PATH), _endpoint(async_server, FAST_PATH)]

    results = await engine.run_funnel(
        endpoints, quick_requests=15, deep_requests=30, deep_threshold=1
    )

    assert len(results) == 2
    slow = next(r for r in results if r.endpoint.path == SLOW_PATH)
    fast = next(r for r in results if r.endpoint.path == FAST_PATH)
    assert slow.metrics.phase == "deep"
    assert fast.metrics.phase == "quick"
    # slowest first
    assert results[0].endpoint.path == SLOW_PATH


@pytest.mark.asyncio
async def test_run_connection_error_is_harness_error():
    # Port 0 is invalid to connect to, so aiohttp raises ClientConnectorError
    # immediately and deterministically (a closed localhost port can blackhole
    # into a connect timeout on some OSes).
    base = "http://127.0.0.1:0"
    engine = LoadEngine(base, timeout=1, max_parallel=2)
    results = await engine.run([_endpoint(base, "/nope")], requests_per_endpoint=5)

    m = results[0].metrics
    assert m.harness_error_count == 5
    assert m.error_count == 0  # not a system error
    assert m.success_rate == 0.0
    assert m.error_rate == 0.0  # harness errors excluded from denominator


@pytest.mark.asyncio
async def test_run_timeout_counted_separately():
    async def slow_handler(request: web.Request) -> web.Response:
        await asyncio.sleep(0.5)
        return web.json_response({"ok": True})

    base, cleanup = await _serve({"/hang": slow_handler})

    try:
        engine = LoadEngine(base, timeout=0.1, max_parallel=1)
        results = await engine.run([_endpoint(base, "/hang")], requests_per_endpoint=5)
    finally:
        await cleanup()

    m = results[0].metrics
    assert m.timeout_count == 5
    assert m.error_rate == pytest.approx(100.0)
    assert m.p95 == 0.0  # no success samples -> no latency percentile
    assert m.quality == "critical"


@pytest.mark.asyncio
async def test_run_http_errors_classified_and_excluded_from_p95():
    async def ok(request: web.Request) -> web.Response:
        await asyncio.sleep(0.03)
        return web.json_response({"ok": True})

    async def bad(request: web.Request) -> web.Response:
        return web.Response(text="validation failed", status=400)

    async def boom(request: web.Request) -> web.Response:
        return web.Response(text="boom", status=500)

    base, cleanup = await _serve({"/ok": ok, "/bad": bad, "/boom": boom})

    try:
        engine = LoadEngine(base, timeout=5, max_parallel=3, drop_failure_rate=None)
        endpoints = [
            _endpoint(base, "/ok"),
            _endpoint(base, "/bad"),
            _endpoint(base, "/boom"),
        ]
        results = await engine.run(endpoints, requests_per_endpoint=20)
    finally:
        await cleanup()

    ok_m = next(r for r in results if r.endpoint.path == "/ok").metrics
    bad_m = next(r for r in results if r.endpoint.path == "/bad").metrics
    boom_m = next(r for r in results if r.endpoint.path == "/boom").metrics

    assert ok_m.success_count == 20
    assert ok_m.p95 > 0.0

    # Fast 400s are client errors, not a "fast" success that would distort P95.
    assert bad_m.client_error_count == 20
    assert bad_m.success_count == 0
    assert bad_m.p95 == 0.0
    assert bad_m.error_rate == pytest.approx(100.0)

    assert boom_m.server_error_count == 20
    assert boom_m.error_rate == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_run_sets_perf_header():
    captured = {}

    async def echo(request: web.Request) -> web.Response:
        captured["header"] = request.headers.get("X-Perf-Test")
        return web.Response(text="ok")

    base, cleanup = await _serve({"/x": echo})

    try:
        engine = LoadEngine(base, timeout=5, max_parallel=1)
        await engine.run([_endpoint(base, "/x")], requests_per_endpoint=1)
    finally:
        await cleanup()

    assert captured.get("header") == "True"


@pytest.mark.asyncio
async def test_run_retries_transient_timeout_then_succeeds():
    attempts = {"n": 0}

    async def flaky(request: web.Request) -> web.Response:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            await asyncio.sleep(0.3)  # exceeds the 0.1s timeout -> TIMEOUT
        return web.Response(text="ok")

    base, cleanup = await _serve({"/flaky": flaky})

    try:
        engine = LoadEngine(
            base, timeout=0.1, max_parallel=1, max_retries=2, drop_failure_rate=None
        )
        results = await engine.run([_endpoint(base, "/flaky")], requests_per_endpoint=1)
    finally:
        await cleanup()

    m = results[0].metrics
    assert m.success_count == 1  # the logical request eventually succeeded
    assert m.retry_count == 2  # two timeouts were retried
    assert m.timeout_count == 0  # no final timeout remains
    assert m.error_rate == 0.0


@pytest.mark.asyncio
async def test_run_does_not_retry_http_errors():
    attempts = {"n": 0}

    async def bad(request: web.Request) -> web.Response:
        attempts["n"] += 1
        return web.Response(text="no", status=400)

    base, cleanup = await _serve({"/bad": bad})

    try:
        engine = LoadEngine(base, timeout=5, max_parallel=1, max_retries=3)
        results = await engine.run([_endpoint(base, "/bad")], requests_per_endpoint=5)
    finally:
        await cleanup()

    m = results[0].metrics
    assert attempts["n"] == 5  # 4xx is deterministic -> never retried
    assert m.retry_count == 0
    assert m.client_error_count == 5


@pytest.mark.asyncio
async def test_run_drops_endpoint_on_high_failure_rate():
    async def boom(request: web.Request) -> web.Response:
        return web.Response(text="boom", status=500)

    base, cleanup = await _serve({"/boom": boom})

    try:
        engine = LoadEngine(
            base,
            timeout=5,
            max_parallel=10,
            max_retries=0,
            drop_failure_rate=0.5,
            min_requests_before_drop=5,
        )
        results = await engine.run([_endpoint(base, "/boom")], requests_per_endpoint=30)
    finally:
        await cleanup()

    m = results[0].metrics
    assert m.dropped is True
    assert 5 <= m.count < 30  # dropped early, well before 30 requests
    assert m.server_error_count == m.count  # every completed request was a 500


@pytest.mark.asyncio
async def test_run_does_not_drop_healthy_endpoint():
    async def ok(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    base, cleanup = await _serve({"/ok": ok})

    try:
        engine = LoadEngine(
            base,
            timeout=5,
            max_parallel=10,
            drop_failure_rate=0.5,
            min_requests_before_drop=5,
        )
        results = await engine.run([_endpoint(base, "/ok")], requests_per_endpoint=20)
    finally:
        await cleanup()

    m = results[0].metrics
    assert m.dropped is False
    assert m.count == 20
    assert m.success_count == 20
