from dataclasses import dataclass, field
import time


@dataclass
class RequestResult:
    """Metrics collected for a single HTTP request/response cycle."""

    timestamp: float = 0.0
    latency: float = 0.0  # total wall-clock seconds
    connect_time: float = 0.0  # DNS + TCP + TLS
    ttfb: float = 0.0  # time to first byte
    status_code: int | None = None
    response_size: int = 0
    error: str | None = None
    error_detail: str | None = None
    virtual_user_id: int = 0
    request_index: int = 0
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.error is None and self.status_code is not None and self.status_code < 400
