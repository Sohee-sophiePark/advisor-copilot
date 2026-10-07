"""Token bucket with a fake clock; 429 retried with backoff; fatal not retried; timeout retried."""

import asyncio

import pytest

from advisor_copilot.config import RateLimitsCfg, RetryCfg
from advisor_copilot.llm.base import FatalLLMError, RetryableLLMError
from advisor_copilot.llm.limiter import RateLimiter, TokenBucket


class FakeTime:
    def __init__(self) -> None:
        self.now, self.sleeps = 0.0, []

    def clock(self) -> float:
        return self.now

    async def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.now += s


def limiter(ft: FakeTime, attempts: int = 4, timeout_s: float = 5.0) -> RateLimiter:
    limits = RateLimitsCfg.model_validate({"max_concurrency": 2, "m": {"rpm": 6}})
    retry = RetryCfg(max_attempts=attempts, base_seconds=2.0, cap_seconds=30.0)
    return RateLimiter(limits, retry, timeout_s, ft.clock, ft.sleep, jitter=lambda: 0.0)


async def test_bucket_refills_at_rpm_over_60() -> None:
    ft = FakeTime()
    bucket = TokenBucket(rpm=6, clock=ft.clock, sleep=ft.sleep)
    for _ in range(6):
        assert await bucket.acquire() == 0.0
    assert await bucket.acquire() == pytest.approx(10.0)
    assert ft.now == pytest.approx(10.0)


async def test_429_retried_with_backoff_then_succeeds() -> None:
    ft, attempts, seen = FakeTime(), [], []
    lim = limiter(ft)
    lim.on_retry = lambda status, wait, attempt: seen.append((status, attempt))

    async def fn(attempt: int) -> str:
        attempts.append(attempt)
        if attempt < 3:
            raise RetryableLLMError(429, retry_after_s=5.0 if attempt == 1 else None)
        return "ok"

    assert await lim.call("m", fn) == "ok"
    assert attempts == [1, 2, 3] and lim.retries == 2
    assert ft.sleeps == [5.0, 4.0] and seen == [(429, 1), (429, 2)]


async def test_fatal_not_retried() -> None:
    ft, calls = FakeTime(), []

    async def fn(attempt: int) -> str:
        calls.append(attempt)
        raise FatalLLMError("400 bad request")

    with pytest.raises(FatalLLMError):
        await limiter(ft).call("m", fn)
    assert calls == [1] and ft.sleeps == []


async def test_exhausted_attempts_raise_last_error() -> None:
    ft = FakeTime()

    async def fn(attempt: int) -> str:
        raise RetryableLLMError(503)

    with pytest.raises(RetryableLLMError) as exc:
        await limiter(ft, attempts=2).call("m", fn)
    assert exc.value.status == 503 and len(ft.sleeps) == 1


async def test_timeout_is_retryable() -> None:
    ft = FakeTime()

    async def fn(attempt: int) -> str:
        if attempt == 1:
            await asyncio.sleep(1)
        return "late but ok"

    assert await limiter(ft, attempts=2, timeout_s=0.01).call("m", fn) == "late but ok"
    assert ft.sleeps == [2.0]
