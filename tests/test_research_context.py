import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.context import compact_history, model_messages, summarize_series
from agent.tool_cache import cached_result
from agent.tool_guards import execute_tool_calls


def rows(count=90):
    from datetime import date, timedelta

    return [
        {
            "date": str(date(2026, 7, 1) + timedelta(days=i)),
            "open": 100 + i,
            "high": 102 + i,
            "low": 99 + i,
            "close": 101 + i,
            "volume": 1000 + i,
            "series_kind": "ohlc",
            "volume_ratio5": 1.0,
            "volume_ma5": 1000,
            "volume_ma10": 1000,
            "volume_ma20": 1000,
        }
        for i in range(count)
    ]


def test_projection_reduces_context_without_changing_saved_evidence():
    raw = json.dumps(rows())
    source = ToolMessage(name="get_kline", tool_call_id="kline", content=raw)
    view = model_messages([source])[0]
    assert source.content == raw
    assert view.tool_call_id == source.tool_call_id
    data = json.loads(view.content)
    assert data["total_bars"] == 90
    assert data["latest"]["close"] == 190
    assert data["close_ma"]["5"] == 188
    assert len(data["recent_bars"]) == 20
    assert len(view.content) < len(raw) * 0.3


def test_nav_projection_has_no_candle_or_volume_capability():
    data = summarize_series([{**r, "series_kind": "nav", "volume": None} for r in rows()])
    assert data["capabilities"] == {"intraday_patterns": False, "volume_analysis": False}
    assert data["columns"] == ["date", "close"]
    assert data["window_extremes"] == {}


def test_full_detail_is_available_for_older_specific_dates():
    call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "full",
                "name": "get_kline",
                "args": {"ticker": "QQQ", "market": "US", "detail": "full"},
            }
        ],
    )
    message = ToolMessage(content=json.dumps(rows()), name="get_kline", tool_call_id="full")
    assert model_messages([call, message])[-1].content == message.content


def test_history_preserves_pending_and_old_user_constraints():
    history = [
        {"id": i, "ticker": "QQQ", "status": "acted", "user_feedback": None} for i in range(10)
    ]
    history[-1]["user_feedback"] = {"reason": "只买不卖"}
    history[-2]["status"] = "pending"
    view = compact_history(history)
    assert [r["id"] for r in view["results"]] == [0, 1, 8]
    assert view["user_feedback"][0]["user_feedback"]["reason"] == "只买不卖"


def batch_price_history(now=100):
    return [
        HumanMessage(content="analysis"),
        AIMessage(
            content="",
            tool_calls=[
                {"id": "batch", "name": "get_price", "args": {"ticker": "QQQ,DUOL", "market": "US"}}
            ],
        ),
        ToolMessage(
            name="get_price",
            tool_call_id="batch",
            additional_kwargs={"executed_at": now},
            content=json.dumps(
                {"batch": True, "results": {"QQQ": {"price": 100}, "DUOL": {"price": 50}}}
            ),
        ),
    ]


def test_cache_reuses_batch_subset_but_not_expired_or_different_market():
    history = batch_price_history()
    args = {"ticker": "QQQ", "market": "US"}
    assert json.loads(cached_result(history, "get_price", args, now=120)["content"]) == {
        "price": 100
    }
    assert cached_result(history, "get_price", args, now=161) is None
    assert cached_result(history, "get_price", {**args, "market": "HK"}, now=120) is None
    assert (
        cached_result(history + [HumanMessage(content="refresh")], "get_price", args, now=120)
        is None
    )


def test_failed_quotes_are_not_cached():
    history = batch_price_history()
    history[-1].content = json.dumps({"batch": True, "results": {"QQQ": {"error": "timeout"}}})
    assert cached_result(history, "get_price", {"ticker": "QQQ", "market": "US"}, now=120) is None


def test_tool_execution_returns_cached_quote_without_network(monkeypatch):
    import agent.tool_guards as guards
    import agent.tools as tools

    history = batch_price_history(now=100)
    history += [
        AIMessage(
            content="",
            tool_calls=[
                {"id": "single", "name": "get_price", "args": {"ticker": "QQQ", "market": "US"}}
            ],
        )
    ]
    monkeypatch.setattr("agent.tool_cache.time.time", lambda: 120)
    monkeypatch.setattr(
        guards,
        "invoke_tool_with_timeout",
        lambda *a: (_ for _ in ()).throw(AssertionError("network")),
    )
    out = execute_tool_calls({"messages": history}, [tools.get_price])
    message = out["messages"][0]
    assert json.loads(message.content)["price"] == 100
    assert message.additional_kwargs["cache_hit"] is True
    assert message.additional_kwargs["executed_at"] == 100
