"""Structured logging for Axon, built on structlog.

Design:
  - `configure_logging()` is called once at process start (CLI entry points).
  - `bind_workflow_context()` / `clear_workflow_context()` attach correlation
    fields (workflow_id, agent, round, task_id) via structlog.contextvars so
    every log call underneath inherits them without threading a logger object
    through every function signature.
  - Every bound log event is also appended as a JSON line to
    artifacts/<workflow_id>/engine/run.log.jsonl, alongside the workflow's
    other artifacts, in addition to the console/stdout renderer.
  - Raw LLM prompts/responses and secrets are never logged — only lengths,
    booleans, and outcomes. See `_redact_sensitive` for defense in depth.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import structlog

from axon.config.settings import settings

# Defense in depth: redact any field whose key looks like it might hold a secret,
# even if a caller accidentally passes one in. Matched on whole "_"-separated
# segments (not raw substrings) so harmless fields like "max_tokens" aren't
# mistaken for "token".
_SENSITIVE_KEY_MARKERS = {"api_key", "apikey", "token", "secret", "password", "authorization"}


def _redact_sensitive(logger: Any, method_name: str, event_dict: dict) -> dict:
    for key in list(event_dict.keys()):
        normalized = "_" + re.sub(r"[^a-z0-9]+", "_", key.lower()) + "_"
        if any(f"_{marker}_" in normalized for marker in _SENSITIVE_KEY_MARKERS):
            event_dict[key] = "***redacted***"
    return event_dict


def _persist_to_workflow_log(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Append this event as a JSON line to the current workflow's log file, if bound."""
    workflow_id = event_dict.get("workflow_id")
    if not workflow_id:
        return event_dict
    try:
        path = Path(settings.artifacts_base_path) / str(workflow_id) / "engine" / "run.log.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event_dict, default=str) + "\n")
    except Exception:
        pass  # Logging must never break the workflow it's observing.
    return event_dict


def configure_logging(log_format: str | None = None, log_level: str | None = None) -> None:
    """Configure structlog for the whole process. Call once, at process start."""
    fmt = (log_format or settings.log_format).lower()
    level_name = (log_level or settings.log_level).upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(format="%(message)s", level=level)

    renderer = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_sensitive,
            _persist_to_workflow_log,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def bind_workflow_context(**kwargs: Any) -> None:
    """Bind correlation fields (e.g. workflow_id, agent, round, task_id) for this context."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_workflow_context() -> None:
    """Clear all bound correlation fields. Always call in a `finally` block."""
    structlog.contextvars.clear_contextvars()


def get_logger(name: str = "") -> Any:
    return structlog.get_logger(name)
