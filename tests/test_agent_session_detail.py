"""Tests for agent session detail reads and tool-result truncation."""

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
