from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from .enums import HttpMethod, RampStrategy, ReportFormat
from .target import TargetSpec


@dataclass
class TestConfig:
    """Complete test configuration aggregating all settings."""

    target: TargetSpec = field(default_factory=lambda: TargetSpec(url=""))

    # Load settings
    concurrency: int = 10
    rate_limit: int = 0  # 0 = unlimited
    duration: timedelta | None = None
    total_requests: int | None = None
    ramp_up: timedelta | None = None
    ramp_down: timedelta | None = None
    ramp_strategy: RampStrategy = RampStrategy.LINEAR

    # Request settings
    timeout: timedelta = field(default_factory=lambda: timedelta(seconds=30))
    connect_timeout: timedelta = field(default_factory=lambda: timedelta(seconds=10))
    keep_alive: bool = True
    verify_ssl: bool = True
    follow_redirects: bool = False
    max_retries: int = 0
    retry_delay: timedelta = field(default_factory=lambda: timedelta(seconds=1))
    proxy: str | None = None
    resolve: dict[str, str] = field(default_factory=dict)

    # Output settings
    output_dir: Path | None = None
    output_formats: list[ReportFormat] = field(default_factory=lambda: [ReportFormat.TEXT])
    live_refresh_ms: int = 200
    no_live: bool = False
    sample_rate: int = 1
    no_summary: bool = False
    save_responses: bool = False
    limit_response_size: int = 1_048_576  # 1 MB

    # Meta
    tags: list[str] = field(default_factory=list)
    seed: int | None = None
    plugin_dirs: list[Path] = field(default_factory=list)
    plugins_config: dict[str, dict] = field(default_factory=dict)
    extra: dict[str, object] = field(default_factory=dict)

    def __post_init__(self):
        if not self.target.url:
            raise ValueError("Target URL is required")
        if self.concurrency < 1:
            raise ValueError(f"Concurrency must be >= 1, got {self.concurrency}")
        if self.duration is not None and self.total_requests is not None:
            raise ValueError("Specify either --duration or --requests, not both")
        if self.duration is None and self.total_requests is None:
            self.duration = timedelta(seconds=30)
