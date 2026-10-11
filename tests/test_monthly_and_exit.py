"""Monthly summary still runs with no trades; a full exit schedules a review."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent.core import build_exit_context, compose_monthly_context, run_trade_review_analysis
from agent.exit_review import schedule_exit_analysis
from db.models import Base
from db.repository import apply_trade, create_holding


def test_monthly_context_skips_when_nothing_to_summarize():
    assert compose_monthly_context({"holdings": [], "trade_lines": []}) is None


def test_monthly_context_includes_empty_trade_window():
    text = compose_monthly_context({
        "holdings": ["- AAPL"],
        "holding_lines": ["- AAPL US open core shares=1"],
        "trade_lines": [],
        "closed_lines": [],
        "return_summary": "总收益 ¥1",
    })
    assert "月度总结" in text
    assert "近窗口无成交" in text
    assert "总收益 ¥1" in text


def test_monthly_review_invokes_agent_without_trades(monkeypatch):
    monkeypatch.setattr(
        "agent.core._load_monthly_inputs",
        lambda days: {
            "holdings": ["- AAPL"],
            "holding_lines": ["- AAPL"],
            "trade_lines": [],
            "closed_lines": [],
            "return_summary": "总收益 ¥1",
        },
    )
    seen = {}

    class FakeSession:
        session_id = 7

        def start(self):
            return None

        def finish(self, summary=None):
            seen["summary"] = summary

    monkeypatch.setattr("agent.core.AgentSessionManager", lambda **kwargs: FakeSession())

    def invoke(session, state):
        seen["context"] = state["extra_context"]
        return {"messages": [SimpleNamespace(content="总结完成")]}

    monkeypatch.setattr("agent.core._invoke_agent", invoke)
    assert run_trade_review_analysis() == "总结完成"
    assert "近窗口无成交" in seen["context"]
    assert seen["summary"] == "总结完成"


def test_monthly_review_skips_empty_book(monkeypatch):
    monkeypatch.setattr(
        "agent.core._load_monthly_inputs",
        lambda days: {"holdings": [], "trade_lines": []},
    )
    called = []
    monkeypatch.setattr(
        "agent.core._invoke_agent",
        lambda *args, **kwargs: called.append(True),
    )
    assert run_trade_review_analysis() is None
    assert called == []


def test_exit_prompt_does_not_ask_for_a_recommendation():
    text = build_exit_context("AAPL", "US", "core", "- sell 10 @ 90", -100, "USD", -700)
    assert "不要 save_recommendation" in text
    assert "-100.00" in text
    assert "USD" in text


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        yield db
    finally:
        db.close()


def test_full_exit_schedules_review(monkeypatch, session):
    calls = []
    monkeypatch.setattr(
        "db.repository._schedule_exit_analysis",
        lambda holding_id, txn_id: calls.append((holding_id, txn_id)),
    )
    holding = create_holding(session, "AAPL", "US", shares=10, cost_basis=100.0)
    apply_trade(session, holding.id, "sell", shares=10, price=90.0)
    assert len(calls) == 1
    assert calls[0][0] == holding.id


def test_partial_sell_does_not_schedule_review(monkeypatch, session):
    calls = []
    monkeypatch.setattr(
        "db.repository._schedule_exit_analysis",
        lambda holding_id, txn_id: calls.append((holding_id, txn_id)),
    )
    holding = create_holding(session, "AAPL", "US", shares=10, cost_basis=100.0)
    apply_trade(session, holding.id, "sell", shares=4, price=130.0)
    assert calls == []


def test_schedule_exit_analysis_starts_daemon_thread(monkeypatch):
    started = {}

    class FakeThread:
        def __init__(self, target, args, daemon, name):
            started["daemon"] = daemon
            started["name"] = name
            started["target"] = target

        def start(self):
            started["started"] = True

    monkeypatch.setattr("agent.exit_review.threading.Thread", FakeThread)
    schedule_exit_analysis(3, 9)
    assert started["started"] is True
    assert started["daemon"] is True
    assert started["name"] == "exit-analysis-3"
    assert started["target"].__name__ == "_run_guarded"
