"""Recommendation noise reduction — skip routine/duplicate saves."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.models import Base, AgentSession
from db.repository import (
    create_recommendation,
    find_similar_recommendation,
)
from agent.tools import save_recommendation


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _agent_session(db: Session) -> int:
    s = AgentSession(triggered_by="test", status="running")
    db.add(s)
    db.commit()
    return s.id


def test_find_similar_pending_same_action():
    db = _session()
    try:
        sid = _agent_session(db)
        create_recommendation(
            db, sid, "AAPL", "buy_add", "add on dip", 0.8, urgency="medium",
        )
        hit = find_similar_recommendation(db, "AAPL", "buy_add", "high")
        assert hit is not None
        assert hit.action == "buy_add"
        assert hit.status == "pending"
    finally:
        db.close()


def test_find_similar_recent_same_action_urgency():
    db = _session()
    try:
        sid = _agent_session(db)
        rec = create_recommendation(
            db, sid, "QQQ", "reduce", "too heavy", 0.7, urgency="low",
        )
        rec.status = "dismissed"
        rec.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        db.commit()

        hit = find_similar_recommendation(db, "QQQ", "reduce", "low")
        assert hit is not None
        assert hit.id == rec.id
    finally:
        db.close()


def test_save_recommendation_skips_routine_hold(monkeypatch):
    # Avoid needing a live DB engine from config for skip path
    result = save_recommendation.invoke({
        "ticker": "AAPL",
        "action": "hold",
        "reasoning": "all fine",
        "confidence": 0.5,
        "urgency": "low",
        "session_id": 0,
    })
    assert result["status"] == "skipped_routine"


def test_save_recommendation_skips_unchanged(monkeypatch):
    from db import repository as repo

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    def _get_session():
        return Session(engine)

    monkeypatch.setattr(repo, "get_session", _get_session)
    monkeypatch.setattr("agent.tools.get_session", _get_session)

    db = _get_session()
    try:
        sid = _agent_session(db)
        create_recommendation(
            db, sid, "PONY", "watch", "event risk", 0.6, urgency="medium",
        )
    finally:
        db.close()

    result = save_recommendation.invoke({
        "ticker": "PONY",
        "action": "watch",
        "reasoning": "still watching",
        "confidence": 0.6,
        "urgency": "medium",
        "session_id": sid,
    })
    assert result["status"] == "skipped_unchanged"
    assert result["existing_id"] is not None
