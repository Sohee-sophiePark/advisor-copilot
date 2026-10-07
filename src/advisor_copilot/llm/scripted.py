"""Deterministic fake client that returns queued responses per purpose."""

from collections import defaultdict, deque

from advisor_copilot.llm.base import LLMRequest, LLMResponse


class ScriptedClient:
    """Queue with `add(purpose, *responses)`; `generate` pops in order and raises queued errors."""

    def __init__(self) -> None:
        self.queues: dict[str, deque[LLMResponse | Exception]] = defaultdict(deque)
        self.requests: list[LLMRequest] = []

    def add(self, purpose: str, *responses: LLMResponse | Exception) -> None:
        self.queues[purpose].extend(responses)

    async def generate(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        if not self.queues[req.purpose]:
            raise AssertionError(f"no scripted response queued for {req.purpose!r}")
        item = self.queues[req.purpose].popleft()
        if isinstance(item, Exception):
            raise item
        return item.model_copy(update={"source": "scripted", "model": req.model})
