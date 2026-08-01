from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.models import AgentSession, Base, UserAction
from db.repository import apply_recommendation_action, create_recommendation


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _recommendation(db):
    agent_session = AgentSession(triggered_by="test", status="completed")
    db.add(agent_session)
    db.commit()
    return create_recommendation(
        db,
        agent_session.id,
        "AAPL",
        "buy_add",
        "Test recommendation",
        0.8,
    )


def test_apply_recommendation_action_accepts_pending_recommendation_once():
    db = _session()
    try:
        rec = _recommendation(db)

        first = apply_recommendation_action(db, rec.id, "accept")
        duplicate = apply_recommendation_action(db, rec.id, "dismiss")

        db.refresh(rec)
        assert first["status"] == "applied"
        assert first["action"] == "accept"
        assert duplicate["status"] == "already_handled"
        assert rec.status == "acted"
        assert db.query(UserAction).filter_by(recommendation_id=rec.id).count() == 1
    finally:
        db.close()


def test_apply_recommendation_action_rejects_unknown_action_and_missing_recommendation():
    db = _session()
    try:
        rec = _recommendation(db)

        assert apply_recommendation_action(db, rec.id, "buy")["status"] == "invalid_action"
        assert apply_recommendation_action(db, 999, "accept")["status"] == "not_found"
    finally:
        db.close()
