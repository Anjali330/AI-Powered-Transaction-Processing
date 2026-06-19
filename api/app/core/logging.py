"""
core/logging.py

Structured JSON logging setup.
Call setup_logging() once at application startup (main.py).

Every log record is emitted as a single JSON object:
  {"time": "...", "level": "INFO", "logger": "...", "message": "...", "job_id": "..."}

job_id correlation: pass job_id as an extra kwarg to any logger call:
  logger.info("pipeline started", extra={"job_id": job_id})
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    """Formats each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time":    datetime.now(timezone.utc).isoformat(),
            "level":   record.levelname,
            "logger":  record.name,
            "message": record.getMessage(),
        }

        # job_id correlation — attached via extra={"job_id": ...}
        if hasattr(record, "job_id"):
            payload["job_id"] = record.job_id

        # include exception info if present
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload)


def setup_logging(log_level: str = "INFO") -> None:
    """
    Configure the root logger with JSON output to stdout.
    Call once at startup before any log messages are emitted.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any default handlers (uvicorn adds its own on import)
    root.handlers.clear()
    root.addHandler(handler)

    # Keep uvicorn loggers consistent
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "celery", "celery.task"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
