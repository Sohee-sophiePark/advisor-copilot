"""Read-only, cached access to the synthetic fixtures in data/synthetic/."""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from advisor_copilot.config import get_settings
from advisor_copilot.models import (
    AssetClass,
    CapitalMarketAssumptions,
    Client,
    CrmNote,
    Instrument,
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


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def load_fixtures(data_dir: Path | None = None) -> Fixtures:
    """Load and validate every fixture once. Raises ValueError on dangling ticker references."""
    d = data_dir or get_settings().path("data")
    instruments = TypeAdapter(list[Instrument]).validate_python(_read(d / "instruments.json"))
    clients = TypeAdapter(list[Client]).validate_python(_read(d / "clients.json"))
    notes = TypeAdapter(list[CrmNote]).validate_python(_read(d / "crm_notes.json"))
    fx = Fixtures(
        instruments={i.ticker: i for i in instruments},
        clients={c.client_id: c for c in clients},
        notes=notes,
        model_portfolios=ModelPortfolios.model_validate(_read(d / "model_portfolios.json")),
        cma=CapitalMarketAssumptions.model_validate(_read(d / "capital_market_assumptions.json")),
        market=MarketSnapshot.model_validate(_read(d / "market_snapshot.json")),
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
