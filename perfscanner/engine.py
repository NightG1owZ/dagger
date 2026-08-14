"""Async load-test engine: fires concurrent requests and collects timings."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import aiohttp

from .analyzer import compute_metrics, merge_results, select_deep
from .models import Endpoint, EndpointResult

# Number of in-flight requests against a single endpoint.
PER_ENDPOINT_CONCURRENCY = 10
# If an endpoint's failure rate exceeds this, we start throttling.
FAILURE_RATE_LIMIT = 0.5

ProgressCallback = Callable[[EndpointResult], Awaitable[None]]


class LoadEngine:
    """Coordinates concurrent load-testing of discovered endpoints."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        max_parallel: int = 5,
        headers: dict[str, str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_parallel = max_parallel
        self.headers = {"X-Perf-Test": "True", "User-Agent": "PerfScanner/0.1"}
        if headers:
            self.headers.update(headers)
        self._concurrency = PER_ENDPOINT_CONCURRENCY
        self._failure_streak = 0

    async def run_funnel(
        self,
        endpoints: list[Endpoint],
        quick_requests: int,
        deep_requests: int,
        deep_threshold: float,
        on_endpoint: ProgressCallback | None = None,
    ) -> list[EndpointResult]:
        """Two-phase funnel: quick scan all, then deep test the slowest."""
        quick_results = await self.run(endpoints, quick_requests, phase="quick", on_endpoint=on_endpoint)
        deep_targets = select_deep(quick_results, deep_threshold)
        deep_results = await self.run(
            [r.endpoint for r in deep_targets],
            deep_requests,
            phase="deep",
            on_endpoint=on_endpoint,
        )
        return merge_results(quick_results, deep_results)

    async def run(
        self,
        endpoints: list[Endpoint],
        requests_per_endpoint: int,
        phase: str = "quick",
        on_endpoint: ProgressCallback | None = None,
    ) -> list[EndpointResult]:
        """Run one phase across all endpoints, limited to max_parallel at once."""
        results: list[EndpointResult] = []
        endpoint_sem = asyncio.Semaphore(self.max_parallel)

        async with aiohttp.ClientSession(headers=self.headers) as session:
            tasks = [
                self._test_endpoint(session, ep, requests_per_endpoint, phase, endpoint_sem)
                for ep in endpoints
            ]
            for task in asyncio.as_completed(tasks):
                result = await task
                results.append(result)
                if on_endpoint:
                    await on_endpoint(result)

        # Restore input order.
        order = {id(ep): i for i, ep in enumerate(endpoints)}
        results.sort(key=lambda r: order.get(id(r.endpoint), len(endpoints)))
        return results

    async def _test_endpoint(
        self,
        session: aiohttp.ClientSession,
        endpoint: Endpoint,
        n: int,
        phase: str,
        endpoint_sem: asyncio.Semaphore,
    ) -> EndpointResult:
        async with endpoint_sem:
            latencies: list[float] = []
            status_codes: dict[int, int] = {}
            error_count = 0
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            req_sem = asyncio.Semaphore(min(self._concurrency, max(1, n)))

            async def fire() -> None:
                nonlocal error_count
                async with req_sem:
                    # Start timing after the semaphore so queueing is not
                    # mistaken for server latency.
                    start = time.perf_counter()
                    try:
                        async with session.request(
                            endpoint.http_method, endpoint.full_url, timeout=timeout
                        ) as resp:
                            await resp.read()
                            latencies.append(time.perf_counter() - start)
                            status_codes[resp.status] = status_codes.get(resp.status, 0) + 1
                    except Exception:
                        # Record the elapsed time on failure too, so a timeout
                        # is ranked as slow rather than dropped from the samples.
                        error_count += 1
                        latencies.append(time.perf_counter() - start)

            await asyncio.gather(*(fire() for _ in range(n)))

            # Treat network errors and 5xx responses as failures for throttling.
            http_server_errors = sum(c for s, c in status_codes.items() if s >= 500)
            self._maybe_throttle(error_count + http_server_errors, n)
            return EndpointResult(
                endpoint=endpoint,
                metrics=compute_metrics(latencies, status_codes, phase=phase),
            )

    def _maybe_throttle(self, error_count: int, total: int) -> None:
        """Protect the target: reduce per-endpoint concurrency on sustained 5xx/timeouts."""
        if total == 0:
            return
        failure_rate = error_count / total
        if failure_rate >= FAILURE_RATE_LIMIT:
            self._failure_streak += 1
        else:
            self._failure_streak = 0

        if self._failure_streak >= 3:
            self._concurrency = max(1, self._concurrency // 2)
            self._failure_streak = 0
