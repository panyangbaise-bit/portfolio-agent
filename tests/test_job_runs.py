from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.models import Base
from db.repository import create_job_run, finish_job_run, list_job_runs


def test_job_run_records_skipped_outcome():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        run = create_job_run(session, "hourly_news", "每小时新闻轮询")
        finish_job_run(session, run.id, "skipped", "No holdings to monitor.")

        rows = list_job_runs(session)
        assert len(rows) == 1
        assert rows[0].job_id == "hourly_news"
        assert rows[0].status == "skipped"
        assert rows[0].details == "No holdings to monitor."
        assert rows[0].ended_at is not None
    finally:
        session.close()


def test_job_run_filters_apply_before_limit():
    from datetime import datetime, timedelta
    from db.models import JobRun

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        old = datetime(2026, 10, 1)
        db.add(JobRun(job_id="hourly_news", job_name="News", status="failed", started_at=old))
        for i in range(5):
            db.add(JobRun(job_id="hourly_news", job_name="News", status="completed", started_at=old + timedelta(days=i+1)))
        db.add(JobRun(job_id="crypto_daily", job_name="Crypto", status="failed", started_at=old + timedelta(days=10)))
        db.commit()
        rows = list_job_runs(db, limit=1, job_id="hourly_news", status="failed")
        assert len(rows) == 1
        assert rows[0].job_id == "hourly_news"
        assert rows[0].status == "failed"
        assert rows[0].started_at == old
