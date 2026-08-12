from dataclasses import dataclass, field
from .enums import HttpMethod


@dataclass
class TargetSpec:
    """Request-level specification for a single HTTP call."""

    url: str
    method: HttpMethod = HttpMethod.GET
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None
    cookies: dict[str, str] = field(default_factory=dict)
    json_body: object = None
    form_fields: dict[str, str] | None = None
    files: list[tuple[str, str]] | None = None  # (field_name, file_path) pairs

    def __post_init__(self):
        if not self.url:
            raise ValueError("Target URL is required")
