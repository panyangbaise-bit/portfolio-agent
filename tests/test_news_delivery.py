from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent.news_delivery import NewsReport, event_key, set_news_notification, unseen_news
from db.models import AgentSession, Base


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_processed_events_dedupe_but_changes_and_gaps_are_rechecked(db):
    article = {"title": "earnings", "url": "https://example.com/1", "summary": "old"}
    db.add(
        AgentSession(
            triggered_by="event",
            job_id="hourly_news",
            status="completed",
            news_snapshot={
                "portfolio_signature": "same",
                "processed": True,
                "event_keys": [event_key(article)],
            },
        )
    )
    db.commit()
    assert unseen_news(db, [article], "same") == []
    assert unseen_news(db, [article], "changed") == [article]
    updated = {**article, "summary": "revised"}
    assert unseen_news(db, [updated], "same") == [updated]
    gap = {**article, "category": "coverage"}
    assert unseen_news(db, [gap], "same") == [gap]


def test_failed_delivery_is_not_marked_processed(db):
    article = {"title": "earnings"}
    db.add(
        AgentSession(
            triggered_by="event",
            job_id="hourly_news",
            status="completed",
            news_snapshot={"portfolio_signature": "same", "event_keys": [event_key(article)]},
        )
    )
    db.commit()
    assert unseen_news(db, [article], "same") == [article]


def test_notification_tool_requires_current_evidence_and_news_scope():
    state = {"triggered_by": "event", "citation_sources": {"known": {"url": "https://example.com"}}}
    args = {
        "notify": True,
        "reason": "新披露改变风险判断",
        "source_ids": ["invented"],
        "state": state,
    }
    assert set_news_notification.invoke(args)["error"] == "missing_evidence"
    assert set_news_notification.invoke({**args, "source_ids": ["known"]})["status"] == "recorded"
    assert (
        set_news_notification.invoke({**args, "notify": False, "source_ids": []})["notify"] is False
    )
    assert set_news_notification.invoke({**args, "state": {}})["error"] == "not_news_task"


@pytest.mark.parametrize(
    "should_notify,delivered,expected",
    [(False, True, "completed"), (True, True, "completed"), (True, False, "failed")],
)
def test_scheduler_uses_explicit_decision_not_nonempty_text(
    monkeypatch, tmp_path, should_notify, delivered, expected
):
    from scheduler import jobs

    engine = create_engine(f"sqlite:///{tmp_path / 'news.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        analysis = AgentSession(
            triggered_by="event", job_id="hourly_news", status="completed", news_snapshot={}
        )
        db.add(analysis)
        db.commit()
        sid = analysis.id
    report = NewsReport(
        "非空报告", {"status": "recorded", "notify": should_notify, "reason": "test"}
    )
    report.session_id = sid
    sent = []
    monkeypatch.setattr(jobs, "get_session", lambda: Session(engine))
    monkeypatch.setattr(
        jobs,
        "get_open_holdings",
        lambda db: [
            SimpleNamespace(
                market="US", ticker="DUOL", shares=1, cost_basis=1, position_type="core"
            )
        ],
    )
    monkeypatch.setattr(jobs, "poll_news_for_portfolio", lambda _: [{"title": "new"}])
    monkeypatch.setattr(jobs, "run_news_triggered_analysis", lambda *a, **k: report)
    monkeypatch.setattr(jobs, "notify", lambda text: sent.append(text) or delivered)
    result = jobs.job_hourly_news_poll()
    assert result["status"] == expected
    assert bool(sent) is should_notify
    with Session(engine) as db:
        assert bool(db.get(AgentSession, sid).news_snapshot.get("processed")) is (
            expected == "completed"
        )
    engine.dispose()
