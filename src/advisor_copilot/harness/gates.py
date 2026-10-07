"""Deterministic gates: G0 input, G1 KYC, G4 analyst report, G5 output checks (03 §10)."""

import re

from pydantic import ValidationError

from advisor_copilot.config import RulesCfg
from advisor_copilot.data_access import list_clients, load_fixtures
from advisor_copilot.harness.context import SynthContext
from advisor_copilot.harness.injection import detect
from advisor_copilot.models import (
    BOOK,
    SEVERITY_RANK,
    AnalystReport,
    ChatAnswer,
    Client,
    Finding,
    Flag,
    GateResult,
    Recommendation,
    ToolResult,
)

PLACEHOLDER = re.compile(r"\{\{m:([^}]+)\}\}")
HOUSEHOLD = re.compile(r"\{\{h:([^}]+)\}\}")
CLIENT_ID = re.compile(r"\bC\d{3}\b")
NUMBER_WORD = re.compile(  # "one" is left out: it is mostly a pronoun ("no one", "this one")
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|(thir|four|fif|six|seven|eigh|nine)teen"
    r"|(twen|thir|for|fif|six|seven|eigh|nine)ty|hundred|thousand|million|billion|dozen)\b",
    re.IGNORECASE,
)
PREFIX = {
    "portfolio": "PORT",
    "risk": "RISK",
    "tax": "TAX",
    "market": "MKT",
    "scenario": "WHATIF",
    "book": "BOOK",
}
PROHIBITED = re.compile(
    r"guarantee(d)?|risk[- ]free|no risk|can(no|')t lose|sure thing|will definitely", re.IGNORECASE
)
MAX_REQUEST_CHARS = 1000
ACTION_FLAGS = {  # flag families each action type may address (G5.11)
    "rebalance": ("FLAG-DRIFT", "FLAG-SUIT", "FLAG-CONC"),
    "reduce_position": ("FLAG-CONC", "FLAG-SUIT", "FLAG-DRIFT"),
    "relocate_holding": ("FLAG-L1",),
    "use_tfsa_room": ("FLAG-L3", "FLAG-L2"),
    "review_kyc": ("FLAG-GOAL",),
    "no_action": (),
}
SECOND_PERSON = re.compile(r"\byou(r|rs|rself)?\b", re.IGNORECASE)


def input_gate(client_id: str, request_text: str, preset: str | None) -> GateResult:
    """G0: client exists (or the book scope); request non-empty unless a preset; length capped."""
    v = []
    if client_id != BOOK and client_id not in load_fixtures().clients:
        v.append(f"unknown client {client_id!r}")
    if not request_text.strip() and not preset:
        v.append("request is empty and no preset given")
    if len(request_text) > MAX_REQUEST_CHARS:
        v.append(f"request longer than {MAX_REQUEST_CHARS} characters")
    return GateResult(gate="G0", passed=not v, violations=v)


def kyc_expired(client: Client, rules: RulesCfg) -> bool:
    """Last KYC review older than `kyc_max_age_months` before the data snapshot date."""
    last = client.kyc_last_reviewed
    return last is not None and (rules.as_of - last).days > rules.kyc_max_age_months * 365 / 12


def kyc_gate(client: Client, rules: RulesCfg) -> GateResult:
    """G1: risk profile, horizon and objectives on file, and the KYC review not expired."""
    v = [f"missing {m}" for m in client.kyc_missing()]
    if kyc_expired(client, rules):
        age = rules.kyc_max_age_months
        v.append(f"KYC last reviewed {client.kyc_last_reviewed}, over {age} months ago")
    return GateResult(gate="G1", passed=not v, violations=v)


IDENT = re.compile(r"\b[A-Z][A-Z_-]*\d+[A-Z_-]*\b")  # FLAG-L1-USEQ, TAX-2, L3_UNUSED_TFSA_ROOM


def has_raw_digits(text: str) -> bool:
    """True if any digit remains after removing {{m:...}} placeholders and identifier tokens."""
    return bool(re.search(r"\d", IDENT.sub("", PLACEHOLDER.sub("", text))))


def code_finding(flag: Flag, source_tool: str) -> Finding:
    refs = ", ".join(f"{{{{m:{k}}}}}" for k in flag.metric_refs)
    return Finding(
        finding_id=flag.flag_id,
        title=f"{flag.rule} ({flag.flag_id})",
        severity=flag.severity,
        detail=f"Detected by {source_tool}: {flag.rule}. Metrics: {refs}.",
        metric_refs=list(flag.metric_refs),
        flag_refs=[flag.flag_id],
    )


def analyst_gate(
    report: AnalystReport, results: dict[str, ToolResult], max_findings: int
) -> tuple[AnalystReport, list[str]]:
    """G4: validate against this agent's tool output; returns corrected report + violations."""
    metrics = {m.key for r in results.values() for m in r.metrics}
    flags = {f.flag_id: (f, r.tool) for r in results.values() for f in r.flags}
    violations: list[str] = []
    kept: list[Finding] = []
    if len(report.findings) > max_findings:
        violations.append(f"too many findings: {len(report.findings)} > {max_findings}")
    for f in report.findings[:max_findings]:
        bad = [k for k in f.metric_refs if k not in metrics] + [
            k for k in f.flag_refs if k not in flags
        ]
        if bad:
            violations.append(f"{f.title!r}: unknown references {bad}")
        if has_raw_digits(f.title + " " + f.detail):
            violations.append(f"{f.title!r}: digits outside {{{{m:...}}}} placeholders")
        if not bad and not has_raw_digits(f.title + " " + f.detail):
            kept.append(f)
    covered = {fid for f in kept for fid in f.flag_refs}
    uncovered = [fid for fid in flags if fid not in covered]
    if uncovered:
        violations.append(f"flags not covered by any finding: {uncovered}")
    findings = kept + [code_finding(flags[fid][0], flags[fid][1]) for fid in uncovered]
    prefix = PREFIX[report.agent]
    for i, f in enumerate(findings, 1):
        refs = [flags[x][0].severity for x in f.flag_refs]
        f.finding_id = f"{prefix}-{i}"
        f.severity = max(refs, key=SEVERITY_RANK.get, default="info")
    corrected = report.model_copy(update={"findings": findings})
    return corrected, violations


def _texts(d: Recommendation) -> list[str]:
    actions = [t for a in d.actions for t in (a.description, a.rationale)]
    deferred = [x.reason for x in d.deferred]
    return [
        d.headline,
        d.summary,
        *actions,
        *d.risks_and_considerations,
        *deferred,
        *d.client_talking_points,
    ]


def output_gates(raw: dict, ctx: SynthContext) -> tuple[Recommendation | None, GateResult]:
    """G5.1 to G5.10 over a synthesizer draft; returns the parsed draft (None if G5.1 fails)."""
    try:
        d = Recommendation.model_validate(raw)
    except ValidationError as e:
        return None, GateResult(
            gate="G5", passed=False, violations=[f"G5.1 schema: {e.error_count()} errors"]
        )
    v: list[str] = []
    texts = _texts(d)
    joined = "\n".join(texts)
    if any(has_raw_digits(t) for t in texts):
        v.append("G5.2 no_raw_numbers: digits outside {{m:...}} placeholders")
    if missing := sorted({k for k in PLACEHOLDER.findall(joined) if k not in ctx.metrics}):
        v.append(f"G5.3 placeholders_resolve: unknown metric keys {missing}")
    ids = {f.finding_id for f in ctx.findings}
    for a in d.actions:
        if bad := [r for r in a.finding_refs if r not in ids]:
            v.append(f"G5.4 refs_valid: action {a.action_id} references unknown findings {bad}")
        if a.type != "no_action" and not a.finding_refs:
            v.append(f"G5.4 refs_valid: action {a.action_id} has no finding_refs")
    deferred_ok = {x.finding_id for x in d.deferred if len(x.reason.split()) >= 5}
    covered = {r for a in d.actions for r in a.finding_refs} | deferred_ok
    if uncovered := [m for m in ctx.must_address if m not in covered]:
        v.append(f"G5.5 coverage: not actioned or deferred with a reason: {uncovered}")
    for a in d.actions:
        drift = ctx.metrics.get(f"drift.{a.target}.pp")
        if a.direction == "increase" and f"FLAG-CONC-{a.target}" in ctx.flags:
            v.append(f"G5.6 no_contradiction: increase on concentrated {a.target}")
        worsens = (a.direction == "increase" and drift and drift.value > 0) or (
            a.direction == "decrease" and drift and drift.value < 0
        )
        if f"FLAG-DRIFT-{a.target}" in ctx.flags and worsens:
            v.append(f"G5.6 no_contradiction: {a.direction} on {a.target} worsens its drift breach")
    if m := PROHIBITED.search(joined):
        v.append(f"G5.7 prohibited_language: {m.group(0)!r}")
    no_action = [a for a in d.actions if a.type == "no_action"]
    if not ctx.must_address and d.actions and d.actions != no_action[:1]:
        v.append(
            "G5.8 restraint: no critical/warning findings; actions must be empty or one no_action"
        )
    if no_action and len(d.actions) > 1:
        v.append("G5.8 restraint: no_action mixed with other actions")
    limits = [
        (len(d.headline.split()) > 20, "headline over 20 words"),
        (len(d.summary.split()) > 100, "summary over 100 words"),
        (len(d.actions) > 5, "more than 5 actions"),
        (len(d.client_talking_points) > 3, "more than 3 talking points"),
    ]
    v += [f"G5.9 limits: {msg}" for hit, msg in limits if hit]
    if detect(joined):
        v.append("G5.10 no_injection_echo: recommendation text matches an injection pattern")
    finding_flags = {f.finding_id: f.flag_refs for f in ctx.findings}
    for a in d.actions:
        if a.type == "no_action":
            continue
        allowed = ACTION_FLAGS[a.type]
        for r in a.finding_refs:
            refs = finding_flags.get(r, [])
            if refs and not any(f.startswith(allowed) for f in refs):
                v.append(
                    f"G5.11 action_matches_finding: {a.type} cannot address {r} ({', '.join(refs)})"
                )
    advisor_facing = [
        d.headline,
        d.summary,
        *(t for a in d.actions for t in (a.description, a.rationale)),
    ]
    if any(SECOND_PERSON.search(t) for t in advisor_facing):
        v.append(
            "G5.12 advisor_voice: headline, summary and actions speak about the client, not to them"
        )
    return d, GateResult(gate="G5", passed=not v, violations=v)


def answer_gates(
    raw: dict, ctx: SynthContext, max_words: int
) -> tuple[ChatAnswer | None, GateResult]:
    """Chat answers: schema, numbers via placeholders only, keys resolve, language, length."""
    try:
        a = ChatAnswer.model_validate(raw)
    except ValidationError as e:
        return None, GateResult(
            gate="G5", passed=False, violations=[f"G5.1 schema: {e.error_count()} errors"]
        )
    texts = [a.answer, *a.suggested_questions]
    joined = "\n".join(texts)
    v: list[str] = []
    if any(has_raw_digits(t) for t in texts):
        v.append("G5.2 no_raw_numbers: digits outside {{m:...}} placeholders")
    if missing := sorted({k for k in PLACEHOLDER.findall(joined) if k not in ctx.metrics}):
        v.append(f"G5.3 placeholders_resolve: unknown metric keys {missing}")
    if m := PROHIBITED.search(joined):
        v.append(f"G5.7 prohibited_language: {m.group(0)!r}")
    if len(a.answer.split()) > max_words or len(a.suggested_questions) > 3:
        v.append(f"G5.9 limits: answer over {max_words} words or more than 3 suggested questions")
    if detect(joined):
        v.append("G5.10 no_injection_echo: answer text matches an injection pattern")
    if not ctx.client:
        v += known_households(joined, ctx)
    return a, GateResult(gate="G5", passed=not v, violations=v)


def known_households(text: str, ctx: SynthContext) -> list[str]:
    """G5.13 (book answers): households named only as {{h:id}}, each one returned by a tool;
    counts only as placeholders (no number words)."""
    returned = {k.split(".")[1] for k in ctx.metrics if k.startswith("book.")}
    v = []
    if unknown := sorted(set(HOUSEHOLD.findall(text)) - returned):
        v.append(f"G5.13 known_households: households not in the tool results {unknown}")
    bare = PLACEHOLDER.sub("", HOUSEHOLD.sub("", text))
    if CLIENT_ID.search(bare) or any(c.name in bare for c in list_clients()):
        v.append("G5.13 known_households: households must be named only as {{h:<client_id>}}")
    if m := NUMBER_WORD.search(bare):
        v.append(f"G5.13 counts_as_placeholders: number word {m.group(0)!r}; use {{{{m:<key>}}}}")
    return v
