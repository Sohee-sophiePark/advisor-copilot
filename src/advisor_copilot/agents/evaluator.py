"""Separate LLM evaluator returning an EvalVerdict; code decides pass/revise (03 §8.4, §11)."""

from statistics import mean
from typing import Literal

from pydantic import BaseModel, ValidationError

from advisor_copilot.config import LoopCfg
from advisor_copilot.harness.context import SynthContext, load_prompt, synth_inputs
from advisor_copilot.harness.deps import Deps
from advisor_copilot.llm.base import LLMRequest, Message
from advisor_copilot.models import EvalIssue, EvalVerdict, Recommendation
from advisor_copilot.render import render


class EvalChecks(BaseModel):
    suitability_respected: bool
    critical_addressed: bool
    faithful_to_findings: bool
    client_specific: bool
    untrusted_ignored: bool


class EvalScores(BaseModel):
    clarity_for_advisor: int
    actionability: int
    professional_tone: int


class EvalResponse(BaseModel):
    verdict: Literal["pass", "revise"]
    checks: EvalChecks
    scores: EvalScores
    issues: list[EvalIssue]


def passes(v: EvalVerdict, cfg: LoopCfg) -> bool:
    scores = list(v.scores.values())
    return (
        all(v.checks.values())
        and min(scores) >= cfg.pass_min_score
        and mean(scores) >= cfg.pass_mean_score
    )


async def evaluate(draft: Recommendation, ctx: SynthContext, deps: Deps) -> EvalVerdict:
    s = deps.settings
    rendered = render(draft, ctx.metrics).recommendation
    text = "\n".join(synth_inputs(ctx) + [f"<draft>\n{rendered.model_dump_json()}\n</draft>"])
    req = LLMRequest(
        model=s.models.evaluator,
        system=load_prompt("evaluator.md", s),
        messages=[Message(role="user", text=text)],
        temperature=s.temperature.evaluator,
        thinking_level=s.thinking_level.evaluator,
        max_output_tokens=s.max_output_tokens.evaluator,
        response_schema=EvalResponse,
        purpose="evaluator",
    )
    resp = await deps.llm_call(req)
    try:
        r = EvalResponse.model_validate(resp.parsed or {})
    except ValidationError as e:
        issue = EvalIssue(
            criterion="evaluator",
            detail=f"unparseable verdict: {e.error_count()} errors",
            suggested_fix="revise the draft for clarity and resubmit",
        )
        return EvalVerdict(
            verdict="revise",
            checks={"evaluator_parsed": False},
            scores={"clarity_for_advisor": 1},
            issues=[issue],
        )
    return EvalVerdict(
        verdict=r.verdict,
        checks=r.checks.model_dump(),
        scores=r.scores.model_dump(),
        issues=r.issues,
    )
