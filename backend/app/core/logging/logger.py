"""
Structured Logging Infrastructure
===================================
Configures structlog for JSON (production) or pretty console (development)
output. Every log entry includes: timestamp, level, logger name, request_id,
and any bound context variables.

Usage:
    from app.core.logging import get_logger
    logger = get_logger(__name__)
    logger.info("account.created", account_id="acc_123", user_id="usr_456")
"""

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.core.config import settings


# ──────────────────────────────────────────────
# Custom Processors
# ──────────────────────────────────────────────

def add_app_metadata(logger: Any, method: str, event_dict: EventDict) -> EventDict:
    """Inject app name and version into every log entry."""
    event_dict["app"] = settings.app_name
    event_dict["version"] = settings.app_version
    event_dict["env"] = settings.app_env.value
    return event_dict


def drop_color_message_key(logger: Any, method: str, event_dict: EventDict) -> EventDict:
    """Remove uvicorn's color_message to keep logs clean."""
    event_dict.pop("color_message", None)
    return event_dict


# ──────────────────────────────────────────────
# Shared Processors (both JSON & console)
# ──────────────────────────────────────────────

SHARED_PROCESSORS: list[Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.stdlib.PositionalArgumentsFormatter(),
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    add_app_metadata,
    drop_color_message_key,
]


def configure_logging() -> None:
    """
    Initialize structured logging. Call once at application startup.
    Configures both structlog AND the standard library logging to route
    through structlog's pipeline.
    """
    log_level = settings.logging.level.value
    use_json = settings.logging.format.value == "json"

    # --- Final renderer ---
    if use_json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # --- Configure structlog ---
    structlog.configure(
        processors=SHARED_PROCESSORS + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # --- Configure stdlib logging to flow through structlog ---
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=SHARED_PROCESSORS,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Silence noisy third-party loggers
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "alembic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Re-enable uvicorn.access at INFO in development
    if settings.is_development:
        logging.getLogger("uvicorn.access").setLevel(logging.INFO)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Factory for module-level loggers.

    Example:
        logger = get_logger(__name__)
        logger.info("payment.processed", amount=100.0, currency="USD")
    """
    return structlog.get_logger(name)


# ──────────────────────────────────────────────
# Request Context Binding
# ──────────────────────────────────────────────

def bind_request_context(request_id: str, path: str, method: str) -> None:
    """Bind request-scoped variables to structlog's context vars."""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        path=path,
        method=method,
    )


def clear_request_context() -> None:
    """Clear request-scoped context after response."""
    structlog.contextvars.clear_contextvars()
