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


def test_dismiss_requires_nonblank_reason_and_does_not_mutate_pending_record():
    db = _session()
    try:
        rec = _recommendation(db)
        for reason in (None, "", " \n\t "):
            assert apply_recommendation_action(db, rec.id, "dismiss", reason)["status"] == "reason_required"
            db.refresh(rec)
            assert rec.status == "pending"
            assert db.query(UserAction).count() == 0

        result = apply_recommendation_action(db, rec.id, "dismiss", "  仓位已达到上限  ")
        assert result["status"] == "applied"
        db.refresh(rec)
        assert rec.status == "dismissed"
        assert rec.user_action.notes == "仓位已达到上限"
    finally:
        db.close()


def test_dismissal_reason_is_available_in_detached_history():
    from db.repository import get_recommendation_history

    db = _session()
    rec = _recommendation(db)
    apply_recommendation_action(db, rec.id, "dismiss", "Position limit")
    history = get_recommendation_history(db)
    db.close()
    assert history[0].user_action.notes == "Position limit"
