"""Evidence durability, temporal boundaries and hybrid failure behavior."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from config import config
from db.models import (Base, Holding, Transaction, AgentSession, Recommendation,
                       MemoryDocument, MemoryChunk, TradingDiscipline, ConversationMessage)
from db.repository import (create_holding, delete_holding, get_all_holdings, list_transactions,
                           save_trading_discipline, apply_recommendation_action, end_agent_session)
from memory import backends, retrieval
from memory.indexer import initialize, backfill_batch, index_lexical_batch, index_vector_batch


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(config, "MEMORY_VECTOR_ENABLED", False)
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    initialize(eng)
    yield eng
    eng.dispose()


def index_all(engine):
    while index_lexical_batch(engine):
        pass


def seed(db):
    holding = create_holding(db, "DUOL", "US", 4, 160, name="多邻国")
    session = AgentSession(triggered_by="manual", job_id="us_after_market", market="US", status="completed",
                           summary="DUOL 跌破支撑，建议减仓，避免追涨杀跌。")
    db.add(session)
    db.commit()
    rec = Recommendation(session_id=session.id, ticker="DUOL", action="reduce", reasoning="跌破支撑减仓",
                         confidence=.8, urgency="high")
    db.add(rec)
    db.commit()
    return holding, session, rec


def test_capture_is_atomic_and_rollback_does_not_leave_evidence(engine):
    with Session(engine) as db:
        db.add(TradingDiscipline(id=1, content="拒绝追涨"))
        db.flush()
        db.rollback()
        assert db.scalar(select(func.count()).select_from(MemoryDocument)) == 0
        assert db.get(TradingDiscipline, 1) is None


def test_rules_versions_and_archive_preserve_ledger(engine):
    with Session(engine) as db:
        save_trading_discipline(db, "每次开仓先确定止损")
        save_trading_discipline(db, "不要追涨")
        docs = db.scalars(select(MemoryDocument).where(MemoryDocument.source_type == "discipline").order_by(MemoryDocument.id)).all()
        assert len(docs) == 2
        assert docs[0].snapshot["content"] == "每次开仓先确定止损"
        assert docs[1].previous["content"] == "每次开仓先确定止损"
        holding = create_holding(db, "DUOL", "US", 4, 160)
        delete_holding(db, holding.id)
        assert get_all_holdings(db) == []
        assert list_transactions(db) == []
        assert db.scalar(select(func.count()).select_from(Transaction)) == 1
        assert db.get(Holding, holding.id).status == "archived"
    index_all(engine)
    with Session(engine) as db:
        assert retrieval.search(db, "止损")["results"]
        assert retrieval.timeline(db, "DUOL", source_types=["transaction"])["results"]


def test_chinese_search_feedback_and_bidirectional_links(engine):
    with Session(engine) as db:
        _, _, rec = seed(db)
        apply_recommendation_action(db, rec.id, "dismiss", "我担心卖出后踏空，想等待反弹")
    index_all(engine)
    with Session(engine) as db:
        result = retrieval.search(db, "踏空", instruments=["多邻国"], source_types=["feedback"])
        assert result["status"] == "ok"
        assert len(result["results"]) == 1
        feedback = result["results"][0]
        full = retrieval.read(db, feedback["evidence_id"])
        recs = [r for r in full["related_evidence"] if r["source_type"] == "recommendation"]
        assert recs and "踏空" in full["excerpt"]
        detail = retrieval.read(db, recs[0]["evidence_id"])
        assert any(r["source_type"] == "feedback" for r in detail["related_evidence"])
        assert retrieval.search(db, "踏空", instruments=["HK:DUOL"])["results"] == []


def test_asof_applies_to_search_read_and_linked_records(engine):
    with Session(engine) as db:
        _, _, rec = seed(db)
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None)
        apply_recommendation_action(db, rec.id, "dismiss", "事后改变观点")
        latest = db.scalars(select(MemoryDocument).where(MemoryDocument.source_type == "feedback")).one()
        latest.known_at = cutoff + timedelta(days=1)
        rid = db.scalars(select(MemoryDocument.id).where(MemoryDocument.source_type == "recommendation").order_by(MemoryDocument.id)).first()
        fid = latest.id
        db.commit()
    index_all(engine)
    with Session(engine) as db:
        stamp = cutoff.isoformat() + "Z"
        assert retrieval.search(db, "事后", source_types=["feedback"], as_of=stamp)["results"] == []
        assert retrieval.read(db, f"M{fid}", as_of=stamp)["status"] == "not_found"
        assert not any(x["source_type"] == "feedback" for x in retrieval.read(db, f"M{rid}", as_of=stamp)["related_evidence"])


def test_backfill_is_restartable_and_conservative(engine):
    with Session(engine) as db:
        db.info["skip_memory_capture"] = True
        db.add(TradingDiscipline(id=1, content="2020年旧规则", updated_at=datetime(2020, 1, 1)))
        db.commit()
    assert backfill_batch(engine, 1) == 1
    assert backfill_batch(engine, 1) == 0
    with Session(engine) as db:
        doc = db.scalars(select(MemoryDocument)).one()
        assert doc.time_quality == "imported"
        assert doc.known_at.year >= 2026
        assert doc.occurred_at.year == 2020
    index_all(engine)
    assert index_lexical_batch(engine) == 0
    with Session(engine) as db:
        assert retrieval.search(db, "旧规则", as_of="2021-01-01Z")["results"] == []


def test_conversation_turns_are_separate_and_tool_results_not_reingested(engine):
    from db.models import AgentToolCall
    with Session(engine) as db:
        s = AgentSession(triggered_by="manual", job_id="ask_agent")
        db.add(s); db.commit()
        end_agent_session(db, s.id, "Q: 为什么减仓？\nA: 风险升高")
        end_agent_session(db, s.id, "Q: 什么风险？\nA: 估值和仓位", append_summary=True)
        db.add(AgentToolCall(session_id=s.id, tool_name="search_memory", result_summary="复制的历史"))
        db.commit()
        messages = db.scalars(select(ConversationMessage)).all()
        assert [m.role for m in messages] == ["user", "assistant", "user", "assistant"]
        assert messages[-1].created_at >= messages[0].created_at
        docs = db.scalars(select(MemoryDocument)).all()
        assert len(docs) == 4 and all(d.source_type == "message" for d in docs)


def test_timeline_pagination_has_no_duplicates_and_filters_before_limit(engine):
    with Session(engine) as db:
        for i in range(6):
            db.add(Holding(ticker="AAPL" if i % 2 else "DUOL", market="US", shares=0, cost_basis=0))
        db.commit()
        seen, cursor = [], 0
        while True:
            page = retrieval.timeline(db, "US:AAPL", limit=1, cursor=cursor)
            seen += [i["evidence_id"] for i in page["results"]]
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert len(seen) == len(set(seen)) == 3


def test_conversation_preserves_user_text_containing_answer_separator(engine):
    with Session(engine) as db:
        s = AgentSession(triggered_by="manual", job_id="ask_agent")
        db.add(s); db.commit()
        question = "请解释这个格式：\nA: 示例答案"
        db.add(ConversationMessage(session_id=s.id, role="user", content=question))
        db.commit()
        end_agent_session(db, s.id, f"Q: {question}\nA: 这是示例中的答案标签")
        messages = db.scalars(select(ConversationMessage).order_by(ConversationMessage.id)).all()
        assert [(m.role, m.content) for m in messages] == [
            ("user", question), ("assistant", "这是示例中的答案标签")]


def test_hybrid_failure_preserves_lexical_and_surfaces_degradation(engine, monkeypatch):
    with Session(engine) as db:
        save_trading_discipline(db, "不要追涨")
    index_all(engine)
    monkeypatch.setattr(backends, "configured", lambda: True)
    def broken(_):
        raise backends.BackendError("Service unavailable")
    monkeypatch.setattr(backends, "embed", broken)
    with Session(engine) as db:
        result = retrieval.search(db, "追涨")
        assert result["mode"] == "lexical_fallback" and result["status"] == "degraded"
        assert result["results"]


def test_vector_ingestion_is_bounded_retryable_and_filters_stale_payload(engine, monkeypatch):
    with Session(engine) as db:
        save_trading_discipline(db, "不要追涨")
    index_all(engine)
    monkeypatch.setattr(backends, "configured", lambda: True)
    monkeypatch.setattr(backends, "embed", lambda texts: [[1., 0.] for _ in texts])
    points = []
    class Client:
        def ensure(self): pass
        def upsert(self, batch): points.extend(batch)
        def search(self, vector, conditions, limit): return [p["id"] for p in points]
    monkeypatch.setattr(backends, "Qdrant", Client)
    assert index_vector_batch(engine) == 1
    assert index_vector_batch(engine) == 0
    assert points and points[0]["payload"]["source_type"] == "discipline"
    with Session(engine) as db:
        assert retrieval.search(db, "风险控制")["mode"] == "hybrid"
        assert retrieval.search(db, "风险控制", as_of="2020-01-01Z")["results"] == []
        assert retrieval.search(db, "风险控制", source_types=["feedback"])["results"] == []


def test_backend_rejects_invalid_vectors_and_namespaces_models(monkeypatch):
    monkeypatch.setattr(backends, "configured", lambda: True)
    monkeypatch.setattr(config, "MEMORY_EMBEDDING_DIMENSIONS", 2)
    monkeypatch.setattr(backends, "request", lambda *a, **kw: {"data": [{"index": 0, "embedding": [float("nan"), 0]}]})
    with pytest.raises(backends.BackendError): backends.embed(["test"])
    first = backends.Qdrant().url
    monkeypatch.setattr(config, "MEMORY_EMBEDDING_MODEL", "changed-model")
    assert backends.Qdrant().url != first


def test_migration_creates_memory_schema_for_existing_db(engine):
    from db.migrate import migrate
    with engine.begin() as conn:
        for name in ("memory_chunks", "memory_documents", "memory_checkpoints", "conversation_messages", "memory_fts"):
            conn.execute(text("DROP TABLE " + name))
    migrate(engine); migrate(engine)
    with Session(engine) as db:
        save_trading_discipline(db, "迁移后能保存")
    index_all(engine)
    with Session(engine) as db:
        assert retrieval.search(db, "迁移")["results"]


def test_run_and_analysis_are_linked_without_duplicating_report_text(engine, monkeypatch):
    from memory.context import current_run_id
    from db.repository import create_agent_session, create_job_run, finish_job_run
    with Session(engine) as db:
        run = create_job_run(db, "us_after_market", "US")
        token = current_run_id.set(run.id)
        try:
            sess = create_agent_session(db, "cron", job_id="us_after_market", market="US")
        finally:
            current_run_id.reset(token)
        end_agent_session(db, sess.id, "DUOL 独一无二的分析正文")
        finish_job_run(db, run.id, "completed", "DUOL 独一无二的分析正文")
        run_doc = db.scalars(select(MemoryDocument).where(MemoryDocument.source_type == "run")).one()
        assert "独一无二" not in run_doc.body
        assert run_doc.snapshot["details"] == "DUOL 独一无二的分析正文"
        assert run_doc.relations == [{"source_type": "analysis", "source_id": sess.id}]
        links = retrieval.read(db, f"M{run_doc.id}")["related_evidence"]
        assert len(links) == 1 and links[0]["source_type"] == "analysis"
        reverse = retrieval.read(db, links[0]["evidence_id"])["related_evidence"]
        assert [item["evidence_id"] for item in reverse] == [f"M{run_doc.id}"]


def test_vector_failure_records_retry_then_recovers(engine, monkeypatch):
    with Session(engine) as db:
        save_trading_discipline(db, "避免追涨")
    index_all(engine)
    monkeypatch.setattr(backends, "configured", lambda: True)
    class Broken:
        def ensure(self): raise backends.BackendError("Service unavailable")
    monkeypatch.setattr(backends, "Qdrant", Broken)
    assert index_vector_batch(engine) == 1
    assert index_vector_batch(engine) == 0  # backoff, not a tight retry loop
    with Session(engine) as db:
        doc = db.scalars(select(MemoryDocument)).one()
        assert doc.attempts == 1 and doc.error and doc.vector_profile is None
        assert doc.indexed_at is not None  # lexical index is still usable
        doc.retry_at = datetime(2000, 1, 1)
        db.commit()
    class Healthy:
        def ensure(self): pass
        def upsert(self, points): pass
    monkeypatch.setattr(backends, "Qdrant", Healthy)
    monkeypatch.setattr(backends, "embed", lambda texts: [[1., 0.] for _ in texts])
    assert index_vector_batch(engine) == 1
    with Session(engine) as db:
        doc = db.scalars(select(MemoryDocument)).one()
        assert doc.error is None and doc.attempts == 0 and doc.vector_profile


def test_memory_ui_search_open_and_timeline(engine, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    with Session(engine) as db:
        _, _, rec = seed(db)
        apply_recommendation_action(db, rec.id, "dismiss", "等待反弹，担心踏空")
    index_all(engine)
    monkeypatch.setattr("db.repository.get_session", lambda: Session(engine))
    app = AppTest.from_file(str(Path("app/views/memory.py").resolve())).run()
    assert not app.exception and not app.error
    app.text_input[0].set_value("踏空")
    next(b for b in app.button if b.label == "Search").click().run()
    assert not app.exception and not app.error
    assert any("踏空" in x.value for x in app.text)
    next(b for b in app.button if b.label == "Read source").click().run()
    assert any("踏空" in x.value for x in app.markdown)
    next(b for b in app.button if b.label == "Browse timeline").click().run()
    assert not app.exception and not app.error
    assert app.session_state["memory_results"]["results"]


def test_tools_report_errors_instead_of_empty_evidence(monkeypatch):
    from memory.tools import search_memory, read_memory
    class Broken:
        def __enter__(self): raise RuntimeError("offline")
        def __exit__(self, *args): pass
    monkeypatch.setattr("memory.tools.get_session", Broken)
    assert search_memory.invoke({"query": "止损"})["status"] == "error"
    assert read_memory.invoke({"evidence_id": "M1"})["status"] == "error"


def test_embedding_cache_avoids_duplicate_calls_across_retries(engine, monkeypatch):
    from memory.indexer import embed_cached
    calls = []
    def embed(texts):
        calls.append(texts)
        return [[1., 0.] for _ in texts]
    monkeypatch.setattr(backends, "embed", embed)
    assert embed_cached(engine, ["same", "same"]) == [[1., 0.], [1., 0.]]
    assert embed_cached(engine, ["same"]) == [[1., 0.]]
    assert calls == [["same"]]
    monkeypatch.setattr(config, "MEMORY_EMBEDDING_MODEL", "new-model")
    embed_cached(engine, ["same"])
    assert calls == [["same"], ["same"]]


def test_removed_watchlist_identity_is_not_reused(engine):
    from db.repository import create_watchlist_item, delete_watchlist_item, get_watchlist_items
    with Session(engine) as db:
        item = create_watchlist_item(db, "DUOL", "US", watch_reason="等待回调")
        first_id = item.id
        delete_watchlist_item(db, first_id)
        assert not get_watchlist_items(db)
        second = create_watchlist_item(db, "AAPL", "US")
        assert second.id != first_id
        rows = retrieval.timeline(db, "US:DUOL")["results"]
        assert len(rows) == 2
        assert all(x["source_id"] == first_id for x in rows)


def test_memory_chinese_labels_override_english_fallback():
    from app.i18n import translate
    assert translate("zh", "memory.title") == "投资记忆库"
    assert translate("zh", "action.dismiss") == "已拒绝"


def test_bailian_request_sends_model_dimensions_and_float_format(monkeypatch):
    monkeypatch.setattr(backends, "configured", lambda: True)
    monkeypatch.setattr(config, "MEMORY_EMBEDDING_MODEL", "qwen3.7-text-embedding-flash")
    monkeypatch.setattr(config, "MEMORY_EMBEDDING_DIMENSIONS", 256)
    monkeypatch.setattr(config, "MEMORY_EMBEDDING_SEND_DIMENSIONS", True)
    captured = []
    def request(method, url, **kwargs):
        captured.append(kwargs["json"])
        return {"data": [{"index": 0, "embedding": [1.] * 256}]}
    monkeypatch.setattr(backends, "request", request)
    assert len(backends.embed(["历史纪律"])[0]) == 256
    assert captured == [{"model": "qwen3.7-text-embedding-flash", "input": ["历史纪律"],
                         "dimensions": 256, "encoding_format": "float"}]
    monkeypatch.setattr(config, "MEMORY_EMBEDDING_DIMENSIONS", 2048)
    with pytest.raises(backends.BackendError, match="requires"):
        backends.embed(["bad dimensions"])
