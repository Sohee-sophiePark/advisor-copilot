"""Token-bucket rate limiter per model, global concurrency cap, and retry with backoff."""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from advisor_copilot.config import RateLimitsCfg, RetryCfg
from advisor_copilot.llm.base import RetryableLLMError

T = TypeVar("T")
Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class TokenBucket:
    """Capacity `rpm`, refilling `rpm/60` tokens per second."""

    def __init__(
        self, rpm: int, clock: Clock = time.monotonic, sleep: Sleep = asyncio.sleep
    ) -> None:
        self.capacity = self.tokens = float(rpm)
        self.rate = rpm / 60.0
        self.clock, self.sleep = clock, sleep
        self.last = clock()

    async def acquire(self) -> float:
        """Block until a token is available; returns seconds waited."""
        waited = 0.0
        while True:
            now = self.clock()
            self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens >= 1:
                self.tokens -= 1
                return waited
            delay = (1 - self.tokens) / self.rate
            await self.sleep(delay)
            waited += delay


class RateLimiter:
    """Per-model buckets, a global semaphore, per-call timeout, and capped exponential backoff."""

    def __init__(
        self,
        limits: RateLimitsCfg,
        retry: RetryCfg,
        timeout_s: float,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
        on_retry: Callable[[int, float, int], None] | None = None,
    ) -> None:
        self.limits, self.retry, self.timeout_s = limits, retry, timeout_s
        self.clock, self.sleep, self.jitter, self.on_retry = clock, sleep, jitter, on_retry
        self.semaphore = asyncio.Semaphore(limits.max_concurrency)
        self.buckets: dict[str, TokenBucket] = {}
        self.retries = 0

    def bucket(self, model: str) -> TokenBucket:
        if model not in self.buckets:
            self.buckets[model] = TokenBucket(self.limits.rpm_for(model), self.clock, self.sleep)
        return self.buckets[model]

    async def call(self, model: str, fn: Callable[[int], Awaitable[T]]) -> T:
        """Run `fn(attempt)`; retries RetryableLLMError and timeouts, never FatalLLMError."""
        for attempt in range(1, self.retry.max_attempts + 1):
            await self.bucket(model).acquire()
            async with self.semaphore:
                try:
                    return await asyncio.wait_for(fn(attempt), self.timeout_s)
                except TimeoutError as e:
                    err = RetryableLLMError(408, detail="per-call timeout")
                    err.__cause__ = e
                except RetryableLLMError as e:
                    err = e
            if (
                attempt == self.retry.max_attempts
                or (err.retry_after_s or 0) > self.retry.max_wait_seconds
            ):
                raise err
            backoff = min(self.retry.cap_seconds, self.retry.base_seconds * 2 ** (attempt - 1))
            wait = max(err.retry_after_s or 0.0, backoff) + self.jitter()
            self.retries += 1
            if self.on_retry:
                self.on_retry(err.status, wait, attempt)
            await self.sleep(wait)
        raise AssertionError("unreachable")
