"""save_recommendation must bind to the real agent session via InjectedState."""

import json

from langchain_core.messages import AIMessage
from langgraph.prebuilt import ToolNode
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent.tools import save_recommendation
from db.models import Base, Recommendation
from db.repository import create_agent_session


def _engine_session(monkeypatch):
    # ToolNode runs tools in a worker thread — share one in-memory connection.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def _get_session():
        return Session(engine)

    monkeypatch.setattr("db.repository.get_session", _get_session)
    monkeypatch.setattr("agent.tools.get_session", _get_session)
    monkeypatch.setattr("agent.tools._notify_recommendation", lambda rec: None)
    return engine, _get_session


def test_tool_schema_hides_session_id():
    """LLM must not be asked to invent session_id — it was defaulting to 0."""
    from langchain_core.utils.function_calling import convert_to_openai_tool

    ot = convert_to_openai_tool(save_recommendation)
    props = ot["function"]["parameters"].get("properties") or {}
    assert "session_id" not in props
    assert "ticker" in props
    assert "reasoning" in props


def test_tool_node_injects_session_id_from_graph_state(monkeypatch):
    engine, get_db = _engine_session(monkeypatch)
    db = get_db()
    try:
        agent_sess = create_agent_session(db, "schedule", job_id="us_after_market", market="US")
        sid = agent_sess.id
    finally:
        db.close()

    tool_call = {
        "name": "save_recommendation",
        "args": {
            "ticker": "AAPL",
            "action": "buy_add",
            "reasoning": "Dip into support with rising volume.",
            "confidence": 0.8,
            "urgency": "medium",
        },
        "id": "call-1",
        "type": "tool_call",
    }
    state = {
        "messages": [AIMessage(content="", tool_calls=[tool_call])],
        "session_id": sid,
    }

    result = ToolNode([save_recommendation]).invoke(state)
    payload = json.loads(result["messages"][0].content)
    assert payload["status"] == "saved"

    db = get_db()
    try:
        rec = db.query(Recommendation).filter_by(id=payload["recommendation_id"]).one()
        assert rec.session_id == sid
    finally:
        db.close()
        engine.dispose()
