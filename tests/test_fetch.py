"""Fetch: history per source, raw kept once, caps, missing keys, CI refusal, official prices."""

import json
from pathlib import Path

import httpx
import pytest

from advisor_copilot import fetch
from advisor_copilot.config import load_settings
from advisor_copilot.data_access import load_fixtures, official_prices
from advisor_copilot.db import Store

BOC = {
    "observations": [
        {"d": "2026-10-06", "FXUSDCAD": {"v": "1.4226"}},
        {"d": "2026-10-07", "FXUSDCAD": {"v": "1.4257"}},
    ]
}
TIINGO = [{"date": "2026-10-06T00:00:00.000Z", "close": 40.0}]
STOCKS = {"0": {"cik_str": 311337, "ticker": "SU", "title": "SUNCOR ENERGY INC"}}
FUNDS = {"fields": ["cik", "seriesId", "classId", "symbol"], "data": [[36405, "S1", "C1", "VTI"]]}
RECENT = {
    "form": ["6-K"],
    "filingDate": ["2026-10-05"],
    "accessionNumber": ["0001-26-1"],
    "primaryDocument": ["a.htm"],
}
SUB = {
    "cik": "311337",
    "name": "SUNCOR ENERGY INC",
    "sicDescription": "Petroleum Refining",
    "filings": {"recent": RECENT},
}


def fy(val: float, year: int) -> dict:
    return {
        "val": val,
        "fy": year,
        "fp": "FY",
        "form": "40-F",
        "end": f"{year}-12-31",
        "filed": f"{year + 1}-02-26",
    }


FACTS = {"facts": {"ifrs-full": {
    "Revenue": {"units": {"CAD": [fy(1, 2017)]}},
    "RevenueFromContractsWithCustomers": {"units": {"CAD": [fy(52_377_000_000, 2025)]}},
}}}  # fmt: skip


def handler(seen: list[httpx.Request]):  # noqa: ANN201
    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        url = str(req.url)
        body = (
            BOC if "bankofcanada" in url
            else STOCKS if url.endswith("company_tickers.json")
            else FUNDS if url.endswith("company_tickers_mf.json")
            else TIINGO if "tiingo" in url
            else FACTS if "companyfacts" in url
            else SUB
        )  # fmt: skip
        return httpx.Response(200, json=body)

    return h


def setup(tmp_path: Path, **caps: int) -> tuple:
    s = load_settings(env={})
    fetch_cfg = s.fetch.model_copy(update={"caps": {**s.fetch.caps, **caps}})
    s = s.model_copy(
        update={"fetch": fetch_cfg, "paths": s.paths.model_copy(update={"data": str(tmp_path)})}
    )
    seen: list[httpx.Request] = []
    return (
        s,
        Store(tmp_path / "t.db"),
        httpx.Client(transport=httpx.MockTransport(handler(seen))),
        seen,
    )


ENV = {"SEC_USER_AGENT": "Test test@example.com", "TIINGO_API_KEY": "k"}


def test_fetch_all_sources_into_layers(tmp_path: Path) -> None:
    s, store, http, seen = setup(tmp_path)
    out = fetch.run(s, store, http, ENV)
    assert out == {"boc": "2 new values", "sec": "facts for 2 tickers", "tiingo": "2 new values"}
    su = json.loads((tmp_path / "instrument_facts.json").read_text())[1]
    assert su["figures"] == [
        {
            "key": "revenue",
            "label": "Revenue",
            "value": 52_377_000_000,
            "unit": "cad",
            "period": "FY2025",
        }
    ]  # the newest annual value across equivalent concepts
    assert su["filings"][0]["url"] == "https://www.sec.gov/Archives/edgar/data/311337/0001261/a.htm"
    assert su["facts_source"] == "SEC EDGAR"
    assert store.latest("fx.USDCAD") == ("2026-10-07", 1.4257)
    assert store.latest("px.SU.usd") == ("2026-10-06", 40.0)
    sec = [r for r in seen if "sec.gov" in str(r.url)]
    assert all(r.headers["User-Agent"] == ENV["SEC_USER_AGENT"] for r in sec)
    assert any("CIK0000311337" in str(r.url) and "companyfacts" in str(r.url) for r in sec)
    assert not any("CIK0000036405" in str(r.url) and "companyfacts" in str(r.url) for r in sec)
    assert all("token" not in str(r.url).lower() for r in seen)  # key travels in a header
    again = fetch.run(s, store, http, ENV)
    assert again["boc"] == again["tiingo"] == "0 new values"  # history never overwritten
    raw = store.conn.execute("SELECT COUNT(*) FROM market_raw").fetchone()[0]
    assert raw == 6  # second run fetched identical responses: stored once


def test_caps_missing_keys_and_ci(tmp_path: Path) -> None:
    s, store, http, seen = setup(tmp_path, tiingo=1)
    out = fetch.run(s, store, http, {"TIINGO_API_KEY": "k"})
    assert out["sec"] == "skipped: SEC_USER_AGENT not set"
    assert out["tiingo"] == "skipped: daily cap reached" and store.usage_today("fetch:tiingo") == 1
    with pytest.raises(RuntimeError):
        fetch.run(s, store, http, {"CI": "true"})


def test_official_prices_keep_value_on_the_data_date(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    store.put_history("boc", [("fx.USDCAD", "2026-09-30", 1.5), ("fx.USDCAD", "2026-10-07", 1.5)])
    store.put_history(
        "tiingo", [("px.SU.usd", "2026-09-30", 40.0), ("px.SU.usd", "2026-10-07", 44.0)]
    )
    fx = load_fixtures()
    fx = fx.model_copy(deep=True)
    su = sum(h.units for a in fx.clients["C002"].accounts for h in a.holdings if h.ticker == "SU")
    official_prices(fx, store, "2026-09-30")
    after = sum(
        h.units for a in fx.clients["C002"].accounts for h in a.holdings if h.ticker == "SU"
    )
    assert fx.instruments["SU"].price_cad == 66.0  # 44 USD x 1.5
    assert after * 60.0 == pytest.approx(su * 18.0, rel=1e-4)  # same value on the data date
    assert fx.instruments["XBB"].price_cad == load_fixtures().instruments["XBB"].price_cad
