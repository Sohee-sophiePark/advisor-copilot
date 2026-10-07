"""Read-only, cached client data: SQLite when seeded from the current JSON, else the JSON itself."""

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
        "facts": _read(d / "fund_facts.json"),
    }


def official_prices(fx: "Fixtures", store: db.Store, as_of: str) -> None:
    """Laptop only: real CAD prices (latest USD close x USD/CAD); units rescaled so each holding's
    value on `as_of` equals its illustrative value, so later changes are real market moves."""

    def cad(ticker: str, on: str = "9999") -> float | None:
        px, rate = store.latest(f"px.{ticker}.usd", on), store.latest("fx.USDCAD", on)
        return px[1] * rate[1] if px and rate else None

    scale = {}
    for t, i in fx.instruments.items():
        if (now := cad(t)) and (anchor := cad(t, as_of)):
            scale[t], i.price_cad = i.price_cad / anchor, round(now, 4)
    for h in (h for c in fx.clients.values() for a in c.accounts for h in a.holdings):
        h.units = round(h.units * scale.get(h.ticker, 1.0), 4)


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
        official_prices(fx, db.Store(dbp), str(s.rules.as_of))
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
