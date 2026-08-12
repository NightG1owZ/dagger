"""Plugin that logs every request/response pair to disk."""

from pathlib import Path
import json
import logging

from ..base import DaggerPlugin

LOGGER = logging.getLogger("dagger")


class RequestRecorderPlugin(DaggerPlugin):
    """Records request/response metadata to disk for debugging and replay."""

    name = "request_recorder"
    version = "0.1.0"
    description = "Logs every request and response to disk"

    def __init__(self):
        self._output_dir: Path | None = None
        self._enabled: bool = False
        self._records: list[dict] = []
        self._max_records: int = 10000

    async def on_configure(self, config: dict) -> None:
        self._enabled = config.get("enabled", True)
        output = config.get("output_dir", "./request_logs")
        self._output_dir = Path(output)
        self._max_records = config.get("max_records", 10000)

    async def post_response(self, result: "RequestResult") -> "RequestResult":
        if not self._enabled:
            return result

        if len(self._records) >= self._max_records:
            return result

        self._records.append({
            "timestamp": result.timestamp,
            "latency": result.latency,
            "status_code": result.status_code,
            "response_size": result.response_size,
            "error": result.error,
            "error_detail": result.error_detail,
            "virtual_user_id": result.virtual_user_id,
            "request_index": result.request_index,
        })
        return result

    async def on_test_end(self, summary: "MetricsSummary") -> None:
        if not self._enabled or not self._output_dir or not self._records:
            return

        self._output_dir.mkdir(parents=True, exist_ok=True)
        output_file = self._output_dir / "request_log.json"
        try:
            output_file.write_text(
                json.dumps(self._records, indent=2),
                encoding="utf-8",
            )
            LOGGER.info("Recorded %d requests to %s", len(self._records), output_file)
        except Exception as e:
            LOGGER.error("Failed to write request log: %s", e)
