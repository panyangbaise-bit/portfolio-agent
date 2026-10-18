from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from streamlit.testing.v1 import AppTest

from db.models import AgentSession, Base, Recommendation, UserAction
from db.repository import create_recommendation


def test_dismiss_form_blocks_blank_input_and_saves_reason(monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        agent_session = AgentSession(triggered_by="test", status="completed")
        db.add(agent_session)
        db.commit()
        rec_id = create_recommendation(db, agent_session.id, "AAPL", "hold", "Test", 0.8).id
    monkeypatch.setattr("app.components.recommendation_card.get_session", lambda: Session(engine))
    app = AppTest.from_string(
        "from app.components.recommendation_card import render_recommendations\nrender_recommendations()"
    ).run()
    assert not app.exception
    app.text_area[0].set_value("  ")
    app.button[1].click().run()
    assert not app.exception
    assert len(app.error) == 1
    with Session(engine) as db:
        assert db.get(Recommendation, rec_id).status == "pending"
    app.text_area[0].set_value("仓位上限")
    app.button[1].click().run()
    assert not app.exception
    with Session(engine) as db:
        assert db.get(Recommendation, rec_id).status == "dismissed"
        assert db.query(UserAction).one().notes == "仓位上限"
