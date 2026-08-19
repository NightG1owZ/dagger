"""Tests for the smoke test (precheck) logic."""

from __future__ import annotations

import random

import aiohttp
import pytest

from java.models import ApiEndpoint
from java.smoke import business_ok, smoke_endpoint


async def _smoke(server, path, method="GET", timeout=10.0, base=None):
    endpoint = ApiEndpoint(method=method, path=path)
    async with aiohttp.ClientSession() as session:
        return await smoke_endpoint(
            session, endpoint, base or server["base"], {}, random.Random(1), timeout
        )


@pytest.mark.asyncio
async def test_smoke_passes_on_2xx(openapi_server):
    result = await _smoke(openapi_server, "/api/fast")
    assert result.passed is True
    assert result.status == 200


@pytest.mark.asyncio
async def test_smoke_passes_with_business_code_0(openapi_server):
    result = await _smoke(openapi_server, "/api/code0")
    assert result.passed is True


@pytest.mark.asyncio
async def test_smoke_fails_on_business_code(openapi_server):
    result = await _smoke(openapi_server, "/api/biz")
    assert result.passed is False
    assert "业务码 500" in result.reason


@pytest.mark.asyncio
async def test_smoke_fails_on_http_400(openapi_server):
    result = await _smoke(openapi_server, "/api/bad")
    assert result.passed is False
    assert "HTTP 400" in result.reason


@pytest.mark.asyncio
async def test_smoke_fails_on_http_500(openapi_server):
    result = await _smoke(openapi_server, "/api/boom")
    assert result.passed is False
    assert "HTTP 500" in result.reason


@pytest.mark.asyncio
async def test_smoke_fails_on_timeout(openapi_server):
    result = await _smoke(openapi_server, "/api/sleep", timeout=0.1)
    assert result.passed is False
    assert "超时" in result.reason


@pytest.mark.asyncio
async def test_smoke_fails_on_connection_error():
    # Port 0 is never a valid connect target -> immediate connector error.
    result = await _smoke({"base": "http://127.0.0.1:0"}, "/api/x")
    assert result.passed is False
    assert "连接失败" in result.reason


def test_business_ok_rules():
    assert business_ok(200, None) == (True, "")
    assert business_ok(299, {"msg": "hi"}) == (True, "")
    assert business_ok(200, {"code": 0}) == (True, "")
    assert business_ok(200, {"code": 200}) == (True, "")
    assert business_ok(200, {"code": "0"}) == (True, "")
    assert business_ok(200, {"code": "200"}) == (True, "")
    assert business_ok(200, {"code": 500})[0] is False
    assert business_ok(200, {"code": 500})[1] == "业务码 500"
    assert business_ok(404, None)[0] is False
    assert business_ok(300, None)[0] is False
