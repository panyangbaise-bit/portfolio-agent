"""APScheduler configuration — starts and manages all scheduled jobs."""

import logging
import threading
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import config
from scheduler.jobs import (
    job_after_market_us,
    job_after_market_cn,
    job_after_market_hk,
    job_after_market_crypto,
    job_hourly_news_poll,
    job_monthly_trade_review,
)
from scheduler.settings import get_news_crontab, set_news_crontab, validate_crontab

logger = logging.getLogger(__name__)

# Re-export for UI / callers
__all__ = [
    "start_scheduler",
    "stop_scheduler",
    "get_scheduler_status",
    "update_news_crontab",
    "get_news_crontab",
    "trigger_job",
    "get_manual_run_status",
    "clear_manual_run_status",
    "JOB_FUNCTIONS",
    "NEWS_JOB_ID",
]

_scheduler: Optional[BackgroundScheduler] = None

JOB_FUNCTIONS: dict[str, Callable] = {
    "us_after_market": job_after_market_us,
    "cn_after_market": job_after_market_cn,
    "hk_after_market": job_after_market_hk,
    "crypto_daily": job_after_market_crypto,
    "hourly_news": job_hourly_news_poll,
    "monthly_trade_review": job_monthly_trade_review,
}

# Track manual trigger runs for the dashboard to poll.
_manual_runs: dict[str, dict] = {}

NEWS_JOB_ID = "hourly_news"
NEWS_JOB_NAME = "新闻轮询"


def _news_trigger(crontab: Optional[str] = None) -> CronTrigger:
    expr = crontab if crontab is not None else get_news_crontab()
    return validate_crontab(expr, timezone=config.APP_TIMEZONE)


def start_scheduler():
    """Start the background scheduler with all jobs configured."""
    global _scheduler

    if _scheduler is not None:
        logger.warning("Scheduler already running.")
        return

    _scheduler = BackgroundScheduler(
        # max_instances=2: news can overlap a market after-market job without blocking.
        # Allow short server restarts without silently losing a scheduled run.
        job_defaults={"coalesce": True, "max_instances": 2, "misfire_grace_time": 300},
    )

    _scheduler.add_job(
        job_after_market_us,
        trigger=CronTrigger(hour=7, minute=30, timezone="Asia/Shanghai"),
        id="us_after_market",
        name="美股盘后分析",
    )

    _scheduler.add_job(
        job_after_market_cn,
        trigger=CronTrigger(hour=15, minute=30, timezone="Asia/Shanghai"),
        id="cn_after_market",
        name="A股盘后分析",
    )

    _scheduler.add_job(
        job_after_market_hk,
        trigger=CronTrigger(hour=16, minute=30, timezone="Asia/Hong_Kong"),
        id="hk_after_market",
        name="港股盘后分析",
    )

    _scheduler.add_job(
        job_after_market_crypto,
        trigger=CronTrigger(hour=21, minute=0, timezone="Asia/Shanghai"),
        id="crypto_daily",
        name="Crypto每日分析",
    )

    news_cron = get_news_crontab()
    _scheduler.add_job(
        job_hourly_news_poll,
        trigger=_news_trigger(news_cron),
        id=NEWS_JOB_ID,
        name=NEWS_JOB_NAME,
    )
    logger.info("News poll crontab: %s (%s)", news_cron, config.APP_TIMEZONE)

    _scheduler.add_job(
        job_monthly_trade_review,
        trigger=CronTrigger(
            day=1, hour=21, minute=0, timezone="Asia/Shanghai",
        ),
        id="monthly_trade_review",
        name="月度交易复盘",
    )

    _scheduler.start()
    logger.info("Scheduler started with 6 jobs.")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped.")


def get_scheduler_status() -> list[dict]:
    """Return status of all scheduled jobs for the dashboard."""
    if not _scheduler:
        return []
    jobs = []
    for job in _scheduler.get_jobs():
        entry = {
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else "paused",
        }
        if job.id == NEWS_JOB_ID:
            entry["crontab"] = get_news_crontab()
        jobs.append(entry)
    return jobs


def update_news_crontab(expr: str) -> str:
    """Validate, persist, and live-reschedule the news poll job.

    Returns the cleaned crontab expression.
    Raises ValueError if the expression is invalid.
    """
    cleaned = set_news_crontab(expr)
    if _scheduler is not None:
        _scheduler.reschedule_job(NEWS_JOB_ID, trigger=_news_trigger(cleaned))
        logger.info("Rescheduled %s to crontab: %s", NEWS_JOB_ID, cleaned)
    return cleaned


def trigger_job(job_id: str) -> bool:
    """Manually trigger a job by its ID. Runs in a background thread.

    Returns True if the job was found and started, False if unknown job_id.
    """
    func = JOB_FUNCTIONS.get(job_id)
    if not func:
        logger.warning(f"Unknown job_id for manual trigger: {job_id}")
        return False

    _manual_runs[job_id] = {"status": "running", "started_at": None, "error": None}

    def _wrapper():
        from datetime import datetime, timezone

        from app.timeutil import format_display_time

        _manual_runs[job_id]["started_at"] = format_display_time(
            datetime.now(timezone.utc),
            fmt="%Y-%m-%d %H:%M:%S",
        )
        try:
            func()
            _manual_runs[job_id]["status"] = "completed"
        except Exception as e:
            logger.error(f"Manual trigger {job_id} failed: {e}")
            _manual_runs[job_id]["status"] = "failed"
            _manual_runs[job_id]["error"] = str(e)

    thread = threading.Thread(target=_wrapper, daemon=True, name=f"manual-{job_id}")
    thread.start()
    logger.info(f"Manual trigger started for job: {job_id}")
    return True


def get_manual_run_status(job_id: str) -> Optional[dict]:
    """Return the status of a manually triggered run, or None if never triggered."""
    return _manual_runs.get(job_id)


def clear_manual_run_status(job_id: str):
    """Clear the manual run status so the button resets."""
    _manual_runs.pop(job_id, None)
