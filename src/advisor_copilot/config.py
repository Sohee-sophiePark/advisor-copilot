"""Settings loader. `config/settings.yaml` is the single source of truth; env overrides run_mode."""

import datetime as dt
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_FILE = ROOT / "config" / "settings.yaml"

RunMode = Literal["live", "record", "replay"]


class ModelsCfg(BaseModel):
    router: str
    analyst: str
    synthesizer: str
    evaluator: str


class TemperatureCfg(BaseModel):
    router: float
    analyst: float
    synthesizer: float
    evaluator: float


class MaxOutputCfg(BaseModel):
    router: int
    analyst: int
    synthesizer: int
    evaluator: int


class ThinkingCfg(BaseModel):
    """Gemini 3: level MINIMAL|LOW|MEDIUM|HIGH. Gemini 2.5: integer token budget (0 = off)."""

    router: str | int
    analyst: str | int
    synthesizer: str | int
    evaluator: str | int


class RateLimitsCfg(BaseModel):
    """`max_concurrency` plus one `{rpm: N}` entry per model id, stored as extra keys."""

    model_config = ConfigDict(extra="allow")
    max_concurrency: int = 3

    def rpm_for(self, model_id: str) -> int:
        entry = (self.model_extra or {}).get(model_id)
        if not isinstance(entry, dict) or "rpm" not in entry:
            raise KeyError(f"rate_limits has no rpm entry for model {model_id!r}")
        return int(entry["rpm"])


class RetryCfg(BaseModel):
    max_attempts: int
    base_seconds: float
    cap_seconds: float
    max_wait_seconds: float = (
        120.0  # a longer server-requested wait (e.g. a daily quota) fails fast
    )


class BudgetCfg(BaseModel):
    max_llm_calls: int
    max_total_tokens: int
    max_wall_seconds: int
    per_call_timeout_seconds: int
    daily_call_cap: int
    thread_max_calls: int
    thread_max_tokens: int


class AgentsCfg(BaseModel):
    analyst_mode: Literal["tool_loop", "prefetch"]
    answer_analyst_mode: Literal["tool_loop", "prefetch"]
    max_turns: int
    max_findings: int
    max_market_findings: int
    max_tool_calls: int


class LoopCfg(BaseModel):
    max_revisions: int
    pass_min_score: int
    pass_mean_score: float


class RouterCfg(BaseModel):
    low_confidence_threshold: float
    fast_path_presets: list[str]


class RulesCfg(BaseModel):
    drift_tolerance_pp: float
    drift_critical_multiplier: float
    single_security_max_pct: float
    interest_in_nonreg_min_cad: float
    as_of: dt.date
    kyc_max_age_months: int


class ChatCfg(BaseModel):
    summary_turns: int
    answer_max_words: int


class PricingCfg(BaseModel):
    """`free_tier` plus one `{input, output}` USD-per-million entry per model id (extra keys)."""

    model_config = ConfigDict(extra="allow")
    free_tier: bool = True

    def cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        p = (self.model_extra or {}).get(model)
        if self.free_tier or not isinstance(p, dict):
            return 0.0
        return (tokens_in * p["input"] + tokens_out * p["output"]) / 1_000_000


class InjectionCfg(BaseModel):
    redact: bool


class TraceCfg(BaseModel):
    store_prompts: bool


class PathsCfg(BaseModel):
    data: str
    db: str
    prompts: str
    runs: str
    cassettes: str
    replays: str


class ApiCfg(BaseModel):
    port_min: int
    port_max: int


class RetentionCfg(BaseModel):
    """Days kept before `advisor-copilot cleanup`: raw responses, history values, run folders."""

    raw_days: int
    history_days: int
    runs_days: int


class FeesCfg(BaseModel):
    """Tiered annual advisory fee on household assets: (upper bound or None, % rate), marginal."""

    tiers: list[tuple[float | None, float]]
    label: str


class FetchCfg(BaseModel):
    """Laptop-only fetch: US-listed tickers to price, FX series, daily request caps per source."""

    us_tickers: list[str]
    sector_etfs: dict[str, str] = {}
    index_etfs: dict[str, str] = {}
    proxies: dict[str, dict] = {}
    history_days: int
    caps: dict[str, int]


class Settings(BaseModel):
    run_mode: RunMode
    data_source: Literal["fictional", "official"] = "fictional"
    models: ModelsCfg
    temperature: TemperatureCfg
    max_output_tokens: MaxOutputCfg
    thinking_level: ThinkingCfg
    rate_limits: RateLimitsCfg
    retry: RetryCfg
    budget: BudgetCfg
    agents: AgentsCfg
    loop: LoopCfg
    router: RouterCfg
    rules: RulesCfg
    chat: ChatCfg
    pricing: PricingCfg
    injection: InjectionCfg
    trace: TraceCfg
    paths: PathsCfg
    api: ApiCfg
    fetch: FetchCfg
    fees: FeesCfg
    retention: RetentionCfg

    def path(self, name: str) -> Path:
        """Absolute path for `paths.<name>`, resolved against the repo root."""
        return ROOT / getattr(self.paths, name)


def load_settings(path: Path | None = None, env: dict[str, str] | None = None) -> Settings:
    """Parse the YAML file. Non-empty `RUN_MODE` / `DATA_SOURCE` in `env` (os.environ) win."""
    environ = os.environ if env is None else env
    raw = yaml.safe_load((path or SETTINGS_FILE).read_text(encoding="utf-8"))
    for var, key in (("RUN_MODE", "run_mode"), ("DATA_SOURCE", "data_source")):
        if value := environ.get(var, "").strip():
            raw[key] = value
    return Settings.model_validate(raw)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton; the only cached global state in the package."""
    return load_settings()


def gemini_api_key() -> str:
    """Read `GEMINI_API_KEY` from the environment at call time. Never stored or logged."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set; live and record modes need it")
    return key
