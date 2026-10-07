"""Bounded tool-use loop with a final-answer tool and code-enforced termination (03 §4)."""

from pydantic import BaseModel, ValidationError

from advisor_copilot.agents.analysts import AnalystSpec
from advisor_copilot.harness.context import (
    AgentContext,
    build_brief,
    compact_result,
    load_prompt,
    render_tool_results,
)
from advisor_copilot.harness.deps import Deps
from advisor_copilot.harness.gates import analyst_gate, code_finding
from advisor_copilot.llm.base import LLMRequest, Message, ToolCall, ToolDecl
from advisor_copilot.models import AnalystReport, Finding, ToolResult
from advisor_copilot.tools import registry
from advisor_copilot.tools.common import asset_classes_held


class SubmitArgs(BaseModel):
    findings: list[Finding]
    data_gaps: list[str] = []


SUBMIT_DECL = ToolDecl(
    name="submit_findings",
    description="Finish your analysis. Submit at most five findings, each citing metric keys from "
    "your tool results and the flag ids it covers. Call this exactly once, as your last action.",
    parameters=registry._schema(SubmitArgs),
)


def _errors(err: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in err.errors())


def default_args(name: str, ctx: AgentContext) -> dict | None:
    return (
        {"asset_classes": asset_classes_held(ctx.client)} if name == "get_market_snapshot" else None
    )


def execute_tool(
    call: ToolCall,
    spec: AnalystSpec,
    ctx: AgentContext,
    results: dict[str, ToolResult],
    deps: Deps,
    n: int,
) -> dict:
    """G3: allowlist, call cap, validated args, client id bound by the harness. Never raises."""
    if call.name not in spec.tools:
        out = {"error": "tool not permitted for this agent"}
    elif n > deps.settings.agents.max_tool_calls:
        out = {"error": "tool call limit reached; call submit_findings now"}
    else:
        try:
            results[call.name] = registry.run_tool(call.name, ctx.client.client_id, call.args)
            out = compact_result(results[call.name])
        except registry.ToolError as e:
            out = {"error": str(e)}
    r = results.get(call.name)
    deps.trace.emit(
        "tool_call",
        spec.name,
        {
            "name": call.name,
            "args": call.args,
            "metrics_count": len(r.metrics) if r else 0,
            "flags": [{"id": f.flag_id, "severity": f.severity} for f in r.flags] if r else [],
            "error": out.get("error"),
        },
    )
    return out


def degraded_report(spec: AnalystSpec, results: dict[str, ToolResult]) -> AnalystReport:
    findings = [code_finding(f, r.tool) for r in results.values() for f in r.flags]
    report = AnalystReport(
        agent=spec.name,
        findings=findings,
        status="degraded",
        data_gaps=["analyst did not submit findings; generated from tool flags"],
    )
    return analyst_gate(report, results, len(findings) or 1)[0].model_copy(
        update={"status": "degraded"}
    )


async def run_agent(
    spec: AnalystSpec, ctx: AgentContext, deps: Deps, results: dict[str, ToolResult] | None = None
) -> AnalystReport:
    s = deps.settings
    results = {} if results is None else results
    deps.trace.emit("agent_started", spec.name, {"mode": spec.mode, "tools": list(spec.tools)})
    messages = [Message(role="user", text=build_brief(spec.name, ctx))]
    tools = [ToolDecl(**registry.get_tool(t).declaration()) for t in spec.tools]
    if spec.mode == "prefetch":
        results.update(
            {
                t: registry.run_tool(t, ctx.client.client_id, default_args(t, ctx))
                for t in spec.tools
            }
        )
        messages[0].text += "\n" + render_tool_results(results)
        tools = []
    calls_made, repaired = 0, False
    for turn in range(1, spec.max_turns + 1):
        final = turn == spec.max_turns
        req = LLMRequest(
            model=s.models.analyst,
            system=load_prompt(spec.prompt, s),
            messages=list(messages),
            temperature=s.temperature.analyst,
            thinking_level=s.thinking_level.analyst,
            max_output_tokens=s.max_output_tokens.analyst,
            tools=([] if final else tools) + [SUBMIT_DECL],
            tool_mode="ANY",
            allowed_tools=["submit_findings"] if final else None,
            purpose=f"analyst:{spec.name}",
        )
        resp = await deps.llm_call(req)
        messages.append(
            Message(
                role="model",
                text=resp.text,
                tool_calls=resp.tool_calls,
                thought_signature=resp.thought_signature,
            )
        )
        submit = next((c for c in resp.tool_calls if c.name == "submit_findings"), None)
        for call in (c for c in resp.tool_calls if c.name != "submit_findings"):
            calls_made += 1
            out = execute_tool(call, spec, ctx, results, deps, calls_made)
            messages.append(
                Message(role="tool", tool_name=call.name, tool_call_id=call.id, tool_result=out)
            )
        if not submit:
            continue
        try:
            args = SubmitArgs.model_validate(submit.args)
        except ValidationError as e:
            messages.append(
                Message(
                    role="tool",
                    tool_name="submit_findings",
                    tool_call_id=submit.id,
                    tool_result={"error": _errors(e)},
                )
            )
            continue
        report, violations = analyst_gate(
            AnalystReport(agent=spec.name, **args.model_dump()), results, spec.max_findings
        )
        if violations and not repaired:
            repaired = True
            messages.append(
                Message(
                    role="tool",
                    tool_name="submit_findings",
                    tool_call_id=submit.id,
                    tool_result={"error": violations},
                )
            )
            continue
        if violations:
            report = report.model_copy(
                update={"status": "degraded", "data_gaps": report.data_gaps + violations}
            )
        deps.trace.emit(
            "agent_finished",
            spec.name,
            {
                "findings_count": len(report.findings),
                "status": report.status,
                "data_gaps": report.data_gaps,
            },
        )
        return report
    report = degraded_report(spec, results)
    deps.trace.emit(
        "agent_finished",
        spec.name,
        {
            "findings_count": len(report.findings),
            "status": report.status,
            "data_gaps": report.data_gaps,
        },
        "warn",
    )
    return report
