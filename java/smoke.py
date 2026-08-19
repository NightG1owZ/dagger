"""Smoke test (precheck): one request per endpoint before load testing.

An endpoint "passes" when it returns HTTP 2xx and, when the JSON response
carries a business ``code`` field, that code is ``0`` or ``200``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time

import aiohttp

from .datagen import prepare_request
from .models import ApiEndpoint, SmokeResult

logger = logging.getLogger("java.smoke")


def business_ok(status: int, body) -> tuple[bool, str]:
    """Check HTTP 2xx plus the business ``code`` field when present."""
    if not (200 <= status < 300):
        return False, f"HTTP {status}"
    if isinstance(body, dict) and "code" in body:
        code = body["code"]
        if isinstance(code, str) and code.isdigit():
            code = int(code)
        if code not in (0, 200):
            return False, f"业务码 {body['code']}"
    return True, ""


def _snippet(text: str, limit: int = 60) -> str:
    compact = " ".join(text.split())
    return f": {compact[:limit]}" if compact else ""


async def smoke_endpoint(
    session: aiohttp.ClientSession,
    endpoint: ApiEndpoint,
    base_url: str,
    components: dict,
    rng: random.Random,
    timeout: float,
) -> SmokeResult:
    """Send one request and decide whether the endpoint is testable."""
    url, kwargs = prepare_request(endpoint, base_url, components, rng)
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    try:
        async with session.request(
            endpoint.method, url, timeout=client_timeout, **kwargs
        ) as resp:
            raw = await resp.read()
            text = raw.decode("utf-8", errors="replace")
            body = None
            ctype = resp.headers.get("Content-Type", "")
            if "json" in ctype or text.lstrip().startswith(("{", "[")):
                try:
                    body = json.loads(text)
                except json.JSONDecodeError:
                    body = None
            ok, reason = business_ok(resp.status, body)
            if ok:
                return SmokeResult(True, resp.status)
            return SmokeResult(False, resp.status, reason + _snippet(text))
    except (asyncio.TimeoutError, TimeoutError):
        return SmokeResult(False, None, f"请求超时(>{timeout}s)")
    except aiohttp.ClientConnectionError as exc:
        return SmokeResult(False, None, f"连接失败: {type(exc).__name__}")
    except Exception as exc:  # noqa: BLE001 - any failure makes the endpoint untestable
        return SmokeResult(False, None, f"请求异常: {type(exc).__name__}")
