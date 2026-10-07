"""Market tool: get_market_snapshot."""

from pydantic import BaseModel, Field

from advisor_copilot.data_access import get_market
from advisor_copilot.models import AssetClass, ToolResult
from advisor_copilot.tools import common as c


class MarketArgs(BaseModel):
    asset_classes: list[AssetClass] = Field(
        ...,
        description="Asset classes the client holds; only indicators and headlines tagged "
        "with one of them are returned",
    )


def get_market_snapshot(client_id: str, args: MarketArgs) -> ToolResult:
    snap = get_market()
    tool = "get_market_snapshot"
    wanted = set(args.asset_classes)
    indicators = [i for i in snap.indicators if wanted & set(i.asset_classes)]
    headlines = [h for h in snap.headlines if wanted & set(h.asset_classes)]
    metrics = [c.metric(c.k_mkt(i.key), i.value, i.unit, i.label, tool) for i in indicators]
    data = {
        "as_of": snap.as_of.isoformat(),
        "label": snap.label,
        "headlines": [
            {"id": h.id, "text": h.text, "asset_classes": list(h.asset_classes)} for h in headlines
        ],
    }
    return c.tool_result(tool, metrics, data=data)
