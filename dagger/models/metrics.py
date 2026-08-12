from dataclasses import dataclass, field
from collections import Counter
import time
import math

from .result import RequestResult


@dataclass
class Percentiles:
    """Pre-computed percentile values for a latency distribution."""

    min: float = 0.0
    p50: float = 0.0
    p75: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    p99_9: float = 0.0
    max: float = 0.0
    mean: float = 0.0
    stddev: float = 0.0
    count: int = 0


@dataclass
class MetricsSnapshot:
    """Point-in-time metrics for live display updates."""

    elapsed: float = 0.0
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    requests_per_second: float = 0.0
    latencies: Percentiles = field(default_factory=Percentiles)
    status_codes: Counter[int] = field(default_factory=Counter)
    errors: Counter[str] = field(default_factory=Counter)
    active_users: int = 0
    bytes_received: int = 0
    bytes_sent: int = 0


@dataclass
class ErrorGroup:
    """Aggregated error information for reporting."""

    error_type: str
    count: int
    percentage: float
    example: str


@dataclass
class TimeSeriesPoint:
    """A single data point in a time series."""

    elapsed: float
    rps: float
    p50: float
    p90: float
    p99: float
    error_rate: float


@dataclass
class MetricsSummary:
    """Complete aggregated metrics for final report generation."""

    config_summary: dict = field(default_factory=dict)
    duration: float = 0.0
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    success_rate: float = 0.0
    avg_rps: float = 0.0
    peak_rps: float = 0.0
    latencies: Percentiles = field(default_factory=Percentiles)
    status_codes: Counter[int] = field(default_factory=Counter)
    errors: list[ErrorGroup] = field(default_factory=list)
    time_series: list[TimeSeriesPoint] = field(default_factory=list)
    bytes_received: int = 0
    bytes_sent: int = 0
    histogram_buckets: list[tuple[float, int]] = field(default_factory=list)


class Histogram:
    """HDR-style log-linear histogram for latency distribution tracking."""

    # Pre-computed bucket boundaries covering 1ms to 60s range
    _BOUNDARIES: list[float] = []

    @classmethod
    def _init_boundaries(cls) -> list[float]:
        if cls._BOUNDARIES:
            return cls._BOUNDARIES
        boundaries: list[float] = []
        # 1ms to 1000ms: 1ms steps for first 10ms, then progressively wider
        for ms in range(1, 11):
            boundaries.append(ms / 1000.0)
        for ms in range(12, 101, 2):
            boundaries.append(ms / 1000.0)
        for ms in range(110, 1001, 10):
            boundaries.append(ms / 1000.0)
        # 1s to 60s
        for s in range(1, 61):
            boundaries.append(float(s))
        cls._BOUNDARIES = boundaries
        return boundaries

    def __init__(self):
        self._boundaries = self._init_boundaries()
        self._counts: list[int] = [0] * (len(self._boundaries) + 1)
        self._count = 0
        self._sum = 0.0
        self._sum_sq = 0.0
        self._min = float("inf")
        self._max = float("-inf")
        self._sorted_values: list[float] = []

    def record(self, value: float) -> None:
        self._count += 1
        self._sum += value
        self._sum_sq += value * value
        if value < self._min:
            self._min = value
        if value > self._max:
            self._max = value

        idx = 0
        for boundary in self._boundaries:
            if value <= boundary:
                break
            idx += 1
        else:
            idx = len(self._boundaries)
        self._counts[idx] += 1

        self._sorted_values.append(value)

    def percentile(self, p: float) -> float:
        if self._count == 0:
            return 0.0
        if self._count <= 1:
            return self._sorted_values[0] if self._sorted_values else 0.0

        self._sorted_values.sort()
        rank = (p / 100.0) * (self._count - 1)
        lower = int(rank)
        upper = lower + 1
        if upper >= self._count:
            return self._sorted_values[-1]
        weight = rank - lower
        return self._sorted_values[lower] * (1 - weight) + self._sorted_values[upper] * weight

    @property
    def count(self) -> int:
        return self._count

    @property
    def min(self) -> float:
        return self._min if self._count > 0 else 0.0

    @property
    def max(self) -> float:
        return self._max if self._count > 0 else 0.0

    @property
    def mean(self) -> float:
        return self._sum / self._count if self._count > 0 else 0.0

    @property
    def stddev(self) -> float:
        if self._count < 2:
            return 0.0
        variance = (self._sum_sq - (self._sum ** 2) / self._count) / (self._count - 1)
        return math.sqrt(max(0, variance))

    def to_percentiles(self) -> Percentiles:
        return Percentiles(
            min=self.min * 1000,
            p50=self.percentile(50) * 1000,
            p75=self.percentile(75) * 1000,
            p90=self.percentile(90) * 1000,
            p95=self.percentile(95) * 1000,
            p99=self.percentile(99) * 1000,
            p99_9=self.percentile(99.9) * 1000,
            max=self.max * 1000,
            mean=self.mean * 1000,
            stddev=self.stddev * 1000,
            count=self._count,
        )

    def to_buckets(self) -> list[tuple[float, int]]:
        result: list[tuple[float, int]] = []
        for i, boundary in enumerate(self._boundaries):
            if self._counts[i] > 0:
                result.append((boundary * 1000, self._counts[i]))
        if self._counts[-1] > 0:
            result.append((float("inf"), self._counts[-1]))
        return result


class MetricsCollector:
    """Collects and aggregates request metrics during a test run."""

    def __init__(self, max_raw_samples: int = 100_000):
        self._histogram = Histogram()
        self._start_time = time.monotonic()
        self._total_requests = 0
        self._successful = 0
        self._failed = 0
        self._bytes_received = 0
        self._bytes_sent = 0
        self._status_codes: Counter[int] = Counter()
        self._errors: Counter[str] = Counter()
        self._error_examples: dict[str, str] = {}

        # Sliding window for RPS calculation (last 5 seconds)
        self._recent_times: list[float] = []

        # Time series data (snapshots every second)
        self._time_series: list[TimeSeriesPoint] = []
        self._last_series_time = self._start_time
        self._series_requests = 0
        self._series_successful = 0
        self._series_latencies: list[float] = []

    def record(self, result: RequestResult) -> None:
        self._total_requests += 1
        now = time.monotonic()

        if result.is_success:
            self._successful += 1
            self._series_successful += 1
        else:
            self._failed += 1

        self._bytes_received += result.response_size
        self._series_requests += 1

        if result.status_code is not None:
            self._status_codes[result.status_code] += 1

        if result.error:
            self._errors[result.error] += 1
            if result.error not in self._error_examples and result.error_detail:
                self._error_examples[result.error] = result.error_detail[:200]

        self._histogram.record(result.latency)

        # Maintain sliding window for RPS
        self._recent_times.append(now)
        cutoff = now - 5.0
        self._recent_times = [t for t in self._recent_times if t >= cutoff]

        # Time series aggregation (per second)
        if now - self._last_series_time >= 1.0:
            self._flush_time_series(now)

    def _flush_time_series(self, now: float) -> None:
        if self._series_requests == 0:
            return

        interval = now - self._last_series_time
        rps = self._series_requests / interval if interval > 0 else 0
        error_rate = (self._series_requests - self._series_successful) / self._series_requests if self._series_requests > 0 else 0

        if self._series_latencies:
            self._series_latencies.sort()
            p50 = self._series_latencies[int(len(self._series_latencies) * 0.50)]
            p90 = self._series_latencies[int(len(self._series_latencies) * 0.90)]
            p99 = self._series_latencies[int(len(self._series_latencies) * 0.99)] if len(self._series_latencies) >= 100 else p90
        else:
            p50 = p90 = p99 = 0.0

        self._time_series.append(TimeSeriesPoint(
            elapsed=now - self._start_time,
            rps=rps,
            p50=p50 * 1000,
            p90=p90 * 1000,
            p99=p99 * 1000,
            error_rate=error_rate * 100,
        ))

        self._last_series_time = now
        self._series_requests = 0
        self._series_successful = 0
        self._series_latencies.clear()

    def snapshot(self) -> MetricsSnapshot:
        now = time.monotonic()
        recent_count = len(self._recent_times)
        if recent_count >= 2:
            window = self._recent_times[-1] - self._recent_times[0]
            rps = recent_count / window if window > 0 else 0
        else:
            rps = 0.0

        return MetricsSnapshot(
            elapsed=now - self._start_time,
            total_requests=self._total_requests,
            successful=self._successful,
            failed=self._failed,
            requests_per_second=rps,
            latencies=self._histogram.to_percentiles(),
            status_codes=self._status_codes.copy(),
            errors=self._errors.copy(),
            active_users=0,  # Set by engine
            bytes_received=self._bytes_received,
            bytes_sent=self._bytes_sent,
        )

    def finalize(self, config_summary: dict) -> MetricsSummary:
        """Produce final summary after test completion."""
        self._flush_time_series(time.monotonic())

        duration = time.monotonic() - self._start_time
        avg_rps = self._total_requests / duration if duration > 0 else 0
        peak_rps = max((p.rps for p in self._time_series), default=0.0)

        errors = []
        total_err = sum(self._errors.values())
        for error_type, count in self._errors.most_common():
            errors.append(ErrorGroup(
                error_type=error_type,
                count=count,
                percentage=(count / self._total_requests * 100) if self._total_requests > 0 else 0,
                example=self._error_examples.get(error_type, ""),
            ))

        return MetricsSummary(
            config_summary=config_summary,
            duration=duration,
            total_requests=self._total_requests,
            successful=self._successful,
            failed=self._failed,
            success_rate=(self._successful / self._total_requests * 100) if self._total_requests > 0 else 0,
            avg_rps=avg_rps,
            peak_rps=peak_rps,
            latencies=self._histogram.to_percentiles(),
            status_codes=self._status_codes.copy(),
            errors=errors,
            time_series=self._time_series.copy(),
            bytes_received=self._bytes_received,
            bytes_sent=self._bytes_sent,
            histogram_buckets=self._histogram.to_buckets(),
        )
