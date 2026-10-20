"""Volume semantics, grounded chart artifacts, and report rendering regressions."""

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent.chart_tools import annotate_kline, build_chart_payload
from agent.kline import enrich_kline
from agent.tool_guards import execute_tool_calls
from app.components import kline_chart
from db.models import AnalysisChart, Base
from db.repository import create_agent_session


def bars(count=25):
    return [
        {
            "date": (date(2026, 9, 1) + timedelta(days=i)).isoformat(),
            "open": 100 + i,
            "close": 102 + i,
            "low": 98 + i,
            "high": 104 + i,
            "volume": (i + 1) * 100,
        }
        for i in range(count)
    ]


def source_state(batch=False):
    data = enrich_kline(bars(), "US")
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_kline",
                        "id": "source-1",
                        "args": {
                            "ticker": "AAPL,600519" if batch else "AAPL",
                            "market": "US,CN" if batch else "US",
                            "period": "3mo",
                        },
                    }
                ],
            ),
            ToolMessage(
                tool_call_id="source-1",
                name="get_kline",
                content=json.dumps(
                    {"batch": True, "results": {"AAPL": data, "600519": data}} if batch else data,
                ),
            ),
        ]
    }


def test_volume_windows_use_correct_denominators_without_mutation():
    raw = bars()
    enriched = enrich_kline(list(reversed(raw)), "US")
    assert "volume_ma5" not in raw[0]
    assert enriched[3]["volume_ma5"] is None
    assert enriched[4]["volume_ma5"] == 300
    assert enriched[4]["volume_ratio5"] is None
    assert enriched[5]["volume_ratio5"] == 2  # 600 / mean(100..500)
    assert enriched[5]["volume_change_pct"] == 20
    assert enriched[19]["volume_ma20"] == 1050
    assert enriched[9]["volume_ma10"] == 550


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), -1, True])
def test_missing_volume_is_not_zero_or_a_partial_average(bad):
    raw = bars(7)
    raw[2]["volume"] = bad
    result = enrich_kline(raw, "CN")
    assert result[2]["volume"] is None
    assert result[5]["volume_ratio5"] is None
    assert result[6]["volume_ma5"] is None
    assert result[3]["volume_change_pct"] is None
    json.dumps(result, allow_nan=False)


def test_zero_volume_and_nav():
    raw = [{**b, "volume": 0} for b in bars(6)]
    result = enrich_kline(raw, "US")
    assert result[-1]["volume_ma5"] == 0
    assert result[-1]["volume_ratio5"] is None
    assert result[-1]["volume_change_pct"] is None
    nav = enrich_kline([{**b, "series_kind": "nav", "volume": None} for b in bars()], "CN")
    assert nav[-1]["volume_kind"] == "unavailable"
    assert nav[-1]["volume_unit"] is None


def test_single_and_batch_tool_results_remain_compatible(monkeypatch):
    from agent import tools

    adapter = SimpleNamespace(get_kline=lambda *_: bars(6))
    monkeypatch.setattr(tools, "adapter_registry", SimpleNamespace(get=lambda _: adapter))
    single = tools.get_kline.invoke({"ticker": "AAPL", "market": "US"})
    batch = tools.get_kline.invoke({"ticker": "AAPL,600519", "market": "US,CN"})
    assert single[-1]["volume_ratio5"] == 2
    assert batch["results"]["AAPL"] == single
    assert batch["results"]["600519"][-1]["volume_unit"] == "lot"


def test_cn_period_is_daily_lookback_not_candle_frequency(monkeypatch):
    from adapters import cn_market

    called = {}

    def history(**kwargs):
        called.update(kwargs)
        return pd.DataFrame(
            [
                {
                    "日期": b["date"],
                    "开盘": b["open"],
                    "最高": b["high"],
                    "最低": b["low"],
                    "收盘": b["close"],
                    "成交量": b["volume"],
                    "成交额": 10000,
                    "换手率": 1.2,
                }
                for b in bars(100)
            ]
        )

    monkeypatch.setattr(cn_market.ak, "stock_zh_a_hist", history)
    result = cn_market.CNMarketAdapter()._get_stock_kline("600519", "1y")
    assert called["period"] == "daily"
    assert called["start_date"] < called["end_date"]
    assert len(result) == 100  # no old 90-bar truncation
    assert result[0]["turnover_rate"] == 1.2
    assert result[0]["amount"] == 10000


def test_crypto_keeps_last_daily_sample_and_matches_volume_timestamp(monkeypatch):
    from adapters import crypto

    t0 = 1788220800000  # 2026-09-01 UTC
    monkeypatch.setattr(
        crypto.cg,
        "get_coin_market_chart_by_id",
        lambda **_: {
            "prices": [[t0, 100], [t0 + 3600000, 102], [t0 + 86400000, 104]],
            "total_volumes": [[t0 + 3600000, 20], [t0, 10]],
        },
    )
    result = crypto.CryptoAdapter().get_kline("BTC")
    assert len(result) == 2
    assert result[0]["price"] == 102
    assert result[0]["volume"] == 20
    assert result[1]["volume"] is None
    assert result[0]["volume_kind"] == "rolling_24h_turnover"


def test_chart_source_is_exact_and_batch_market_is_resolved():
    payload = build_chart_payload(source_state(True), "source-1", "600519", "Test", [], [])
    assert payload["market"] == "CN"
    assert payload["bars"][-1]["close"] == 126
    latest = build_chart_payload(source_state(), "", "AAPL", "", [], [])
    assert latest["source_tool_call_id"] == "source-1"
    horizontal = build_chart_payload(
        source_state(),
        "",
        "AAPL",
        "",
        [],
        [
            {
                "kind": "support",
                "start_date": "2026-09-01",
                "end_date": "2026-09-02",
                "start_price": 100,
                "text": "historical level",
            }
        ],
    )
    assert horizontal["lines"][0]["end_price"] == 100
    with pytest.raises(ValueError, match="标的"):
        build_chart_payload(source_state(), "source-1", "MSFT", "", [], [])
    with pytest.raises(ValueError, match="source_tool_call_id"):
        build_chart_payload(source_state(), "invented", "AAPL", "", [], [])
    with pytest.raises(ValueError, match="标注日期"):
        build_chart_payload(
            source_state(),
            "source-1",
            "AAPL",
            "",
            [
                {"date": "2027-01-01", "price": 100, "text": "future"},
            ],
            [],
        )
    with pytest.raises(ValueError, match="相同"):
        build_chart_payload(
            source_state(),
            "source-1",
            "AAPL",
            "",
            [],
            [
                {
                    "kind": "support",
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-02",
                    "start_price": 100,
                    "end_price": 110,
                    "text": "invalid level",
                }
            ],
        )


def test_tool_guard_injects_state_and_chart_survives_new_db_session(tmp_path, monkeypatch):
    import agent.chart_tools as chart_tools

    engine = create_engine(f"sqlite:///{tmp_path / 'charts.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(chart_tools, "get_session", lambda: Session(engine))
    monkeypatch.setattr(kline_chart, "get_session", lambda: Session(engine))
    with Session(engine) as db:
        sid = create_agent_session(db, "manual").id
    state = source_state()
    state["session_id"] = sid
    state["messages"].append(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "chart-1",
                    "name": "annotate_kline",
                    "args": {
                        "source_tool_call_id": "source-1",
                        "ticker": "AAPL",
                        "title": "Volume test",
                        "annotations": [
                            {"date": "2026-09-06", "price": 107, "text": "量为前五根均量2倍"}
                        ],
                        "lines": [
                            {
                                "kind": "trend",
                                "start_date": "2026-09-01",
                                "end_date": "2026-09-25",
                                "start_price": 98,
                                "end_price": 122,
                                "text": "低点连线",
                            }
                        ],
                    },
                }
            ],
        )
    )
    assert "state" not in annotate_kline.tool_call_schema.model_json_schema()["properties"]
    output = execute_tool_calls(state, [annotate_kline], timeout=10)
    result = json.loads(output["messages"][0].content)
    assert result["status"] == "saved", result
    payload = kline_chart.load_chart(result["chart_id"])
    with Session(engine) as db:
        assert db.get(AnalysisChart, result["chart_id"]).session_id == sid
    assert payload["bars"] == enrich_kline(bars(), "US")
    figure = kline_chart.build_kline_figure(payload)
    assert [trace.type for trace in figure.data] == [
        "candlestick",
        "bar",
        "scatter",
        "scatter",
        "scatter",
    ]
    assert len(figure.layout.shapes) == 1
    assert len(figure.layout.annotations) == 2
    ui = FakeUI()
    kline_chart.render_report(
        "Before\n\n" + result["markdown"] + "\n\nAfter", key_prefix="test", ui=ui
    )
    assert len(ui.figures) == 1
    assert ui.text == ["Before\n\n", "\n\nAfter"]


class FakeUI:
    def __init__(self):
        self.text, self.captions, self.figures = [], [], []

    def markdown(self, text):
        self.text.append(text)

    def caption(self, text):
        self.captions.append(text)

    def plotly_chart(self, fig, **kwargs):
        self.figures.append(fig)


@pytest.mark.parametrize(
    "ref", ["not-json", '{"chart_id":"../../secret"}', '{"chart_id":"' + "a" * 32 + '"}']
)
def test_invalid_or_missing_chart_preserves_surrounding_report(ref, monkeypatch):
    monkeypatch.setattr(kline_chart, "load_chart", lambda _: None)
    ui = FakeUI()
    kline_chart.render_report(f"Before\n```kline\n{ref}\n```\nAfter", key_prefix="test", ui=ui)
    assert "Before" in ui.text[0] and "After" in ui.text[-1]
    assert len(ui.captions) == 1
    assert ui.figures == []


def test_nav_renders_line_without_fake_candles_or_volume_and_escapes_labels():
    payload = build_chart_payload(
        source_state(),
        "source-1",
        "AAPL",
        "<b>title</b>",
        [
            {"date": "2026-09-01", "price": 100, "text": '<a href="https://example.com">note</a>'},
        ],
        [],
    )
    payload["bars"] = [{**b, "series_kind": "nav", "volume": None} for b in payload["bars"]]
    figure = kline_chart.build_kline_figure(payload)
    assert [trace.type for trace in figure.data] == ["scatter"]
    assert "&lt;b&gt;" in figure.layout.title.text
    assert "&lt;a" in figure.layout.annotations[0].text


def test_telegram_chart_references_become_readable_hints():
    from notifier.telegram import _md_to_telegram_html

    result = _md_to_telegram_html('Before\n```kline\n{"chart_id":"' + "a" * 32 + '"}\n```\nAfter')
    assert "Before" in result and "After" in result
    assert "报告页面" in result
    assert "chart_id" not in result


def test_chart_chinese_labels_are_not_overwritten_by_english_fallback():
    from app.i18n import translate

    assert translate("zh", "chart.ohlc") == "K线"
    assert translate("en", "chart.ohlc") == "Candles"


@pytest.mark.parametrize(
    "locale,up,down",
    [
        ("en", "#34d399", "#f87171"),
        ("zh", "#f87171", "#34d399"),
        ("cn", "#f87171", "#34d399"),
    ],
)
def test_candle_and_volume_colors_follow_page_language(locale, up, down):
    payload = build_chart_payload(source_state(), "", "AAPL", "", [], [])
    # Exercise both directions, including volume bars, on the same saved snapshot.
    payload["bars"][1]["open"], payload["bars"][1]["close"] = 103, 101
    figure = kline_chart.build_kline_figure(payload, locale)
    candle, volume = figure.data[:2]
    assert candle.increasing.line.color == up
    assert candle.decreasing.line.color == down
    assert volume.marker.color[:2] == (up, down)
