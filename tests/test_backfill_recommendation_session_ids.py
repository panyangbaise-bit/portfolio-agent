"""Backfill orphan recommendation.session_id from save_recommendation tool logs."""

import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from db.migrate import migrate, _backfill_recommendation_session_ids
from db.models import Base
from db.repository import create_agent_session, create_recommendation, log_tool_call


def test_backfill_recommendation_session_ids_from_tool_logs():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        s = create_agent_session(db, "schedule", job_id="us_after_market", market="US")
        sid = s.id
        # Simulate the historical bug: recommendation landed on session_id=0
        rec = create_recommendation(
            db, session_id=0, ticker="AAPL", action="buy_add",
            reasoning="dip buy", confidence=0.8, urgency="medium",
        )
        rec_id = rec.id
        log_tool_call(
            db,
            sid,
            "save_recommendation",
            params={"ticker": "AAPL", "action": "buy_add"},
            result_summary=json.dumps({
                "status": "saved",
                "recommendation_id": rec_id,
                "ticker": "AAPL",
                "action": "buy_add",
            }),
        )
    finally:
        db.close()

    with engine.connect() as conn:
        _backfill_recommendation_session_ids(conn)
        conn.commit()
        row = conn.execute(
            text("SELECT session_id FROM recommendations WHERE id = :id"),
            {"id": rec_id},
        ).one()
        assert row[0] == sid


def test_migrate_applies_v6_backfill(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    # Ensure v6 is pending
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS _migrations "
            "(version TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ))
        conn.commit()

    migrate(engine)

    with engine.connect() as conn:
        versions = {
            r[0] for r in conn.execute(text("SELECT version FROM _migrations")).fetchall()
        }
    assert "v6_backfill_recommendation_session_ids" in versions
