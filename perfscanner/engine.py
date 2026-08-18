"""Async load-test engine: fires concurrent requests and collects timings."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import aiohttp

from .analyzer import classify_request, compute_metrics, merge_results, select_deep
from .models import Endpoint, EndpointResult, RequestCategory, RequestSample

# Number of in-flight requests against a single endpoint.
PER_ENDPOINT_CONCURRENCY = 10
# If an endpoint's overload rate exceeds this, we start throttling.
FAILURE_RATE_LIMIT = 0.5
# Defaults for retry + drop knobs.
DEFAULT_MAX_RETRIES = 3
DEFAULT_DROP_FAILURE_RATE = 0.5
DEFAULT_MIN_REQUESTS_BEFORE_DROP = 10

# Categories worth retrying: no valid HTTP response was received, so another
# attempt may succeed. 4xx/5xx are deterministic server answers -> no retry.
RETRYABLE_CATEGORIES = frozenset(
    {RequestCategory.HARNESS_ERROR, RequestCategory.TIMEOUT}
)

ProgressCallback = Callable[[EndpointResult], Awaitable[None]]


class LoadEngine:
    """Coordinates concurrent load-testing of discovered endpoints."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        max_parallel: int = 5,
        headers: dict[str, str] | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        drop_failure_rate: float | None = DEFAULT_DROP_FAILURE_RATE,
        min_requests_before_drop: int = DEFAULT_MIN_REQUESTS_BEFORE_DROP,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_parallel = max_parallel
        self.headers = {"X-Perf-Test": "True", "User-Agent": "PerfScanner/0.1"}
        if headers:
            self.headers.update(headers)
        self.max_retries = max(0, max_retries)
        # None disables dropping; otherwise drop when the final failure rate
        # reaches this threshold after min_requests_before_drop samples.
        self.drop_failure_rate = drop_failure_rate
        self.min_requests_before_drop = max(1, min_requests_before_drop)
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
        """Warm up, quick-scan all, then deep-test the slowest."""
        await self._warmup(endpoints)
        quick_results = await self.run(endpoints, quick_requests, phase="quick", on_endpoint=on_endpoint)
        deep_targets = select_deep(quick_results, deep_threshold)
        deep_results = await self.run(
            [r.endpoint for r in deep_targets],
            deep_requests,
            phase="deep",
            on_endpoint=on_endpoint,
        )
        return merge_results(quick_results, deep_results)

    async def _warmup(self, endpoints: list[Endpoint]) -> None:
        """Issue one probe per endpoint to warm JIT/connections and detect dead
        endpoints before the measured run. Probe outcomes are intentionally
        discarded; the measured run classifies each request itself."""
        if not endpoints:
            return
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(headers=self.headers) as session:
            await asyncio.gather(
                *(self._probe(session, ep, timeout) for ep in endpoints),
                return_exceptions=True,
            )

    async def _probe(self, session: aiohttp.ClientSession, endpoint: Endpoint, timeout) -> None:
        try:
            async with session.request(
                endpoint.http_method, endpoint.full_url, timeout=timeout
            ) as resp:
                await resp.read()
        except Exception:
            # Warm-up best effort: dead endpoints are classified during the run.
            pass

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
            samples: list[RequestSample] = []
            retry_total = 0
            completed = 0
            failures = 0
            dropped = False
            lock = asyncio.Lock()
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            req_sem = asyncio.Semaphore(min(self._concurrency, max(1, n)))

            async def fire() -> None:
                nonlocal retry_total, completed, failures, dropped
                if dropped:
                    return
                async with req_sem:
                    if dropped:
                        return
                    sample, retries = await self._request_with_retry(
                        session, endpoint, timeout
                    )
                    async with lock:
                        samples.append(sample)
                        retry_total += retries
                        completed += 1
                        if sample.category is not RequestCategory.SUCCESS:
                            failures += 1
                        if (
                            self.drop_failure_rate is not None
                            and completed >= self.min_requests_before_drop
                            and failures / completed >= self.drop_failure_rate
                        ):
                            dropped = True

            await asyncio.gather(*(fire() for _ in range(n)))

            metrics = compute_metrics(
                samples, phase=phase, retry_count=retry_total, dropped=dropped
            )
            # Throttle on genuine overload signals only (5xx + timeouts), not on
            # client errors or harness errors.
            self._maybe_throttle(
                metrics.server_error_count + metrics.timeout_count, max(1, metrics.count)
            )
            return EndpointResult(endpoint=endpoint, metrics=metrics)

    async def _request_with_retry(
        self,
        session: aiohttp.ClientSession,
        endpoint: Endpoint,
        timeout: aiohttp.ClientTimeout,
    ) -> tuple[RequestSample, int]:
        """Fire one logical request, retrying transient failures up to max_retries.

        Returns ``(final_sample, retries_used)``.
        """
        retries = 0
        while True:
            sample = await self._fire_once(session, endpoint, timeout)
            if sample.category in RETRYABLE_CATEGORIES and retries < self.max_retries:
                retries += 1
                continue
            return sample, retries

    async def _fire_once(
        self,
        session: aiohttp.ClientSession,
        endpoint: Endpoint,
        timeout: aiohttp.ClientTimeout,
    ) -> RequestSample:
        """Send a single HTTP request and classify the outcome."""
        # Start timing after the semaphore so queueing is not mistaken for
        # server latency.
        start = time.perf_counter()
        try:
            async with session.request(
                endpoint.http_method, endpoint.full_url, timeout=timeout
            ) as resp:
                await resp.read()
                elapsed = time.perf_counter() - start
                category = classify_request(
                    status=resp.status,
                    elapsed=elapsed,
                    timeout=self.timeout,
                )
                return RequestSample(elapsed, category, resp.status)
        except (asyncio.TimeoutError, TimeoutError):
            return RequestSample(
                time.perf_counter() - start, RequestCategory.TIMEOUT, None
            )
        except aiohttp.ClientConnectionError:
            # Connection refused/reset, DNS failure, TLS error:
            # the tool or environment is wrong, not the system.
            return RequestSample(
                time.perf_counter() - start, RequestCategory.HARNESS_ERROR, None
            )
        except Exception:
            return RequestSample(
                time.perf_counter() - start, RequestCategory.HARNESS_ERROR, None
            )

    def _maybe_throttle(self, error_count: int, total: int) -> None:
        """Protect the target: reduce per-endpoint concurrency on sustained overload."""
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
