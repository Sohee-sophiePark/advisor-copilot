"""Advisor views computed by code (no LLM): book overview, client detail, market context."""

import datetime as dt
import json
from functools import lru_cache

from advisor_copilot.config import get_settings
from advisor_copilot.data_access import (
    get_client,
    get_market,
    get_notes,
    get_targets,
    list_clients,
    load_fixtures,
)
from advisor_copilot.harness.context import profile_summary
from advisor_copilot.harness.gates import kyc_expired
from advisor_copilot.tools.common import positions
from advisor_copilot.tools.portfolio import allocation

RANK = {"critical": 0, "kyc": 1, "warning": 2, "review": 3}


def aum_tier(total: float) -> str:
    return "Core" if total < 250_000 else "Premier" if total < 1_000_000 else "Private"


@lru_cache(maxsize=256)
def _tools(client_id: str) -> tuple[dict, list]:
    from advisor_copilot.tools.registry import run_all_for_client  # registry imports book tools

    results = run_all_for_client(client_id)
    metrics = {m.key: m.value for r in results for m in r.metrics}
    flags = list({f.flag_id: f for r in results for f in r.flags}.values())
    return metrics, flags


def annual_fee(total: float) -> float:
    """Annual advisory fee on household assets under the tiered schedule (marginal rates)."""
    fee, lower = 0.0, 0.0
    for upper, rate in get_settings().fees.tiers:
        top = total if upper is None else min(total, upper)
        fee += max(top - lower, 0) * rate / 100
        lower = upper if upper is not None else lower
    return fee


def attention(client_id: str) -> list[dict]:
    """Why this household needs the advisor, most urgent first: breaches, KYC, overdue review."""
    c, rules = get_client(client_id), get_settings().rules
    items = [
        {"level": f.severity, "text": f.message, "flag_id": f.flag_id}
        for f in _tools(client_id)[1]
        if f.severity != "info"
    ]
    if c.kyc_missing():
        items.append(
            {
                "level": "kyc",
                "text": "KYC incomplete: " + ", ".join(c.kyc_missing()).replace("_", " "),
            }
        )
    elif kyc_expired(c, rules):
        items.append(
            {"level": "kyc", "text": f"KYC refresh due (last review {c.kyc_last_reviewed})"}
        )
    if c.review_due and c.review_due < rules.as_of:
        items.append({"level": "review", "text": f"Review overdue since {c.review_due}"})
    return sorted(items, key=lambda i: RANK[i["level"]])


def household(client_id: str) -> dict:
    c = get_client(client_id)
    total, _ = allocation(c)
    items = attention(client_id)
    return {
        "client_id": c.client_id,
        "name": c.name,
        "age": c.age,
        "life_stage": c.life_stage,
        "risk_profile": c.risk_profile,
        "total_cad": round(total, 2),
        "aum_tier": aum_tier(total),
        "fee_cad": round(annual_fee(total), 2),
        "review_due": c.review_due,
        "attention": items,
        "top_level": items[0]["level"] if items else None,
    }


def book() -> dict:
    rows = sorted(
        (household(c.client_id) for c in list_clients()),
        key=lambda h: (RANK.get(h["top_level"], 9), -h["total_cad"]),
    )
    count = lambda pred: sum(1 for h in rows if pred(h))  # noqa: E731
    return {
        "as_of": get_settings().rules.as_of,
        "stats": {
            "households": len(rows),
            "aum_cad": round(sum(h["total_cad"] for h in rows), 2),
            "need_attention": count(lambda h: h["top_level"] is not None),
            "critical": count(lambda h: h["top_level"] == "critical"),
            "kyc_due": count(lambda h: any(i["level"] == "kyc" for i in h["attention"])),
            "review_overdue": count(lambda h: any(i["level"] == "review" for i in h["attention"])),
            "revenue_cad": round(sum(h["fee_cad"] for h in rows), 2),
            "revenue_attention_cad": round(sum(h["fee_cad"] for h in rows if h["top_level"]), 2),
        },
        "fee_label": get_settings().fees.label,
        "households": rows,
    }


def client_detail(client_id: str) -> dict:
    c = get_client(client_id)
    metrics, flags = _tools(client_id)
    total, alloc = allocation(c)
    targets = get_targets(c.risk_profile) if c.risk_profile else {}
    accounts: dict[str, dict] = {}
    for p in positions(c):
        a = accounts.setdefault(
            p.account_type, {"type": p.account_type, "value_cad": 0.0, "holdings": []}
        )
        a["value_cad"] += p.market_value
        a["holdings"].append(
            {
                "ticker": p.ticker,
                "name": p.instrument.name,
                "asset_class": p.instrument.asset_class,
                "units": p.units,
                "value_cad": round(p.market_value, 2),
            }
        )
    goals = [
        {
            **g.model_dump(),
            "required_pct": metrics.get(f"goal.{g.goal_id}.required.pct"),
            "model_pct": metrics.get("goal.model_return.pct"),
        }
        for g in c.goals
    ]
    return {
        **household(client_id),
        "profile": profile_summary(c),
        "metrics": metrics,
        "allocation": [
            {"asset_class": ac, "current_pct": round(v, 2), "target_pct": targets.get(ac)}
            for ac, v in alloc.items()
        ],
        "accounts": [{**a, "value_cad": round(a["value_cad"], 2)} for a in accounts.values()],
        "goals": goals,
        "flags": [f.model_dump() for f in flags],
        "notes": [
            n.model_dump(mode="json")
            for n in sorted(get_notes(client_id), key=lambda n: n.date, reverse=True)
        ],
    }


def instrument_view(ticker: str) -> dict:
    """Ticker page: instrument, fund facts with provenance, holders and the book's total."""
    from advisor_copilot.db import Store
    from advisor_copilot.tools.book import _exposure  # tools.book imports this module

    fx, s = load_fixtures(), get_settings()
    px = Store(s.path("db")).latest(f"px.{ticker}.usd") if s.data_source == "official" else None
    holders = _exposure(ticker)
    names = {c.client_id: c.name for c in list_clients()}
    return {
        **fx.instruments[ticker].model_dump(),
        "facts": fx.facts[ticker].model_dump(mode="json") if ticker in fx.facts else None,
        "price_note": f"Tiingo close {px[0]} in CAD (laptop only)"
        if px
        else proxy["label"] + " (laptop only)"
        if (proxy := s.fetch.proxies.get(ticker)) and s.data_source == "official"
        else "Illustrative price",
        "holders": [
            {
                "client_id": cid,
                "name": names[cid],
                "value_cad": round(v, 2),
                "weight_pct": round(p, 2),
            }
            for cid, v, p in holders
        ],
        "total_cad": round(sum(v for _, v, _ in holders), 2),
    }


def market_view() -> dict:
    snap, real = get_market(), get_settings().path("data") / "market_real.json"
    official = get_settings().data_source == "official"
    local = _local(dt.date.today().isoformat()) if official else {"cards": [], "sectors": []}
    weights = {c.client_id: (c.name, allocation(c)[1]) for c in list_clients()}
    indicators = []
    for i in snap.indicators:
        exposed = sorted(
            (
                (sum(a[ac] for ac in i.asset_classes), cid, name)
                for cid, (name, a) in weights.items()
            ),
            reverse=True,
        )[:5]
        indicators.append(
            {
                **i.model_dump(),
                "most_exposed": [
                    {"client_id": cid, "name": name, "weight_pct": round(w, 1)}
                    for w, cid, name in exposed
                ],
            }
        )
    return {
        "as_of": snap.as_of,
        "label": snap.label,
        "months": snap.history_months,
        "indicators": indicators,
        "headlines": [h.model_dump() for h in snap.headlines],
        "instruments": [
            {"ticker": i.ticker, "name": i.name} for i in load_fixtures().instruments.values()
        ],
        "real": (json.loads(real.read_text()) if real.exists() else []) + local["cards"],
        "sectors": local["sectors"],
    }


@lru_cache(maxsize=1)
def _local(day: str) -> dict:
    """Laptop only (DATA_SOURCE=official): US sector ETF moves from history; VIX live from FRED."""
    import os

    import httpx

    from advisor_copilot import fetch
    from advisor_copilot.db import Store

    s = get_settings()
    store, since = (
        Store(s.path("db")),
        str(dt.date.fromisoformat(day) - dt.timedelta(days=s.fetch.history_days)),
    )
    sectors = []
    for t, name in {**s.fetch.index_etfs, **s.fetch.sector_etfs}.items():
        if len(h := store.series(f"px.{t}.usd", since)) > 1:
            change = round(100 * (h[-1][1] / h[0][1] - 1), 1)
            sectors.append(
                {"ticker": t, "sector": name, "change_pct": change, "from": h[0][0], "to": h[-1][0]}
            )
    cards = []
    if key := os.environ.get("FRED_API_KEY"):
        try:
            with httpx.Client(timeout=30) as http:
                cards = [c for c in [fetch.vix(s, store, http, key)] if c and c["history"]]
        except httpx.HTTPError:
            pass  # the Market page still renders without VIX
    return {"cards": cards, "sectors": sorted(sectors, key=lambda x: -x["change_pct"])}
