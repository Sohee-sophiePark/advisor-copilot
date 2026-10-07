"""Book tools: read-only views across every household in the advisor's book (not client-bound)."""

from collections import Counter
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from advisor_copilot import book as views
from advisor_copilot.data_access import list_clients, load_fixtures
from advisor_copilot.models import ASSET_CLASSES, ToolResult, Unit
from advisor_copilot.tools import common as c

Limit = Annotated[int, Field(ge=1, le=20, description="Maximum households to return")]
Target = Annotated[
    str, Field(description="An asset class (e.g. CA_EQUITY) or a ticker from <book_scope>")
]
Row = tuple[str, list[tuple[str, float, Unit, str]], dict]  # client id, metrics, extra data


class AttentionArgs(BaseModel):
    level: Literal["critical", "warning", "kyc", "review", "all"] = "all"
    limit: Limit = 10


class SegmentArgs(BaseModel):
    group_by: Literal["life_stage", "aum_tier", "risk_profile"]


class RiskArgs(BaseModel):
    kind: Literal["volatility", "stress", "concentration", "drift"]
    limit: Limit = 10


class ExposureArgs(BaseModel):
    target: Target
    limit: Limit = 10


class ImpactArgs(BaseModel):
    target: Target
    move_pct: float = Field(ge=-50, le=50, description="Hypothetical move in percent, e.g. -10")
    limit: Limit = 10


class TaxArgs(BaseModel):
    kind: Literal["us_in_tfsa", "unused_tfsa_room", "interest_non_reg"]
    limit: Limit = 10


class GoalArgs(BaseModel):
    limit: Limit = 10


def _result(
    tool: str, name: str, rows: list[Row], limit: int, totals: list[tuple] = ()
) -> ToolResult:
    """Top `limit` rows as `book.<client_id>.<metric>.<unit>`; totals as `book.<name>.<..>`."""
    totals = [
        ("matches", len(rows), "count", "Households that match"),
        ("shown", min(len(rows), limit), "count", "Households listed"),
        *totals,
    ]
    metrics = [c.metric(f"book.{name}.{k}.{u}", v, u, label, tool) for k, v, u, label in totals]
    for cid, ms, _ in rows[:limit]:
        metrics += [c.metric(f"book.{cid}.{k}.{u}", v, u, label, tool) for k, v, u, label in ms]
    households = [{"client_id": cid, **data} for cid, _, data in rows[:limit]]
    return c.tool_result(tool, metrics, data={"households": households})


def _flags(cid: str, prefix: str) -> list[str]:
    return [f.flag_id for f in views._tools(cid)[1] if f.flag_id.startswith(prefix)]


REASON = {  # flag prefix: reason kind; KYC and review items use their level as the kind
    "FLAG-SUIT": "risk_limit",
    "FLAG-CONC": "concentration",
    "FLAG-DRIFT": "drift",
    "FLAG-L": "tax",
    "FLAG-GOAL": "goal",
}


def _reason(item: dict) -> str:
    fid = item.get("flag_id", "")
    return next((k for p, k in REASON.items() if fid.startswith(p)), item["level"])


def book_attention(_: str, args: AttentionArgs) -> ToolResult:
    """Matching households plus, per reason kind, how many of them have it (the whole group)."""
    match = lambda i: args.level == "all" or i["level"] == args.level  # noqa: E731
    hs = [h for h in views.book()["households"] if any(match(i) for i in h["attention"])]
    rows = [
        (
            h["client_id"],
            [("total", h["total_cad"], "cad", "Household assets")],
            {"level": h["top_level"], "reasons": [i["text"] for i in h["attention"]]},
        )
        for h in hs
    ]
    kinds = Counter(k for h in hs for k in {_reason(i) for i in h["attention"] if match(i)})
    by_kind = [
        (k, n, "count", f"Matching households with a {k.replace('_', ' ')} item")
        for k, n in sorted(kinds.items())
    ]
    return _result("book_attention", f"attention_{args.level}", rows, args.limit, by_kind)


def book_segments(_: str, args: SegmentArgs) -> ToolResult:
    tool, groups = "book_segments", {}
    for h in views.book()["households"]:
        groups.setdefault(h[args.group_by] or "none", []).append(h)
    metrics = []
    for g, hs in groups.items():
        metrics += [
            c.metric(f"book.seg_{g}.households.count", len(hs), "count", f"{g} households", tool),
            c.metric(
                f"book.seg_{g}.assets.cad", sum(h["total_cad"] for h in hs), "cad", "Assets", tool
            ),
            c.metric(
                f"book.seg_{g}.attention.count",
                sum(1 for h in hs if h["top_level"]),
                "count",
                f"{g} households needing attention",
                tool,
            ),
        ]
    return c.tool_result(tool, metrics, data={"group_by": args.group_by, "groups": sorted(groups)})


def book_risk(_: str, args: RiskArgs) -> ToolResult:
    ranked = []
    for cl in list_clients():
        cid, m = cl.client_id, views._tools(cl.client_id)[0]
        conc = {k: v for k, v in m.items() if k.startswith("conc.") and k != c.K_CONC_LIMIT}
        drift = {k: v for k, v in m.items() if k.startswith("drift.")}
        if args.kind == "volatility" and c.K_RISK_BAND in m:
            vol, band = m[c.K_RISK_VOL], m[c.K_RISK_BAND]
            ms = [
                ("vol", vol, "pct", "Portfolio volatility"),
                ("vol_limit", band, "pct", "Volatility limit for the risk profile"),
            ]
            ranked.append((vol - band, (cid, ms, {"breach": bool(_flags(cid, "FLAG-SUIT"))})))
        elif args.kind == "stress":
            pct, cad = m[c.k_stress("equity_bear", "pct")], m[c.k_stress("equity_bear", "cad")]
            ms = [("stress", pct, "pct", "Equity bear loss"), ("stress", cad, "cad", "Bear loss")]
            ranked.append((-pct, (cid, ms, {})))
        elif args.kind == "concentration" and conc:
            k, v = max(conc.items(), key=lambda kv: kv[1])
            ms = [("top_stock", v, "pct", f"{k.split('.')[1]} share of portfolio")]
            ranked.append((v, (cid, ms, {"breach": bool(_flags(cid, "FLAG-CONC"))})))
        elif args.kind == "drift" and drift:
            k, v = max(drift.items(), key=lambda kv: abs(kv[1]))
            label = f"{c.ASSET_LABEL[k.split('.')[1]]} drift from target"
            ms = [("max_drift", v, "pp", label)]
            ranked.append((abs(v), (cid, ms, {"breach": bool(_flags(cid, "FLAG-DRIFT"))})))
    rows = [r for _, r in sorted(ranked, key=lambda x: -x[0])]
    breaches = sum(1 for _, _, d in rows if d.get("breach"))
    total = [("breaches", breaches, "count", "Households over the limit")]
    return _result("book_risk", f"risk_{args.kind}", rows, args.limit, total)


def _exposure(target: str) -> list[tuple[str, float, float]]:
    """(client id, value in CAD, % of the household) for holders of an asset class or ticker."""
    if target not in ASSET_CLASSES and target not in load_fixtures().instruments:
        raise c.ToolArgsError(f"unknown asset class or ticker {target!r}")
    out = []
    for cl in list_clients():
        pos = c.positions(cl)
        v = sum(p.market_value for p in pos if target in (p.ticker, p.instrument.asset_class))
        if v > 0:
            out.append((cl.client_id, v, 100 * v / c.total_value(pos)))
    return sorted(out, key=lambda r: -r[2])


def book_exposure(_: str, args: ExposureArgs) -> ToolResult:
    t, held = args.target, _exposure(args.target)
    rows = [
        (
            cid,
            [
                (f"exposure_{t}", pct, "pct", f"{t} share of household"),
                (f"exposure_{t}", v, "cad", f"{t} held"),
            ],
            {},
        )
        for cid, v, pct in held
    ]
    total = [("total", sum(v for _, v, _ in held), "cad", f"{t} held across the book")]
    return _result("book_exposure", f"exposure_{t}", rows, args.limit, total)


def book_market_impact(_: str, args: ImpactArgs) -> ToolResult:
    t, mv, held = args.target, args.move_pct / 100, _exposure(args.target)
    rows = [
        (
            cid,
            [
                (f"impact_{t}", v * mv, "cad", f"Change in value if {t} moves"),
                (f"impact_{t}", pct * mv, "pct", "Change as share of the household"),
            ],
            {},
        )
        for cid, v, pct in held
    ]
    totals = [
        ("total", sum(v for _, v, _ in held) * mv, "cad", "Change across the book"),
        ("move", args.move_pct, "pct", f"Hypothetical {t} move"),
    ]
    return _result("book_market_impact", f"impact_{t}", rows, args.limit, totals)


TAX = {  # kind: (flag prefix, [(row metric, source metric prefix, label)])
    "us_in_tfsa": ("FLAG-L1", [("us_in_tfsa", "tax.l1.", "US-listed funds in the TFSA")]),
    "unused_tfsa_room": (
        "FLAG-L3",
        [
            ("tfsa_room", c.K_TFSA_ROOM, "Unused TFSA room"),
            ("taxable_interest", c.K_NONREG_INTEREST, "Interest holdings in non-registered"),
        ],
    ),
    "interest_non_reg": (
        "FLAG-L2",
        [("taxable_interest", c.K_NONREG_INTEREST, "Interest holdings in non-registered")],
    ),
}


def book_tax(_: str, args: TaxArgs) -> ToolResult:
    prefix, fields = TAX[args.kind]
    rows = []
    for cl in list_clients():
        if _flags(cl.client_id, prefix):
            m = views._tools(cl.client_id)[0]
            ms = [
                (name, sum(v for k, v in m.items() if k.startswith(src)), "cad", label)
                for name, src, label in fields
            ]
            rows.append((cl.client_id, ms, {}))
    rows.sort(key=lambda r: -r[1][0][1])
    return _result("book_tax", f"tax_{args.kind}", rows, args.limit)


def book_goals(_: str, args: GoalArgs) -> ToolResult:
    rows = []
    for cl in list_clients():
        if ids := _flags(cl.client_id, "FLAG-GOAL-"):
            m = views._tools(cl.client_id)[0]
            need = max(m[c.k_goal(i.removeprefix("FLAG-GOAL-"))] for i in ids)
            ms = [
                ("goal_required", need, "pct", "Return the goal needs"),
                ("model_return", m[c.K_GOAL_MODEL_RETURN], "pct", "Expected return of the profile"),
            ]
            rows.append((cl.client_id, ms, {}))
    return _result("book_goals", "goals", rows, args.limit)
