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
        {
            "d": "2026-10-06",
            "FXUSDCAD": {"v": "1.4226"},
            "BD.CDN.2YR.DQ.YLD": {"v": "3.23"},
            "BD.CDN.10YR.DQ.YLD": {"v": "3.92"},
        },
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


NS = (
    'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/"'
)
RSS = (
    f"<rdf:RDF {NS}>"
    "<item><title>Bank of Canada maintains the policy rate</title>"
    "<dc:date>2026-09-02T09:47:53+00:00</dc:date></item>"
    "<item><title>Bank of Canada unveils new bank note</title>"
    "<dc:date>2026-09-03T13:20:16+00:00</dc:date></item>"
    "</rdf:RDF>"
)
TREASURY = 'Date,"1 Mo","2 Yr","10 Yr"\n10/06/2026,4.06,4.79,5.27\n'


def handler(seen: list[httpx.Request]):  # noqa: ANN201
    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        url = str(req.url)
        if "treasury.gov" in url:
            return httpx.Response(200, text=TREASURY)
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
    fetch_cfg = s.fetch.model_copy(
        update={
            "caps": {**s.fetch.caps, **caps},
            "history_days": 100_000,
        }  # window independent of today
    )
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
    assert out == {
        "boc": "4 new values",
        "sec": "facts for 2 tickers",
        "tiingo": "16 new values",  # 2 holdings + 11 sector ETFs + 3 index ETFs
        "treasury": "2 new values",
    }
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
    real = json.loads((tmp_path / "market_real.json").read_text())[0]
    assert (real["source"], real["as_of"], len(real["history"])) == (
        "Bank of Canada",
        "2026-10-07",
        2,
    )
    cards = json.loads((tmp_path / "market_real.json").read_text())
    assert [c["key"] for c in cards] == ["fx_usdcad", "ca_curve", "us_curve"]
    assert cards[2]["history"] == [{"date": "2026-10-06", "value": 0.48}]
    curve = cards[1]
    assert (
        curve["history"] == [{"date": "2026-10-06", "value": 0.69}]
        and curve["as_of"] == "2026-10-06"
    )
    assert store.latest("px.SU.usd") == ("2026-10-06", 40.0)
    sec = [r for r in seen if "sec.gov" in str(r.url)]
    assert all(r.headers["User-Agent"] == ENV["SEC_USER_AGENT"] for r in sec)
    assert any("CIK0000311337" in str(r.url) and "companyfacts" in str(r.url) for r in sec)
    assert not any("CIK0000036405" in str(r.url) and "companyfacts" in str(r.url) for r in sec)
    assert all("token" not in str(r.url).lower() for r in seen)  # key travels in a header
    assert store.fetched_hours_ago() < 0.1  # recorded for `fetch --if-stale`
    again = fetch.run(s, store, http, ENV)
    assert again["boc"] == again["tiingo"] == "0 new values"  # history never overwritten
    raw = store.conn.execute("SELECT COUNT(*) FROM market_raw").fetchone()[0]
    assert raw == 23  # boc 2 + sec 3 + tiingo 16 + treasury 2; the second run stored nothing new


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
    official_prices(fx, store, "2026-09-30", {}, [])
    after = sum(
        h.units for a in fx.clients["C002"].accounts for h in a.holdings if h.ticker == "SU"
    )
    assert fx.instruments["SU"].price_cad == 66.0  # 44 USD x 1.5
    assert after * 60.0 == pytest.approx(su * 18.0, rel=1e-4)  # same value on the data date
    assert fx.instruments["XBB"].price_cad == load_fixtures().instruments["XBB"].price_cad


def test_vix_is_never_stored(tmp_path: Path) -> None:
    s, store, _, _ = setup(tmp_path, fred=1)
    obs = {
        "observations": [
            {"date": "2026-10-06", "value": "."},
            {"date": "2026-10-07", "value": "16.2"},
        ]
    }
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=obs)))
    v = fetch.vix(s, store, http, "k")
    assert v["history"] == [{"date": "2026-10-07", "value": 16.2}] and v["as_of"] == "2026-10-07"
    assert store.conn.execute("SELECT COUNT(*) FROM market_raw").fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM market_history").fetchone()[0] == 0
    assert fetch.vix(s, store, http, "k") is None  # daily cap


def test_proxies_move_from_the_anchor_and_chain_hand_copied_values(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    store.put_history("boc", [("fx.USDCAD", "2026-09-30", 1.5), ("fx.USDCAD", "2026-10-07", 1.5)])
    store.put_history(
        "tiingo", [("px.EWC.usd", "2026-09-30", 40.0), ("px.EWC.usd", "2026-10-07", 44.0)]
    )
    store.put_history(
        "boc", [("yield.CA10Y", "2026-09-30", 3.0), ("yield.CA10Y", "2026-10-07", 3.1)]
    )
    proxies = load_settings(env={}).fetch.proxies
    fx = load_fixtures().model_copy(deep=True)
    base = {t: fx.instruments[t].price_cad for t in ("XIC", "XBB", "CSAV", "XRE")}
    official_prices(fx, store, "2026-09-30", proxies, [])
    assert fx.instruments["XIC"].price_cad == pytest.approx(base["XIC"] * 1.1)  # EWC +10% in CAD
    carry = 3.0 / 100 * 7 / 365
    assert fx.instruments["XBB"].price_cad == pytest.approx(
        base["XBB"] * (1 - 7.0 * 0.1 / 100 + carry), rel=1e-4
    )
    assert (
        fx.instruments["CSAV"].price_cad == base["CSAV"]
        and fx.instruments["XRE"].price_cad == base["XRE"]
    )
    fx = load_fixtures().model_copy(deep=True)
    navs = [
        ("XIC", "2026-09-30", 50.0),
        ("XIC", "2026-10-07", 52.0),
    ]  # real fund +4%, proxy said +10%
    official_prices(fx, store, "2026-09-30", proxies, navs)
    assert fx.instruments["XIC"].price_cad == pytest.approx(
        base["XIC"] * 1.04
    )  # re-anchored on the real value


def test_snapshot_from_public_series(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    rows = []
    for y, mth in [(2025, m) for m in range(1, 13)] + [(2026, m) for m in range(1, 10)]:
        d = f"{y}-{mth:02d}-15"
        rows += [("yield.CA10Y", d, 3.0), ("yield.CA2Y", d, 2.5), ("rate.CA_POLICY", d, 2.25),
                 ("fx.USDCAD", d, 1.4), ("bcpi.TOTAL", d, 100.0 + mth + 12 * (y - 2025)),
                 ("bcpi.ENERGY", d, 200.0 if y == 2025 else 220.0)]  # fmt: skip
    rows += [("yield.US10Y", f"2026-{m:02d}-15", 4.5) for m in range(1, 10)]
    store.put_history("test", rows)
    store.put_raw("boc", fetch.BOC_RSS, "", RSS)
    snap = fetch.build_snapshot(load_settings(env={}), store)
    ind = {i["key"]: i for i in snap["indicators"]}
    assert snap["history_months"][-1] == "2026-09" and len(snap["history_months"]) == 9
    assert ind["ca_curve"]["value"] == 0.5 and ind["energy_commodities_12m"]["value"] == 10.0
    assert ind["usd_cad"]["unit"] == "ratio" and ind["us_10y_yield"]["value"] == 4.5
    assert [h["id"] for h in snap["headlines"]] == [
        "BOC-2026-09-02"
    ]  # rate decision kept, bank note dropped
