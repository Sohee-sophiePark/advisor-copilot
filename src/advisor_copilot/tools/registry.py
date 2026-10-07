"""ToolSpec registry: JSON-schema declarations for the LLM and per-agent allowlists (03 §15)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from advisor_copilot.data_access import get_client
from advisor_copilot.models import Domain, Flag, ToolResult
from advisor_copilot.tools import market, portfolio, risk, tax
from advisor_copilot.tools.common import NoArgs, asset_classes_held

ToolFn = Callable[[str, Any], ToolResult]


class ToolError(Exception):
    """Base for errors the harness turns into structured messages for the model."""


class UnknownToolError(ToolError):
    pass


class ToolArgsError(ToolError):
    pass


def _inline(node: Any, defs: dict[str, Any], in_props: bool = False) -> Any:
    """Resolve `$ref` into `$defs`; drop `title`/`default` annotations (Gemini accepts neither).

    Keys directly under `properties` are field names and are always kept, even one named `title`.
    """
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline(defs[node["$ref"].rsplit("/", 1)[1]], defs)
        drop = () if in_props else ("title", "default", "$defs")
        return {k: _inline(v, defs, k == "properties") for k, v in node.items() if k not in drop}
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    schema = _inline(raw, raw.get("$defs", {}))
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema


def _compact_errors(err: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in err.errors())


@dataclass(frozen=True)
class ToolSpec:
    name: str
    fn: ToolFn
    input_model: type[BaseModel]
    description: str
    agents: tuple[Domain, ...]

    def declaration(self) -> dict[str, Any]:
        """Function declaration for the LLM: name, description, JSON-schema parameters."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": _schema(self.input_model),
        }

    def run(self, client_id: str, args: dict[str, Any] | None = None) -> ToolResult:
        """Validate `args` against the input model, then execute with the bound client id."""
        try:
            parsed = self.input_model.model_validate(args or {})
        except ValidationError as err:
            raise ToolArgsError(_compact_errors(err)) from err
        return self.fn(client_id, parsed)


_SPECS: list[ToolSpec] = [
    ToolSpec(
        "get_positions",
        portfolio.get_positions,
        NoArgs,
        "Returns the client's holdings per account (TFSA, RRSP, RRIF, NON_REG) with market "
        "values in CAD, plus one metric per account type. Use it to see what is held where "
        "before discussing account placement or rebalancing.",
        ("portfolio", "tax"),
    ),
    ToolSpec(
        "compute_allocation",
        portfolio.compute_allocation,
        NoArgs,
        "Returns total portfolio value (CAD), the current allocation % per asset class, and "
        "the model-portfolio target % for the client's risk profile. Call it first for any "
        "allocation question.",
        ("portfolio",),
    ),
    ToolSpec(
        "compute_drift",
        portfolio.compute_drift,
        NoArgs,
        "Returns drift per asset class in percentage points (current minus target) and the "
        "tolerance. Flags FLAG-DRIFT-<ASSET_CLASS> as warning beyond tolerance and critical "
        "beyond twice the tolerance. Use it to decide whether rebalancing is warranted.",
        ("portfolio",),
    ),
    ToolSpec(
        "compute_risk_metrics",
        risk.compute_risk_metrics,
        NoArgs,
        "Returns portfolio volatility %, the maximum volatility band for the client's risk "
        "profile, the model portfolio's volatility, and expected return %. Flags "
        "FLAG-SUIT-VOL (critical) when volatility exceeds the band.",
        ("risk",),
    ),
    ToolSpec(
        "run_stress_test",
        risk.run_stress_test,
        risk.StressArgs,
        "Applies the named stress scenario (equity_bear) to current holdings and returns "
        "the loss in CAD and as % of the portfolio. Use it to express downside in money terms.",
        ("risk",),
    ),
    ToolSpec(
        "check_concentration",
        risk.check_concentration,
        NoArgs,
        "Returns the % of the portfolio held in each single security and the limit. Flags "
        "FLAG-CONC-<TICKER> (critical) when one security exceeds the limit.",
        ("risk",),
    ),
    ToolSpec(
        "check_asset_location",
        tax.check_asset_location,
        NoArgs,
        "Checks tax placement across account types: US-listed foreign-dividend funds held in "
        "a TFSA (L1, warning), interest-income holdings in non-registered accounts (L2, info), "
        "and unused TFSA room while interest holdings sit non-registered (L3, warning). "
        "Values in CAD.",
        ("tax",),
    ),
    ToolSpec(
        "get_contribution_room",
        tax.get_contribution_room,
        NoArgs,
        "Returns unused TFSA and RRSP contribution room in CAD.",
        ("tax",),
    ),
    ToolSpec(
        "get_market_snapshot",
        market.get_market_snapshot,
        market.MarketArgs,
        "Returns fictional market indicators (%) and headlines for the requested asset "
        "classes as of the snapshot date. Use it to explain why allocations drifted. It "
        "does not forecast.",
        ("market",),
    ),
]

TOOLS: dict[str, ToolSpec] = {spec.name: spec for spec in _SPECS}


def get_tool(name: str) -> ToolSpec:
    try:
        return TOOLS[name]
    except KeyError:
        raise UnknownToolError(f"unknown tool {name!r}") from None


def tools_for(agent: Domain) -> list[ToolSpec]:
    return [spec for spec in _SPECS if agent in spec.agents]


def declarations_for(agent: Domain) -> list[dict[str, Any]]:
    return [spec.declaration() for spec in tools_for(agent)]


def run_tool(name: str, client_id: str, args: dict[str, Any] | None = None) -> ToolResult:
    return get_tool(name).run(client_id, args)


def run_all_for_client(client_id: str) -> list[ToolResult]:
    """Every tool with default arguments; no LLM involved. Used by the CLI and the client list."""
    held = asset_classes_held(get_client(client_id))
    out: list[ToolResult] = []
    for spec in _SPECS:
        args = {"asset_classes": held} if spec.input_model is market.MarketArgs else None
        out.append(spec.run(client_id, args))
    return out


def flags_for_client(client_id: str) -> list[Flag]:
    """Union of tool flags for a client, deduplicated by flag id."""
    seen: dict[str, Flag] = {}
    for result in run_all_for_client(client_id):
        for f in result.flags:
            seen.setdefault(f.flag_id, f)
    return list(seen.values())
