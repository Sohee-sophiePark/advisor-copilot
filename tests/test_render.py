"""Each unit format; signs on pp; unknown key raises; metrics_used lists referenced keys."""

import pytest

from advisor_copilot.models import Metric, Recommendation
from advisor_copilot.render import DISCLOSURE, format_value, render, render_text


@pytest.mark.parametrize(
    ("value", "unit", "out"),
    [
        (30.137, "pct", "30.1%"),
        (8.14, "pp", "+8.1 pp"),
        (-9.6, "pp", "-9.6 pp"),
        (27000, "cad", "$27,000"),
        (-50340, "cad", "-$50,340"),
        (20, "years", "20 years"),
        (0.4219, "ratio", "0.42"),
    ],
)
def test_format_value(value: float, unit: str, out: str) -> None:
    assert format_value(value, unit) == out


def test_render_text_and_unknown_key() -> None:
    m = {"a.b.pct": Metric(key="a.b.pct", value=1.25, unit="pct", label="A", source_tool="t")}
    assert render_text("x {{m:a.b.pct}} y", m) == "x 1.2% y"
    with pytest.raises(KeyError):
        render_text("{{m:nope}}", m)


def test_render_recommendation_fills_every_field() -> None:
    m = {
        "tax.tfsa_room.cad": Metric(
            key="tax.tfsa_room.cad", value=14000, unit="cad", label="TFSA room", source_tool="t"
        )
    }
    draft = Recommendation(
        headline="Use the room",
        summary="Room is {{m:tax.tfsa_room.cad}}.",
        actions=[],
        risks_and_considerations=["Only {{m:tax.tfsa_room.cad}} available."],
        deferred=[],
        client_talking_points=["You have {{m:tax.tfsa_room.cad}} of room."],
    )
    out = render(draft, m)
    assert out.recommendation.summary == "Room is $14,000."
    assert out.recommendation.client_talking_points == ["You have $14,000 of room."]
    assert [x.key for x in out.metrics_used] == [
        "tax.tfsa_room.cad"
    ] and out.disclosure == DISCLOSURE
