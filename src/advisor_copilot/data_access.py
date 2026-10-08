"""Read-only, cached client data: SQLite when seeded from the current JSON, else the JSON itself."""

import csv
import datetime as dt
import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from advisor_copilot import db
from advisor_copilot.config import get_settings
from advisor_copilot.models import (
    AssetClass,
    CapitalMarketAssumptions,
    Client,
    CrmNote,
    Instrument,
    InstrumentFacts,
    MarketSnapshot,
    ModelPortfolios,
    RiskProfile,
)


class Fixtures(BaseModel):
    instruments: dict[str, Instrument]
    clients: dict[str, Client]
    notes: list[CrmNote]
    model_portfolios: ModelPortfolios
    cma: CapitalMarketAssumptions
    market: MarketSnapshot
    facts: dict[str, InstrumentFacts]


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def read_json(d: Path) -> dict:
    """All fixtures as plain data: base files plus the generated book."""
    book = _read(d / "book.json") if (d / "book.json").exists() else {"clients": [], "notes": []}
    return {
        "instruments": _read(d / "instruments.json"),
        "clients": _read(d / "clients.json") + book["clients"],
        "notes": _read(d / "crm_notes.json") + book["notes"],
        "model_portfolios": _read(d / "model_portfolios.json"),
        "cma": _read(d / "capital_market_assumptions.json"),
        "market": _read(d / "market_snapshot.json"),
        "facts": _read(d / "instrument_facts.json"),
    }


def nav_checks(path: Path) -> list[tuple[str, str, float]]:
    """Fund values the advisor copied by hand (ticker,date,nav), for proxy re-anchoring."""
    if not path.exists():
        return []
    return [(r["ticker"], r["date"], float(r["nav"])) for r in csv.DictReader(path.open())]


def proxy_level(store: db.Store, p: dict, on: str, as_of: str) -> float | None:
    """Proxy level on a date: flat 1, an ETF's CAD price, or a duration model on yields."""
    if p["method"] == "flat":
        return 1.0
    fx = store.latest("fx.USDCAD", on)
    if p["method"] == "etf":
        px = store.latest(f"px.{p['proxy']}.usd", on)
        return px[1] * fx[1] if px and fx else None
    ya, yt = store.latest(p["series"], as_of), store.latest(p["series"], on)
    if not (ya and yt):
        return None
    days = (dt.date.fromisoformat(yt[0]) - dt.date.fromisoformat(ya[0])).days
    return 1 - p["duration"] * (yt[1] - ya[1]) / 100 + ya[1] / 100 * days / 365


def official_prices(
    fx: "Fixtures", store: db.Store, as_of: str, proxies: dict, navs: list[tuple[str, str, float]]
) -> None:
    """Laptop only: real CAD prices (latest USD close x USD/CAD), units rescaled so each holding's
    value on `as_of` equals its illustrative value; proxied tickers move by their proxy's return
    (chained from the advisor's latest hand-copied fund value when one exists)."""

    def cad(ticker: str, on: str = "9999") -> float | None:
        px, rate = store.latest(f"px.{ticker}.usd", on), store.latest("fx.USDCAD", on)
        return px[1] * rate[1] if px and rate else None

    scale = {}
    for t, i in fx.instruments.items():
        if (now := cad(t)) and (anchor := cad(t, as_of)):
            scale[t], i.price_cad = i.price_cad / anchor, round(now, 4)
    for h in (h for c in fx.clients.values() for a in c.accounts for h in a.holdings):
        h.units = round(h.units * scale.get(h.ticker, 1.0), 4)
    for t, p in proxies.items():
        level = lambda on, p=p: proxy_level(store, p, on, as_of)  # noqa: E731
        if t not in fx.instruments or not (now := level("9999")) or not (base := level(as_of)):
            continue
        r = now / base
        own = sorted((d, v) for k, d, v in navs if k == t)
        start = [v for d, v in own if d <= as_of]
        if start and own[-1][0] > as_of and (at := level(own[-1][0])):
            r = own[-1][1] / start[-1] * now / at
        fx.instruments[t].price_cad = round(fx.instruments[t].price_cad * r, 4)


@lru_cache(maxsize=4)
def load_fixtures(data_dir: Path | None = None, db_path: Path | None = None) -> Fixtures:
    """Validate client data once. Reads SQLite only if it was seeded from the current JSON."""
    s = get_settings()
    d, dbp = data_dir or s.path("data"), db_path or s.path("db")
    raw = db.load(dbp) if db.stored_hash(dbp) == db.source_hash(d) else read_json(d)
    instruments = TypeAdapter(list[Instrument]).validate_python(raw["instruments"])
    clients = TypeAdapter(list[Client]).validate_python(raw["clients"])
    fx = Fixtures(
        instruments={i.ticker: i for i in instruments},
        clients={c.client_id: c for c in clients},
        notes=TypeAdapter(list[CrmNote]).validate_python(raw["notes"]),
        model_portfolios=ModelPortfolios.model_validate(raw["model_portfolios"]),
        cma=CapitalMarketAssumptions.model_validate(raw["cma"]),
        market=MarketSnapshot.model_validate(raw["market"]),
        facts={
            f.ticker: f for f in TypeAdapter(list[InstrumentFacts]).validate_python(raw["facts"])
        },
    )
    unknown = {
        h.ticker
        for c in fx.clients.values()
        for a in c.accounts
        for h in a.holdings
        if h.ticker not in fx.instruments
    }
    if unknown:
        raise ValueError(f"holdings reference unknown tickers: {sorted(unknown)}")
    if s.data_source == "official":
        from advisor_copilot.fetch import build_snapshot

        store = db.Store(dbp)
        navs = nav_checks(dbp.parent / "nav_checks.csv")
        official_prices(fx, store, str(s.rules.as_of), s.fetch.proxies, navs)
        if snap := build_snapshot(s, store):
            fx.market = MarketSnapshot.model_validate(snap)
    return fx


def list_clients() -> list[Client]:
    return list(load_fixtures().clients.values())


def get_client(client_id: str) -> Client:
    try:
        return load_fixtures().clients[client_id]
    except KeyError:
        raise KeyError(f"unknown client {client_id!r}") from None


def get_notes(client_id: str) -> list[CrmNote]:
    return [n for n in load_fixtures().notes if n.client_id == client_id]


def get_instrument(ticker: str) -> Instrument:
    return load_fixtures().instruments[ticker]


def get_targets(profile: RiskProfile) -> dict[AssetClass, float]:
    return load_fixtures().model_portfolios.targets_pct[profile]


def get_vol_band_max(profile: RiskProfile) -> float:
    return load_fixtures().model_portfolios.vol_band_max_pct[profile]


def get_cma() -> CapitalMarketAssumptions:
    return load_fixtures().cma


def get_market() -> MarketSnapshot:
    return load_fixtures().market
