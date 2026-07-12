"""Structured JSON logging. Extra context fields (stream_id, channel_id, ...)
are passed via logger.info(..., extra={...}) and land as top-level JSON keys.
Tokens must never be logged; nothing here redacts, callers must not pass them.
"""

import json
import logging
import sys

CONTEXT_FIELDS = ("stream_id", "channel_id", "event_type", "job_type", "source")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for field in CONTEXT_FIELDS:
            value = record.__dict__.get(field)
            if value is not None:
                entry[field] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
