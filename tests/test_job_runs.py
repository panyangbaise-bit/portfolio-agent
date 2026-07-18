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
