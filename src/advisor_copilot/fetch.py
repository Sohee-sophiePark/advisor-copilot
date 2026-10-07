"""Laptop-only fetch from free sources into the raw and history layers, under daily request caps."""

import csv
import datetime as dt
import io
import json
from collections.abc import Callable, Mapping

import httpx

from advisor_copilot.config import Settings
from advisor_copilot.db import Store

BOC = "https://www.bankofcanada.ca/valet/observations/{series}/json?recent={n}"
BOC_SERIES = {
    "FXUSDCAD": "fx.USDCAD",
    "BD.CDN.2YR.DQ.YLD": "yield.CA2Y",
    "BD.CDN.10YR.DQ.YLD": "yield.CA10Y",
}
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_FUNDS = "https://www.sec.gov/files/company_tickers_mf.json"
SEC_DOC = "https://data.sec.gov/{kind}/CIK{cik:010d}.json"
TIINGO = "https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate={start}"
TREASURY = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
    "&field_tdr_date_value={year}&_format=csv"
)
FRED = (
    "https://api.stlouisfed.org/fred/series/observations?series_id=VIXCLS&file_type=json"
    "&observation_start={start}&api_key={key}"
)
LICENCE = {
    "boc": "Bank of Canada Valet; reuse with attribution (bankofcanada.ca/terms)",
    "sec": "SEC EDGAR; public domain, cite the SEC (sec.gov/privacy)",
    "tiingo": "Tiingo free tier; personal use only, never republish",
    "treasury": "US Treasury; US government work, public domain",
}
BOC_TERMS = {"source": "Bank of Canada", "terms": "https://www.bankofcanada.ca/terms/"}
CURVES = [  # key, label, source block, 2-year series, 10-year series
    (
        "ca_curve",
        "Canada yield curve: 10-year minus 2-year",
        BOC_TERMS,
        "yield.CA2Y",
        "yield.CA10Y",
    ),
    (
        "us_curve",
        "US yield curve: 10-year minus 2-year",
        {
            "source": "US Treasury",
            "terms": "https://home.treasury.gov/treasury-daily-interest-rate-xml-feed",
        },
        "yield.US2Y",
        "yield.US10Y",
    ),
]


FIGURES = [  # key, label, unit, candidate concepts (IFRS and US GAAP); the newest annual value wins
    ("revenue", "Revenue", "cad", ["RevenueFromContractsWithCustomers", "Revenue", "Revenues"]),
    ("profit", "Net profit", "cad", ["ProfitLoss", "NetIncomeLoss"]),
    ("assets", "Total assets", "cad", ["Assets"]),
    ("op_cash", "Cash from operations", "cad", ["CashFlowsFromUsedInOperations"]),
    ("dividends", "Dividends paid", "cad", ["DividendsPaidOrdinaryShares", "PaymentsOfDividends"]),
    ("shares", "Shares outstanding", "count", ["EntityCommonStockSharesOutstanding"]),
]
ANNUAL = ("10-K", "20-F", "40-F")


class CapReached(Exception):
    pass


def sec_facts(ticker: str, sub: dict, facts: dict | None, today: dt.date) -> dict:
    """InstrumentFacts from EDGAR submissions and companyfacts (CAD figures only, latest annual)."""
    by_name = {n: c for tax in (facts or {}).get("facts", {}).values() for n, c in tax.items()}
    figures = []
    for key, label, unit, names in FIGURES:
        vals = [
            v
            for n in names
            for u, vs in by_name.get(n, {}).get("units", {}).items()
            if u in ("CAD", "shares")
            for v in vs
            if v.get("form") in ANNUAL and v.get("fp") == "FY"
        ]
        if vals:
            v = max(vals, key=lambda v: (v["end"], v["filed"]))
            figures.append(
                {
                    "key": key,
                    "label": label,
                    "value": v["val"],
                    "unit": unit,
                    "period": f"FY{v['fy']}",
                }
            )
    r, cik = sub["filings"]["recent"], int(sub["cik"])
    filings: dict[tuple, dict] = {}  # one per form and date (a fund trust files per series)
    for form, date, acc, doc in zip(
        r["form"], r["filingDate"], r["accessionNumber"], r["primaryDocument"], strict=False
    ):
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"
        filings.setdefault((form, date), {"form": form, "date": date, "url": url})
    return {
        "ticker": ticker,
        "entity": sub["name"],
        "description": sub.get("sicDescription") or "",
        "figures": figures,
        "filings": list(filings.values())[:5],
        "facts_source": "SEC EDGAR",
        "facts_as_of": today.isoformat(),
        "facts_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}",
    }


class Fetcher:
    def __init__(self, settings: Settings, store: Store, http: httpx.Client) -> None:
        self.s, self.store, self.http = settings, store, http

    def get(
        self, source: str, url: str, headers: Mapping[str, str] | None = None
    ) -> httpx.Response:
        """One request, counted against today's cap for `source` before it is sent."""
        if self.store.usage_today(f"fetch:{source}") >= self.s.fetch.caps[source]:
            raise CapReached(source)
        self.store.add_usage(f"fetch:{source}", 0, 0)
        r = self.http.get(url, headers=headers or {})
        r.raise_for_status()
        return r

    def boc(self, _: str) -> str:
        url = BOC.format(series=",".join(BOC_SERIES), n=self.s.fetch.history_days)
        r = self.get("boc", url)
        self.store.put_raw("boc", url, LICENCE["boc"], r.text)
        obs = r.json()["observations"]
        rows = [
            (BOC_SERIES[k], o["d"], float(o[k]["v"])) for o in obs for k in BOC_SERIES if k in o
        ]
        return f"{self.store.put_history('boc', rows)} new values"

    def treasury(self, _: str) -> str:
        url = TREASURY.format(year=dt.date.today().year)
        r = self.get("treasury", url)
        self.store.put_raw("treasury", url, LICENCE["treasury"], r.text)
        rows = []
        for c in csv.DictReader(io.StringIO(r.text)):
            d = dt.datetime.strptime(c["Date"], "%m/%d/%Y").date().isoformat()
            rows += [("yield.US2Y", d, float(c["2 Yr"])), ("yield.US10Y", d, float(c["10 Yr"]))]
        return f"{self.store.put_history('treasury', rows)} new values"

    def sec(self, user_agent: str) -> str:
        h = {"User-Agent": user_agent}
        stocks = {
            v["ticker"]: v["cik_str"] for v in self.get("sec", SEC_TICKERS, h).json().values()
        }
        funds = self.get("sec", SEC_FUNDS, h).json()
        funds = {r[3]: r[0] for r in funds["data"]}
        out = []
        for t in self.s.fetch.us_tickers:
            kinds = ["submissions", "api/xbrl/companyfacts"] if t in stocks else ["submissions"]
            cik = stocks.get(t) or funds.get(t)
            docs = []
            for kind in kinds if cik else []:
                url = SEC_DOC.format(kind=kind, cik=cik)
                docs.append(self.get("sec", url, h).text)
                self.store.put_raw("sec", url, LICENCE["sec"], docs[-1])
            if docs:
                facts = json.loads(docs[1]) if len(docs) > 1 else None
                out.append(sec_facts(t, json.loads(docs[0]), facts, dt.date.today()))
        path = self.s.path("data") / "instrument_facts.json"
        path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
        return f"facts for {len(out)} tickers"

    def tiingo(self, key: str) -> str:
        start = dt.date.today() - dt.timedelta(days=self.s.fetch.history_days)
        rows = []
        for t in [*self.s.fetch.us_tickers, *self.s.fetch.sector_etfs]:
            url = TIINGO.format(ticker=t, start=start)
            r = self.get("tiingo", url, {"Authorization": f"Token {key}"})
            self.store.put_raw("tiingo", url, LICENCE["tiingo"], r.text)
            rows += [(f"px.{t}.usd", p["date"][:10], float(p["close"])) for p in r.json()]
        return f"{self.store.put_history('tiingo', rows)} new values"


def run(
    settings: Settings, store: Store, http: httpx.Client, env: Mapping[str, str]
) -> dict[str, str]:
    """Fetch every source whose credential is set; one failing source never stops the others."""
    if env.get("CI"):
        raise RuntimeError("fetch runs on the laptop only, never in CI")
    f = Fetcher(settings, store, http)
    steps: list[tuple[str, Callable[[str], str], str | None]] = [
        ("boc", f.boc, None),
        ("sec", f.sec, "SEC_USER_AGENT"),
        ("tiingo", f.tiingo, "TIINGO_API_KEY"),
        ("treasury", f.treasury, None),
    ]
    out = {}
    for name, step, var in steps:
        if var and not env.get(var):
            out[name] = f"skipped: {var} not set"
            continue
        try:
            out[name] = step(env.get(var, "") if var else "")
        except CapReached:
            out[name] = "skipped: daily cap reached"
        except httpx.HTTPStatusError as e:
            out[name] = f"failed: HTTP {e.response.status_code}"
        except httpx.HTTPError as e:
            out[name] = f"failed: {type(e).__name__}"
    write_public(settings, store)
    return out


def write_public(s: Settings, store: Store) -> None:
    """Public snapshot (republishable series only): USD/CAD and the 10y-2y curves, from history."""
    since = (dt.date.today() - dt.timedelta(days=s.fetch.history_days)).isoformat()
    fx = store.series("fx.USDCAD", since)
    cards = [
        {
            **BOC_TERMS,
            "key": "fx_usdcad",
            "label": "USD/CAD, daily average (indicative)",
            "unit": "rate",
            "url": "https://www.bankofcanada.ca/rates/exchange/daily-exchange-rates/",
            "history": [{"date": d, "value": v} for d, v in fx],
        }
    ]
    for key, label, src, short, long in CURVES:
        a, b = dict(store.series(short, since)), dict(store.series(long, since))
        hist = [{"date": d, "value": round(b[d] - a[d], 2)} for d in sorted(a.keys() & b.keys())]
        cards.append(
            {
                **src,
                "key": key,
                "label": label,
                "unit": "pp",
                "url": src["terms"],
                "note": "A common stress gauge; below zero the curve is inverted.",
                "history": hist,
            }
        )
    public = [{**c, "as_of": c["history"][-1]["date"]} for c in cards if c["history"]]
    path = s.path("data") / "market_real.json"
    path.write_text(json.dumps(public, indent=1) + "\n", encoding="utf-8")


def vix(s: Settings, store: Store, http: httpx.Client, key: str) -> dict | None:
    """Laptop only, never stored (FRED terms forbid caching): recent VIX closes, Cboe data."""
    if store.usage_today("fetch:fred") >= s.fetch.caps["fred"]:
        return None
    store.add_usage("fetch:fred", 0, 0)
    start = dt.date.today() - dt.timedelta(days=s.fetch.history_days)
    r = http.get(FRED.format(start=start, key=key))
    r.raise_for_status()
    hist = [
        {"date": o["date"], "value": float(o["value"])}
        for o in r.json()["observations"]
        if o["value"] != "."
    ]
    return {
        "key": "vix",
        "label": "VIX, US equity volatility (fear index)",
        "unit": "index",
        "source": "FRED (Cboe data)",
        "url": "https://fred.stlouisfed.org/series/VIXCLS",
        "terms": "https://fred.stlouisfed.org/docs/api/terms_of_use.html",
        "note": "Laptop only; personal use, never stored or published.",
        "history": hist,
        "as_of": hist[-1]["date"] if hist else "",
    }
