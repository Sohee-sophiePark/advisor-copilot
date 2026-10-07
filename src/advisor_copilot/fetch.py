"""Laptop-only fetch from free sources into the raw and history layers, under daily request caps."""

import datetime as dt
from collections.abc import Callable, Mapping

import httpx

from advisor_copilot.config import Settings
from advisor_copilot.db import Store

BOC = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent={n}"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_FUNDS = "https://www.sec.gov/files/company_tickers_mf.json"
SEC_DOC = "https://data.sec.gov/{kind}/CIK{cik:010d}.json"
TIINGO = "https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate={start}"
LICENCE = {
    "boc": "Bank of Canada Valet; reuse with attribution (bankofcanada.ca/terms)",
    "sec": "SEC EDGAR; public domain, cite the SEC (sec.gov/privacy)",
    "tiingo": "Tiingo free tier; personal use only, never republish",
}


class CapReached(Exception):
    pass


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
        url = BOC.format(n=self.s.fetch.history_days)
        r = self.get("boc", url)
        self.store.put_raw("boc", url, LICENCE["boc"], r.text)
        rows = [("fx.USDCAD", o["d"], float(o["FXUSDCAD"]["v"])) for o in r.json()["observations"]]
        return f"{self.store.put_history('boc', rows)} new values"

    def sec(self, user_agent: str) -> str:
        h = {"User-Agent": user_agent}
        stocks = {
            v["ticker"]: v["cik_str"] for v in self.get("sec", SEC_TICKERS, h).json().values()
        }
        funds = self.get("sec", SEC_FUNDS, h).json()
        funds = {r[3]: r[0] for r in funds["data"]}
        n = 0
        for t in self.s.fetch.us_tickers:
            kinds = ["submissions", "api/xbrl/companyfacts"] if t in stocks else ["submissions"]
            cik = stocks.get(t) or funds.get(t)
            for kind in kinds if cik else []:
                url = SEC_DOC.format(kind=kind, cik=cik)
                self.store.put_raw("sec", url, LICENCE["sec"], self.get("sec", url, h).text)
                n += 1
        return f"{n} documents"

    def tiingo(self, key: str) -> str:
        start = dt.date.today() - dt.timedelta(days=self.s.fetch.history_days)
        rows = []
        for t in self.s.fetch.us_tickers:
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
    return out
