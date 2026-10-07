"""Request/response mapping of the Gemini adapter, without any network call."""

from google.genai import types
from pydantic import BaseModel

from advisor_copilot.llm.base import LLMRequest, Message, ToolCall, ToolDecl
from advisor_copilot.llm.gemini import from_response, to_config, to_content


class Out(BaseModel):
    answer: str


def test_tool_request_maps_to_function_calling_config() -> None:
    decl = ToolDecl(name="t", description="d", parameters={"type": "object", "properties": {}})
    req = LLMRequest(
        model="m",
        system="s",
        messages=[],
        tools=[decl],
        tool_mode="ANY",
        allowed_tools=["t"],
        purpose="p",
    )
    cfg = to_config(req)
    fc = cfg.tool_config.function_calling_config
    assert fc.mode.value == "ANY" and fc.allowed_function_names == ["t"]
    assert cfg.tools[0].function_declarations[0].parameters_json_schema == decl.parameters
    assert cfg.automatic_function_calling.disable is True and cfg.response_schema is None


def test_schema_request_sets_json_mime_type() -> None:
    cfg = to_config(
        LLMRequest(model="m", system="s", messages=[], response_schema=Out, purpose="p")
    )
    assert cfg.response_mime_type == "application/json" and cfg.response_schema is Out
    assert cfg.tools is None


def test_messages_map_roles_and_parts() -> None:
    msgs = [
        Message(role="user", text="hi"),
        Message(role="model", tool_calls=[ToolCall(id="", name="t", args={"a": 1})]),
        Message(role="tool", tool_name="t", tool_result={"ok": True}),
    ]
    c = [to_content(m) for m in msgs]
    assert [x.role for x in c] == ["user", "model", "user"]
    assert c[1].parts[0].function_call.name == "t" and c[1].parts[0].function_call.id is None
    assert c[2].parts[0].function_response.response == {"ok": True}


def test_response_parsing_extracts_text_calls_and_tokens() -> None:
    content = types.Content(
        role="model",
        parts=[
            types.Part.from_text(text='{"answer": "x"}'),
            types.Part.from_function_call(name="t", args={"a": 1}),
        ],
    )
    resp = types.GenerateContentResponse(
        candidates=[types.Candidate(content=content)],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=10, total_token_count=15
        ),
    )
    out = from_response(
        resp, LLMRequest(model="m", system="s", messages=[], response_schema=Out, purpose="p"), 7
    )
    assert out.parsed == {"answer": "x"} and out.tool_calls == [
        ToolCall(id="", name="t", args={"a": 1})
    ]
    assert (out.tokens_in, out.tokens_out, out.latency_ms, out.source) == (10, 5, 7, "live")


def test_empty_response_is_safe() -> None:
    out = from_response(
        types.GenerateContentResponse(),
        LLMRequest(model="m", system="s", messages=[], purpose="p"),
        0,
    )
    assert out.text is None and out.tool_calls == [] and out.parsed is None


def test_thought_signatures_round_trip() -> None:
    part = types.Part(
        function_call=types.FunctionCall(name="t", args={}), thought_signature=b"sig-bytes"
    )
    resp = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[part]))]
    )
    call = from_response(
        resp, LLMRequest(model="m", system="s", messages=[], purpose="p"), 0
    ).tool_calls[0]
    assert call.thought_signature == "c2lnLWJ5dGVz"
    echoed = to_content(Message(role="model", tool_calls=[call]))
    assert echoed.parts[0].thought_signature == b"sig-bytes"


def test_thinking_level_maps_to_thinking_config() -> None:
    cfg = to_config(
        LLMRequest(model="m", system="s", messages=[], thinking_level="LOW", purpose="p")
    )
    assert cfg.thinking_config.thinking_level.value == "LOW"
    assert (
        to_config(LLMRequest(model="m", system="s", messages=[], purpose="p")).thinking_config
        is None
    )
