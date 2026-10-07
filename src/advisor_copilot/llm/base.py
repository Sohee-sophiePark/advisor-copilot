"""LLMClient protocol and the request, response, and tool-call models shared by adapters."""

from typing import Literal, Protocol

from pydantic import BaseModel


class ToolDecl(BaseModel):
    name: str
    description: str
    parameters: dict


class ToolCall(BaseModel):
    id: str
    name: str
    args: dict
    thought_signature: str | None = None  # base64; Gemini 3 requires it echoed back


class Message(BaseModel):
    role: Literal["user", "model", "tool"]
    text: str | None = None
    tool_calls: list[ToolCall] = []
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_result: dict | None = None
    thought_signature: str | None = None


class LLMRequest(BaseModel):
    model: str
    system: str
    messages: list[Message]
    temperature: float = 0.0
    thinking_level: str | int | None = None
    max_output_tokens: int | None = None
    tools: list[ToolDecl] = []
    tool_mode: Literal["AUTO", "ANY", "NONE"] = "AUTO"
    allowed_tools: list[str] | None = None
    response_schema: type[BaseModel] | None = None
    purpose: str


class LLMResponse(BaseModel):
    text: str | None = None
    tool_calls: list[ToolCall] = []
    parsed: dict | None = None
    thought_signature: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    model: str = ""
    attempt: int = 1
    source: Literal["live", "cassette", "scripted"] = "live"


class LLMClient(Protocol):
    async def generate(self, req: LLMRequest) -> LLMResponse: ...


class RetryableLLMError(Exception):
    def __init__(self, status: int, retry_after_s: float | None = None, detail: str = "") -> None:
        super().__init__(f"{status} {detail}".strip())
        self.status, self.retry_after_s = status, retry_after_s


class FatalLLMError(Exception):
    pass
