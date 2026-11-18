"""Compact JSON logging shared by the API and worker processes."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": getattr(record, "event", "application.log"),
            "request_id": getattr(record, "request_id", None),
            "submission_id": getattr(record, "submission_id", None),
            "attempt_id": getattr(record, "attempt_id", None),
            "message": record.getMessage(),
        }
        for key in ("status_code", "verdict"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_json_logging(level: str | int = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
