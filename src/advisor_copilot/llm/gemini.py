"""Async google-genai adapter implementing LLMClient (verified against google-genai 2.28.0)."""

import base64
import json
import time

from google import genai
from google.genai import errors, types

from advisor_copilot.config import gemini_api_key
from advisor_copilot.llm.base import (
    FatalLLMError,
    LLMRequest,
    LLMResponse,
    Message,
    RetryableLLMError,
    ToolCall,
)

RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}


def _b64(raw: bytes | None) -> str | None:
    return base64.b64encode(raw).decode() if raw else None


def _raw(sig: str | None) -> bytes | None:
    return base64.b64decode(sig) if sig else None


def to_content(m: Message) -> types.Content:
    if m.role == "tool":
        fr = types.FunctionResponse(
            id=m.tool_call_id or None, name=m.tool_name, response=m.tool_result or {}
        )
        return types.Content(role="user", parts=[types.Part(function_response=fr)])
    parts = [types.Part(text=m.text, thought_signature=_raw(m.thought_signature))] if m.text else []
    parts += [
        types.Part(
            function_call=types.FunctionCall(id=c.id or None, name=c.name, args=c.args),
            thought_signature=_raw(c.thought_signature),
        )
        for c in m.tool_calls
    ]
    return types.Content(role=m.role, parts=parts)


def to_config(req: LLMRequest) -> types.GenerateContentConfig:
    cfg = types.GenerateContentConfig(
        system_instruction=req.system,
        temperature=req.temperature,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    if isinstance(req.thinking_level, int):
        cfg.thinking_config = types.ThinkingConfig(thinking_budget=req.thinking_level)
    elif req.thinking_level:
        cfg.thinking_config = types.ThinkingConfig(thinking_level=req.thinking_level)
    if req.response_schema:
        cfg.response_mime_type, cfg.response_schema = "application/json", req.response_schema
    if req.tools:
        decls = [
            types.FunctionDeclaration(
                name=t.name, description=t.description, parameters_json_schema=t.parameters
            )
            for t in req.tools
        ]
        cfg.tools = [types.Tool(function_declarations=decls)]
        cfg.tool_config = types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode=req.tool_mode, allowed_function_names=req.allowed_tools
            )
        )
    return cfg


def from_response(
    resp: types.GenerateContentResponse, req: LLMRequest, latency_ms: int
) -> LLMResponse:
    cand = resp.candidates[0] if resp.candidates else None
    parts = cand.content.parts if cand and cand.content and cand.content.parts else []
    text = "".join(p.text for p in parts if p.text) or None
    calls = [
        ToolCall(
            id=p.function_call.id or "",
            name=p.function_call.name or "",
            args=dict(p.function_call.args or {}),
            thought_signature=_b64(p.thought_signature),
        )
        for p in parts
        if p.function_call
    ]
    text_sig = next(
        (_b64(p.thought_signature) for p in parts if p.text and p.thought_signature), None
    )
    usage = resp.usage_metadata
    tokens_in = (usage.prompt_token_count or 0) if usage else 0
    tokens_out = ((usage.total_token_count or 0) - tokens_in) if usage else 0
    parsed = json.loads(text) if req.response_schema and text else None
    return LLMResponse(
        text=text,
        tool_calls=calls,
        parsed=parsed,
        thought_signature=text_sig,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        model=req.model,
    )


def retry_after(e: errors.APIError) -> float | None:
    details = e.details.get("error", {}).get("details", []) if isinstance(e.details, dict) else []
    delays = [d["retryDelay"] for d in details if isinstance(d, dict) and "retryDelay" in d]
    return float(delays[0].rstrip("s")) if delays else None


class GeminiClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.client = genai.Client(api_key=api_key or gemini_api_key())

    async def generate(self, req: LLMRequest) -> LLMResponse:
        t0 = time.monotonic()
        try:
            resp = await self.client.aio.models.generate_content(
                model=req.model,
                contents=[to_content(m) for m in req.messages],
                config=to_config(req),
            )
        except errors.APIError as e:
            if e.code in RETRYABLE_CODES:
                raise RetryableLLMError(e.code, retry_after(e), e.message) from e
            raise FatalLLMError(f"{e.code} {e.message}") from e
        return from_response(resp, req, int((time.monotonic() - t0) * 1000))

    async def aclose(self) -> None:
        await self.client.aio.aclose()

    async def list_models(self) -> list[str]:
        return [m.name or "" async for m in await self.client.aio.models.list()]
