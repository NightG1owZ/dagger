"""Tests for the async load engine against an in-process aiohttp server."""

import asyncio

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


@pytest.mark.asyncio
async def test_run_collects_metrics(async_server):
    engine = LoadEngine(async_server, timeout=5, max_parallel=2)
    endpoints = [_endpoint(async_server, SLOW_PATH), _endpoint(async_server, FAST_PATH)]

    results = await engine.run(endpoints, requests_per_endpoint=20)

    assert len(results) == 2
    for r in results:
        assert r.metrics.requests_sent == 20
        assert r.metrics.success_rate == 100.0
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
async def test_run_handles_timeouts():
    # A port with no listener -> connection errors are recorded, not raised.
    engine = LoadEngine("http://127.0.0.1:1", timeout=1, max_parallel=2)
    endpoints = [_endpoint("http://127.0.0.1:1", "/nope")]

    results = await engine.run(endpoints, requests_per_endpoint=5)

    assert len(results) == 1
    assert results[0].metrics.error_count == 5
    assert results[0].metrics.success_rate == 0.0


@pytest.mark.asyncio
async def test_run_timeout_recorded_as_slow():
    async def slow_handler(request: web.Request) -> web.Response:
        await asyncio.sleep(0.5)
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_get("/hang", slow_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = site._server.sockets[0].getsockname()[:2]  # noqa: SLF001
    base = f"http://{host}:{port}"

    try:
        engine = LoadEngine(base, timeout=0.1, max_parallel=1)
        results = await engine.run([_endpoint(base, "/hang")], requests_per_endpoint=5)
    finally:
        await runner.cleanup()

    m = results[0].metrics
    assert m.error_count == 5  # all requests timed out
    assert m.success_rate == 0.0
    assert m.p95 > 0.0  # timeouts counted as slow, not dropped to 0


@pytest.mark.asyncio
async def test_run_sets_perf_header():
    captured = {}

    async def echo(request: web.Request) -> web.Response:
        captured["header"] = request.headers.get("X-Perf-Test")
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/x", echo)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = site._server.sockets[0].getsockname()[:2]  # noqa: SLF001
    base = f"http://{host}:{port}"

    try:
        engine = LoadEngine(base, timeout=5, max_parallel=1)
        await engine.run([_endpoint(base, "/x")], requests_per_endpoint=1)
    finally:
        await runner.cleanup()

    assert captured.get("header") == "True"
