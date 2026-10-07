"""Pydantic schemas for domain data, tool outputs, agent I/O, and run artefacts (02 §4)."""

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

AssetClass = Literal["CASH", "CA_BONDS", "CA_EQUITY", "US_EQUITY", "INTL_EQUITY", "REAL_ASSETS"]
RiskBucket = Literal[
    "CASH", "CA_BONDS", "CA_EQUITY", "US_EQUITY", "INTL_EQUITY", "REAL_ASSETS", "SINGLE_STOCK"
]
RiskProfile = Literal["conservative", "balanced", "growth"]
IncomeType = Literal["interest", "eligible_dividend", "foreign_dividend", "other_income"]
AccountType = Literal["TFSA", "RRSP", "RRIF", "NON_REG"]
Severity = Literal["critical", "warning", "info"]
Unit = Literal["pct", "pp", "cad", "years", "ratio", "count"]
Domain = Literal["portfolio", "risk", "tax", "market", "scenario", "book"]  # not in DOMAINS
Route = Literal["full_review", "targeted", "follow_up", "what_if", "out_of_scope", "book_question"]
BOOK = "BOOK"  # scope id used in place of a client id for questions about the whole book
ActionType = Literal[
    "rebalance", "reduce_position", "relocate_holding", "use_tfsa_room", "review_kyc", "no_action"
]
Direction = Literal["increase", "decrease", "move", "none"]
Priority = Literal["high", "medium", "low"]

ASSET_CLASSES: tuple[AssetClass, ...] = (
    "CASH",
    "CA_BONDS",
    "CA_EQUITY",
    "US_EQUITY",
    "INTL_EQUITY",
    "REAL_ASSETS",
)
RISK_BUCKETS: tuple[RiskBucket, ...] = (
    "CASH",
    "CA_BONDS",
    "CA_EQUITY",
    "US_EQUITY",
    "INTL_EQUITY",
    "REAL_ASSETS",
    "SINGLE_STOCK",
)
DOMAINS: tuple[Domain, ...] = ("portfolio", "risk", "tax", "market")
SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "critical": 2}
KYC_REQUIRED_FIELDS: tuple[str, ...] = ("risk_profile", "time_horizon_years", "objectives")


# ---- domain ----
class Instrument(BaseModel):
    ticker: str
    name: str
    asset_class: AssetClass
    risk_bucket: RiskBucket
    price_cad: float
    listing: Literal["CA", "US"]
    income_type: IncomeType
    single_security: bool


class Figure(BaseModel):
    key: str
    label: str
    value: float
    unit: Literal["cad", "count"]
    period: str


class Filing(BaseModel):
    form: str
    date: dt.date
    url: str


class InstrumentFacts(BaseModel):
    """Public facts about a ticker with provenance (`facts_source`, `facts_as_of`, `facts_url`)."""

    ticker: str
    entity: str
    description: str = ""
    figures: list[Figure] = []
    filings: list[Filing] = []
    facts_source: str
    facts_as_of: dt.date
    facts_url: str


class Holding(BaseModel):
    ticker: str
    units: float


class Account(BaseModel):
    account_id: str
    type: AccountType
    holdings: list[Holding]


LifeStage = Literal["accumulation", "pre_retirement", "retirement"]


class Goal(BaseModel):
    goal_id: str
    name: str
    target_cad: float
    target_year: int


class Preferences(BaseModel):
    income_need_cad_month: float = 0
    esg: bool = False


class Client(BaseModel):
    client_id: str
    name: str
    age: int
    province: str
    risk_profile: RiskProfile | None
    time_horizon_years: int | None
    objectives: list[str] | None
    annual_income_cad: float
    liquidity_needs: str | None
    kyc_last_reviewed: dt.date | None
    tfsa_room_cad: float
    rrsp_room_cad: float
    accounts: list[Account]
    life_stage: LifeStage | None = None
    review_due: dt.date | None = None
    last_contact: dt.date | None = None
    goals: list[Goal] = []
    preferences: Preferences = Preferences()

    def kyc_missing(self) -> list[str]:
        """KYC fields that are null; non-empty means gate G1 blocks the run."""
        return [f for f in KYC_REQUIRED_FIELDS if getattr(self, f) is None]


class CrmNote(BaseModel):
    note_id: str
    client_id: str
    date: dt.date
    author: str
    text: str


# ---- reference data ----
class ModelPortfolios(BaseModel):
    as_of: dt.date
    targets_pct: dict[RiskProfile, dict[AssetClass, float]]
    vol_band_max_pct: dict[RiskProfile, float]


class BucketAssumption(BaseModel):
    expected_return_pct: float
    volatility_pct: float


class Correlation(BaseModel):
    a: RiskBucket
    b: RiskBucket
    rho: float


class StressScenario(BaseModel):
    label: str
    shock_pct: dict[RiskBucket, float]


class CapitalMarketAssumptions(BaseModel):
    as_of: dt.date
    buckets: dict[RiskBucket, BucketAssumption]
    correlations: list[Correlation]
    stress_scenarios: dict[str, StressScenario]


class MarketIndicator(BaseModel):
    key: str
    label: str
    value: float
    unit: Unit
    asset_classes: list[AssetClass]
    history: list[float] = []  # month-end values, fictional, ending at `value`


class Headline(BaseModel):
    id: str
    text: str
    asset_classes: list[AssetClass]


class MarketSnapshot(BaseModel):
    as_of: dt.date
    label: str
    history_months: list[str] = []
    indicators: list[MarketIndicator]
    headlines: list[Headline]


# ---- tool outputs ----
class Metric(BaseModel):
    key: str
    value: float
    unit: Unit
    label: str
    source_tool: str


class Flag(BaseModel):
    flag_id: str
    rule: str
    severity: Severity
    metric_refs: list[str]
    message: str


class ToolResult(BaseModel):
    tool: str
    metrics: list[Metric]
    flags: list[Flag]
    data: dict[str, Any] = Field(default_factory=dict)


# ---- agent IO ----
class RouteDecision(BaseModel):
    route: Route
    domains: list[Domain]
    reason: str
    confidence: float


class Finding(BaseModel):
    finding_id: str
    title: str
    severity: Severity
    detail: str
    metric_refs: list[str]
    flag_refs: list[str]


class AnalystReport(BaseModel):
    agent: str
    findings: list[Finding]
    data_gaps: list[str] = Field(default_factory=list)
    status: Literal["ok", "degraded"] = "ok"


class Action(BaseModel):
    action_id: str
    type: ActionType
    target: str
    direction: Direction
    description: str
    rationale: str
    finding_refs: list[str]
    priority: Priority


class Deferral(BaseModel):
    finding_id: str
    reason: str


class Recommendation(BaseModel):
    headline: str
    summary: str
    actions: list[Action]
    risks_and_considerations: list[str]
    deferred: list[Deferral]
    client_talking_points: list[str]


class ChatAnswer(BaseModel):
    answer: str
    suggested_questions: list[str]


class GateResult(BaseModel):
    gate: str
    passed: bool
    violations: list[str]


class EvalIssue(BaseModel):
    criterion: str
    detail: str
    suggested_fix: str


class EvalVerdict(BaseModel):
    verdict: Literal["pass", "revise"]
    checks: dict[str, bool]
    scores: dict[str, int]
    issues: list[EvalIssue]


class RenderedRecommendation(BaseModel):
    recommendation: Recommendation
    disclosure: str
    metrics_used: list[Metric]


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    advisor_note: str = Field("", max_length=1000)
