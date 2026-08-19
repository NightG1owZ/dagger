"""Async load-test engine: fires concurrent requests and collects timings.

Design notes (per the OpenAPI tool spec):

* ``--total-requests`` and ``--duration`` are per endpoint; duration mode
  ignores the request count.
* One logical request = 1 initial attempt + up to ``max_retries`` extra
  attempts, but **only** for transport/connection errors (no response was
  received). Timeouts count as failures and are never retried; 4xx/5xx and
  business-code rejections are deterministic answers and are never retried.
* Success means HTTP 2xx **and** (when the JSON body carries a ``code`` field)
  a business code of ``0`` or ``200`` — the same rule as the smoke test. A
  business rejection (e.g. ``{"code": 50000, "message": "..."}``) is a
  failure, otherwise the load test would keep hammering an endpoint whose
  requests all fail while reporting a 100% success rate.
* Only successful responses feed the P95/P99 percentiles.
* **Drop policy**: once enough requests have completed
  (``min_requests_before_drop``) and the failure rate reaches
  ``drop_failure_rate``, the endpoint is abandoned (``dropped=True``) and no
  further requests are sent. Set ``drop_failure_rate=None`` to disable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time

import aiohttp

from .analyzer import aggregate
from .datagen import prepare_request
from .models import ApiEndpoint, EndpointResult, Outcome
from .smoke import business_ok

logger = logging.getLogger("java.engine")

# Connection errors are retried at most this many times per logical request.
DEFAULT_MAX_RETRIES = 2
# Abandon an endpoint once its failure rate reaches this threshold ...
DEFAULT_DROP_FAILURE_RATE = 0.5
# ... after at least this many completed logical requests.
DEFAULT_MIN_REQUESTS_BEFORE_DROP = 10


class LoadEngine:
    """Load-tests endpoints one at a time, each with ``concurrency`` workers."""

    def __init__(
        self,
        concurrency: int = 10,
        timeout: float = 10.0,
        max_retries: int = DEFAULT_MAX_RETRIES,
        components: dict | None = None,
        drop_failure_rate: float | None = DEFAULT_DROP_FAILURE_RATE,
        min_requests_before_drop: int = DEFAULT_MIN_REQUESTS_BEFORE_DROP,
    ):
        self.concurrency = max(1, concurrency)
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.components = components or {}
        self._rng = random.Random()
        # None disables dropping; otherwise drop once the final failure rate
        # reaches the threshold after min_requests_before_drop samples.
        self.drop_failure_rate = drop_failure_rate
        self.min_requests_before_drop = max(1, min_requests_before_drop)

    async def load_endpoint(
        self,
        session: aiohttp.ClientSession,
        endpoint: ApiEndpoint,
        base_url: str,
        total_requests: int | None = None,
        duration: float | None = None,
    ) -> EndpointResult:
        """Load-test a single endpoint; exactly one of the two modes applies."""
        outcomes: list[Outcome] = []
        retries = 0
        failures = 0
        dropped = False
        fired = 0
        lock = asyncio.Lock()
        deadline = time.monotonic() + duration if duration else None
        client_timeout = aiohttp.ClientTimeout(total=self.timeout)

        async def worker() -> None:
            nonlocal fired, retries, failures, dropped
            while True:
                async with lock:
                    if dropped:
                        return
                    if duration is not None:
                        if time.monotonic() >= deadline:
                            return
                    elif fired >= (total_requests or 0):
                        return
                    fired += 1
                url, kwargs = prepare_request(
                    endpoint, base_url, self.components, self._rng
                )
                outcome, retried = await self._fire(
                    session, endpoint, url, kwargs, client_timeout
                )
                async with lock:
                    outcomes.append(outcome)
                    retries += retried
                    if not outcome.ok:
                        failures += 1
                    if (
                        self.drop_failure_rate is not None
                        and len(outcomes) >= self.min_requests_before_drop
                        and failures / len(outcomes) >= self.drop_failure_rate
                    ):
                        dropped = True

        await asyncio.gather(*(worker() for _ in range(self.concurrency)))
        return aggregate(
            endpoint, outcomes, retries=retries, dropped=dropped
        )

    async def _fire(
        self,
        session: aiohttp.ClientSession,
        endpoint: ApiEndpoint,
        url: str,
        kwargs: dict,
        timeout: aiohttp.ClientTimeout,
    ) -> tuple[Outcome, int]:
        """One logical request with up to ``max_retries`` connection retries."""
        retried = 0
        while True:
            outcome = await self._attempt(session, endpoint, url, kwargs, timeout)
            if (
                outcome.ok
                or outcome.error != "connection"
                or retried >= self.max_retries
            ):
                return outcome, retried
            retried += 1

    async def _attempt(
        self,
        session: aiohttp.ClientSession,
        endpoint: ApiEndpoint,
        url: str,
        kwargs: dict,
        timeout: aiohttp.ClientTimeout,
    ) -> Outcome:
        start = time.perf_counter()
        try:
            async with session.request(
                endpoint.method, url, timeout=timeout, **kwargs
            ) as resp:
                raw = await resp.read()
                elapsed = time.perf_counter() - start
                if 200 <= resp.status < 300:
                    ok, _ = self._business_check(resp, raw)
                    if ok:
                        return Outcome(elapsed, True, resp.status)
                    # HTTP 2xx but the business code says "no" (e.g.
                    # {"code": 50000, "message": "..."}): a real failure.
                    return Outcome(elapsed, False, resp.status, "business")
                return Outcome(elapsed, False, resp.status, "http")
        except (asyncio.TimeoutError, TimeoutError):
            # Deadline exceeded -> failure, never retried.
            return Outcome(time.perf_counter() - start, False, None, "timeout")
        except (TypeError, ValueError):
            # Tool-side request construction bug (e.g. a bad query value):
            # deterministic, never worth a retry.
            return Outcome(time.perf_counter() - start, False, None, "harness")
        except (aiohttp.ClientConnectionError, aiohttp.ClientError):
            # Connection refused/reset, DNS or TLS failure -> no response
            # received, worth another attempt.
            return Outcome(time.perf_counter() - start, False, None, "connection")
        except Exception:  # noqa: BLE001 - any transport-level surprise
            return Outcome(time.perf_counter() - start, False, None, "connection")

    @staticmethod
    def _business_check(resp: aiohttp.ClientResponse, raw: bytes) -> tuple[bool, str]:
        """Validate a 2xx response with the same business-code rule as smoke.

        Returns ``(ok, reason)``. Non-JSON bodies always pass (like smoke).
        """
        text = raw.decode("utf-8", errors="replace")
        ctype = resp.headers.get("Content-Type", "")
        if "json" not in ctype and not text.lstrip().startswith(("{", "[")):
            return True, ""
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            return True, ""
        return business_ok(resp.status, body)
