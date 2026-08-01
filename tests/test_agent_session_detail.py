"""Tests for agent session detail reads and tool-result truncation."""

from contextlib import nullcontext
from types import SimpleNamespace

from app.components import analysis_table
from agent.graph import _truncate_result
from db.models import Base
from db.repository import (
    create_agent_session,
    create_recommendation,
    get_agent_session_detail,
    list_analysis_runs,
    log_tool_call,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_truncate_result_keeps_full_text_under_cap():
    text = "x" * 1000
    assert _truncate_result(text) == text


def test_truncate_result_caps_extreme_payloads():
    text = "y" * 100_001
    out = _truncate_result(text)
    assert out.endswith("…[truncated]")
    assert len(out) == 100_000 + len("…[truncated]")


def test_get_agent_session_detail_includes_reasoning_and_tools():
    db = _session()
    try:
        s = create_agent_session(db, "schedule", job_id="us_after_market", market="US")
        create_recommendation(
            db,
            s.id,
            ticker="AAPL",
            action="hold",
            reasoning="Full reasoning chain about earnings.",
            confidence=0.8,
        )
        log_tool_call(
            db,
            s.id,
            "get_price",
            params={"ticker": "AAPL"},
            result_summary='{"price": 190.5}',
        )
        detail = get_agent_session_detail(db, s.id)
        assert detail is not None
        assert detail["job_id"] == "us_after_market"
        assert len(detail["recommendations"]) == 1
        assert "Full reasoning" in detail["recommendations"][0]["reasoning"]
        assert detail["tool_calls"][0]["tool_name"] == "get_price"
        assert detail["tool_calls"][0]["params"]["ticker"] == "AAPL"
    finally:
        db.close()


def test_list_analysis_runs_filters_by_job_id():
    db = _session()
    try:
        create_agent_session(db, "schedule", job_id="us_after_market", market="US")
        create_agent_session(db, "event", job_id="hourly_news")
        us_only = list_analysis_runs(db, job_id="us_after_market")
        assert len(us_only) == 1
        assert us_only[0]["job_id"] == "us_after_market"
        assert us_only[0]["tool_count"] == 0
    finally:
        db.close()


def test_tool_call_expanders_are_collapsed_by_default(monkeypatch):
    expanded_states = []

    class FakeStreamlit:
        def subheader(self, *args, **kwargs):
            return None

        def selectbox(self, *args, **kwargs):
            options = kwargs["options"]
            return options[0] if len(options) == 1 else options[1]

        def dataframe(self, *args, **kwargs):
            return None

        def markdown(self, *args, **kwargs):
            return None

        def caption(self, *args, **kwargs):
            return None

        def expander(self, title, expanded):
            expanded_states.append(expanded)
            return nullcontext()

        def code(self, *args, **kwargs):
            return None

        def text(self, *args, **kwargs):
            return None

    run = {
        "id": 1,
        "started_at": None,
        "job_id": "us_after_market",
        "triggered_by": "schedule",
        "market": "US",
        "status": "completed",
        "rec_count": 0,
        "tool_count": 2,
        "summary": "",
    }
    detail = {
        "summary": "",
        "recommendations": [],
        "tool_calls": [
            {"tool_name": "get_portfolio", "called_at": None, "params": {}, "result_summary": ""},
            {"tool_name": "get_price", "called_at": None, "params": {}, "result_summary": ""},
        ],
    }
    monkeypatch.setattr(analysis_table, "st", FakeStreamlit())
    monkeypatch.setattr(analysis_table, "t", lambda key, **kwargs: key)
    monkeypatch.setattr(analysis_table, "enum_label", lambda *args: "label")
    monkeypatch.setattr(analysis_table, "get_session", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(analysis_table, "list_analysis_runs", lambda *args, **kwargs: [run])
    monkeypatch.setattr(analysis_table, "get_agent_session_detail", lambda *args: detail)

    analysis_table.render_agent_session_detail()

    assert expanded_states == [False, False]
