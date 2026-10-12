from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from streamlit.testing.v1 import AppTest

from app.components import analysis_table
from db.models import AgentSession, Base, JobRun


@pytest.fixture
def jobs_ui(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    now = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
    with Session(engine) as db:
        db.add_all([
            JobRun(job_id="hourly_news", job_name="News", status="completed", started_at=now, ended_at=now + timedelta(seconds=23), details="Long runtime output " * 100),
            JobRun(job_id="crypto_daily", job_name="Crypto", status="failed", started_at=now - timedelta(hours=1), details="Price feed timed out"),
            AgentSession(triggered_by="schedule", job_id="monthly_trade_review", status="completed", summary="Monthly report body", started_at=now),
            AgentSession(triggered_by="schedule", job_id="hourly_news", status="completed", summary="Full news report body", started_at=now + timedelta(minutes=1)),
        ])
        db.commit()
    monkeypatch.setattr(analysis_table, "get_session", lambda: Session(engine))
    monkeypatch.setattr(analysis_table, "get_scheduler_status", lambda: [
        {"id": jid, "next_run": now, "crontab": "0 21 * * *", "timezone": "Asia/Shanghai"}
        for jid in analysis_table.JOB_IDS
    ])
    monkeypatch.setattr(analysis_table, "get_manual_run_status", lambda jid: None)
    monkeypatch.setattr(analysis_table, "get_news_crontab", lambda: "0 8-22/4 * * mon-fri")
    app = AppTest.from_file("app/views/operations.py").run()
    assert not app.exception
    yield app
    engine.dispose()


def test_default_page_prioritizes_schedules_and_preserves_manual_trigger(jobs_ui, monkeypatch):
    app = jobs_ui
    assert len([button for button in app.button if (button.key or "").startswith("trigger_")]) == 6
    assert not app.dataframe
    assert not any("report body" in item.value for item in app.markdown)
    assert app.expander[0].proto.expanded is False
    triggered = []
    monkeypatch.setattr(analysis_table, "trigger_job", lambda jid: triggered.append(jid) or True)
    app.button(key="trigger_hourly_news").click().run()
    assert triggered == ["hourly_news"]
    assert not app.exception


def test_runtime_filters_and_compact_table(jobs_ui):
    app = jobs_ui
    app.radio(key="jobs_section").set_value("runtime").run()
    assert not app.exception
    table = app.dataframe[0].value
    assert len(table) == 2
    assert "Details" not in table.columns
    assert "23s" in table["Duration"].values
    app.selectbox(key="jobs_runtime_status_filter").set_value("failed").run()
    assert len(app.dataframe[0].value) == 1
    assert app.dataframe[0].value.iloc[0]["Job"] == "Daily Crypto Analysis"
    app.selectbox(key="jobs_runtime_job_filter").set_value("hourly_news").run()
    assert not app.dataframe
    assert len(app.info) == 1


def test_report_workspace_keeps_monthly_collapsed_and_full_report_accessible(jobs_ui):
    app = jobs_ui
    app.radio(key="jobs_section").set_value("reports").run()
    assert not app.exception
    assert app.expander[0].proto.expanded is False
    assert [tab.label for tab in app.tabs] == ["Report", "Recommendations", "Tool Calls"]
    assert any(item.value == "Full news report body" for item in app.markdown)
    assert not app.dataframe  # no duplicate session table above the reader
    app.selectbox(key="jobs_detail_job_filter").set_value("monthly_trade_review").run()
    assert not app.exception
    assert any(item.value == "Monthly report body" for item in app.tabs[0].markdown)


def test_news_schedule_editor_still_saves_and_normalizes(jobs_ui, monkeypatch):
    saved = []
    monkeypatch.setattr(analysis_table, "update_news_crontab", lambda expr: saved.append(expr) or expr.strip())
    app = jobs_ui
    app.text_input(key="news_crontab_expr").set_value(" 0 9 * * mon-fri ")
    next(button for button in app.button if button.label == "Save & reschedule").click().run()
    assert not app.exception
    assert saved == [" 0 9 * * mon-fri "]
    assert app.text_input(key="news_crontab_expr").value == "0 9 * * mon-fri"
    assert len(app.success) == 1
