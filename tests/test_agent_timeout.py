"""Agent run timeout and session fail persistence."""

import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agent.core import AgentRunTimeout, _invoke_agent
from agent.session import AgentSessionManager
from db.models import AgentSession, Base
from db.repository import create_agent_session, end_agent_session


@pytest.fixture()
def db_factory(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    def _get():
        return SessionLocal()

    monkeypatch.setattr("db.repository.get_session", _get)
    monkeypatch.setattr("agent.session.get_session", _get)
    return SessionLocal


def test_end_agent_session_failed_not_overwritten_by_completed(db_factory):
    db = db_factory()
    try:
        s = create_agent_session(db, "event", job_id="hourly_news")
        end_agent_session(db, s.id, summary="timed out", status="failed")
        end_agent_session(db, s.id, summary="late finish", status="completed")
        row = db.query(AgentSession).filter_by(id=s.id).one()
        assert row.status == "failed"
        assert "timed out" in (row.summary or "")
    finally:
        db.close()


def test_invoke_agent_marks_session_failed_on_timeout(monkeypatch, db_factory):
    monkeypatch.setattr("agent.core.config.AGENT_RUN_TIMEOUT", 0.05)

    def _hang(_state):
        time.sleep(2)
        return {"messages": []}

    monkeypatch.setattr("agent.core.agent_graph.invoke", _hang)

    mgr = AgentSessionManager(triggered_by="event", job_id="hourly_news")
    mgr.start()

    with pytest.raises(AgentRunTimeout):
        _invoke_agent(mgr, {
            "messages": [],
            "session_id": mgr.session_id,
            "triggered_by": "event",
            "extra_context": "",
        })

    db = db_factory()
    try:
        row = db.query(AgentSession).filter_by(id=mgr.session_id).one()
        assert row.status == "failed"
        assert "timed out" in (row.summary or "").lower()
    finally:
        db.close()
