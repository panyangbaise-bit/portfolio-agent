"""Manual controls must report durable outcomes and reject duplicate starts."""
import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.models import Base, JobRun
from scheduler import cron, jobs


@pytest.fixture
def job_db(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(jobs, "get_session", lambda: Session(engine))
    monkeypatch.setattr(jobs, "notify", lambda *args: None)
    monkeypatch.setattr(cron, "_manual_runs", {})
    yield engine
    engine.dispose()


@pytest.mark.parametrize("outcome", ["completed", "skipped", "failed"])
def test_manual_status_matches_durable_job_outcome(job_db, monkeypatch, outcome):
    finished = threading.Event()
    original_thread = threading.Thread

    def tracked_thread(target, **kwargs):
        def run():
            try:
                target()
            finally:
                finished.set()
        return original_thread(target=run, **kwargs)

    monkeypatch.setattr(cron.threading, "Thread", tracked_thread)
    monkeypatch.setattr(jobs, "is_trading_day", lambda market: outcome != "skipped")
    report = "Detailed report. " * 100

    def analyze(market):
        if outcome == "failed":
            raise RuntimeError("Data source timed out")
        return report

    monkeypatch.setattr(jobs, "run_after_market_analysis", analyze)
    assert cron.trigger_job("us_after_market")
    assert finished.wait(3)
    state = cron.get_manual_run_status("us_after_market")
    with Session(job_db) as db:
        run = db.query(JobRun).one()
        assert run.status == state["status"] == outcome
        if outcome == "completed":
            assert run.details == report  # longer than the former 500-character cut-off
        if outcome == "failed":
            assert state["error"] == run.details == "Data source timed out"


def test_repeated_manual_requests_share_one_active_run(monkeypatch):
    monkeypatch.setattr(cron, "_manual_runs", {})
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def run_job():
        calls.append(True)
        entered.set()
        release.wait(3)
        finished.set()
        return {"status": "completed"}

    monkeypatch.setitem(cron.JOB_FUNCTIONS, "test_job", run_job)
    try:
        assert cron.trigger_job("test_job")
        assert entered.wait(1)
        # Clearing status while running must not permit a second launch.
        cron.clear_manual_run_status("test_job")
        for _ in range(5):
            assert cron.trigger_job("test_job")
        assert len(calls) == 1
        snapshot = cron.get_manual_run_status("test_job")
        snapshot["status"] = "failed"
        assert cron.get_manual_run_status("test_job")["status"] == "running"
    finally:
        release.set()
        assert finished.wait(2)
