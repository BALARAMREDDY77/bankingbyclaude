"""
Retry Policies & Fallback Mechanisms
=======================================
Configurable retry logic for LangGraph nodes.
Supports exponential backoff, jitter, and per-error-type policies.
"""

import asyncio
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RetryStrategy(str, Enum):
    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    LINEAR = "linear"


@dataclass
class RetryPolicy:
    max_retries: int = 3
    delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    jitter: bool = True
    retryable_errors: List[Type[Exception]] = field(default_factory=lambda: [Exception])
    non_retryable_errors: List[Type[Exception]] = field(default_factory=list)

    def get_delay(self, attempt: int) -> float:
        if self.strategy == RetryStrategy.FIXED:
            delay = self.delay_seconds
        elif self.strategy == RetryStrategy.EXPONENTIAL:
            delay = self.delay_seconds * (self.backoff_multiplier ** attempt)
        else:  # LINEAR
            delay = self.delay_seconds * (attempt + 1)

        if self.jitter:
            delay = delay * (0.8 + random.random() * 0.4)

        return min(delay, 60.0)

    def should_retry(self, error: Exception, attempt: int) -> bool:
        if attempt >= self.max_retries:
            return False
        if any(isinstance(error, t) for t in self.non_retryable_errors):
            return False
        return any(isinstance(error, t) for t in self.retryable_errors)


# ── Pre-defined policies ─────────────────────

DEFAULT_POLICY = RetryPolicy(
    max_retries=settings.orchestration.max_retries,
    delay_seconds=settings.orchestration.retry_delay_seconds,
    backoff_multiplier=settings.orchestration.retry_backoff_multiplier,
)

STRICT_POLICY = RetryPolicy(max_retries=1, delay_seconds=0.5)
AGGRESSIVE_POLICY = RetryPolicy(max_retries=5, delay_seconds=0.5, backoff_multiplier=1.5)
NO_RETRY_POLICY = RetryPolicy(max_retries=0)


# ── Retry decorator ──────────────────────────

def with_retry(policy: RetryPolicy = DEFAULT_POLICY):
    """Async retry decorator for LangGraph node functions."""
    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(policy.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_error = exc
                    if not policy.should_retry(exc, attempt):
                        raise
                    delay = policy.get_delay(attempt)
                    logger.warning(
                        "node.retry",
                        func=func.__name__,
                        attempt=attempt + 1,
                        max=policy.max_retries,
                        delay=round(delay, 2),
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)
            raise last_error
        return wrapper
    return decorator


# ── Fallback handler ─────────────────────────

class FallbackHandler:
    """
    Manages fallback strategies when nodes fail.
    Tries primary model first, then fallback model.
    """

    def __init__(self) -> None:
        self.primary = settings.orchestration.default_model
        self.fallback = settings.orchestration.fallback_model

    async def execute_with_fallback(
        self,
        primary_fn: Callable,
        fallback_fn: Optional[Callable] = None,
        state: Optional[Dict[str, Any]] = None,
    ) -> Any:
        try:
            return await primary_fn()
        except Exception as primary_exc:
            logger.warning(
                "fallback.primary_failed",
                error=str(primary_exc),
                has_fallback=fallback_fn is not None,
            )
            if fallback_fn:
                try:
                    result = await fallback_fn()
                    if state is not None:
                        state["fallback_triggered"] = True
                    logger.info("fallback.succeeded")
                    return result
                except Exception as fallback_exc:
                    logger.error("fallback.also_failed", error=str(fallback_exc))
                    raise fallback_exc
            raise primary_exc
