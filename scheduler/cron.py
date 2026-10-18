"""APScheduler configuration — starts and manages all scheduled jobs."""

import logging
import threading
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import config
from scheduler.jobs import (
    job_after_market_cn,
    job_after_market_crypto,
    job_after_market_hk,
    job_after_market_us,
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
    "job_cron",
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
_manual_runs_lock = threading.Lock()

NEWS_JOB_ID = "hourly_news"
NEWS_JOB_NAME = "新闻轮询"

# 5-field crontab plus the clock timezone for every fixed job.
# News poll uses the editable crontab and APP_TIMEZONE.
FIXED_JOB_CRONS = {
    "us_after_market": ("30 7 * * *", "Asia/Shanghai"),
    "cn_after_market": ("30 15 * * *", "Asia/Shanghai"),
    "hk_after_market": ("30 16 * * *", "Asia/Hong_Kong"),
    "crypto_daily": ("0 21 * * *", "Asia/Shanghai"),
    "monthly_trade_review": ("0 21 1 * *", "Asia/Shanghai"),
}


def job_cron(job_id: str) -> tuple:
    """Return ``(crontab, timezone)`` for a scheduled job."""
    if job_id == NEWS_JOB_ID:
        return get_news_crontab(), config.APP_TIMEZONE
    spec = FIXED_JOB_CRONS.get(job_id)
    if not spec:
        return "", config.APP_TIMEZONE
    return spec


def _fixed_trigger(job_id: str) -> CronTrigger:
    expr, tz = job_cron(job_id)
    return validate_crontab(expr, timezone=tz)


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
        trigger=_fixed_trigger("us_after_market"),
        id="us_after_market",
        name="美股盘后分析",
    )

    _scheduler.add_job(
        job_after_market_cn,
        trigger=_fixed_trigger("cn_after_market"),
        id="cn_after_market",
        name="A股盘后分析",
    )

    _scheduler.add_job(
        job_after_market_hk,
        trigger=_fixed_trigger("hk_after_market"),
        id="hk_after_market",
        name="港股盘后分析",
    )

    _scheduler.add_job(
        job_after_market_crypto,
        trigger=_fixed_trigger("crypto_daily"),
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
        trigger=_fixed_trigger("monthly_trade_review"),
        id="monthly_trade_review",
        name="月度总结",
    )

    _scheduler.start()
    logger.info("Scheduler started with 6 jobs.")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    global _scheduler
    if _scheduler:
        if _scheduler.running:
            _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped.")


def get_scheduler_status() -> list[dict]:
    """Return status of all scheduled jobs for the dashboard."""
    if not _scheduler:
        return []
    jobs = []
    for job in _scheduler.get_jobs():
        expr, tz = job_cron(job.id)
        entry = {
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time,
            "crontab": expr,
            "timezone": tz,
        }
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
    """Start one manual run, or acknowledge the existing run of this job.

    True means the request is handled. Repeated clicks from another browser
    cannot start a second manual run while the first is still running.
    """
    func = JOB_FUNCTIONS.get(job_id)
    if not func:
        logger.warning("Unknown job_id for manual trigger: %s", job_id)
        return False

    with _manual_runs_lock:
        if _manual_runs.get(job_id, {}).get("status") == "running":
            return True
        state = {"status": "running", "started_at": None, "error": None}
        _manual_runs[job_id] = state

    def _wrapper():
        from datetime import datetime, timezone

        from common.time import format_display_time

        with _manual_runs_lock:
            state["started_at"] = format_display_time(
                datetime.now(timezone.utc),
                fmt="%Y-%m-%d %H:%M:%S",
            )
        try:
            outcome = func()
            status = (
                outcome.get("status", "completed") if isinstance(outcome, dict) else "completed"
            )
            with _manual_runs_lock:
                state["status"] = status
                if status == "failed":
                    state["error"] = outcome.get("details") or "Unknown error"
        except Exception as exc:
            logger.exception("Manual trigger %s failed", job_id)
            with _manual_runs_lock:
                state.update(status="failed", error=str(exc))

    thread = threading.Thread(target=_wrapper, daemon=True, name=f"manual-{job_id}")
    try:
        thread.start()
    except Exception as exc:
        with _manual_runs_lock:
            state.update(status="failed", error=str(exc))
        logger.exception("Could not start manual job %s", job_id)
    return True


def get_manual_run_status(job_id: str) -> Optional[dict]:
    """Return a snapshot so rendering cannot observe a partially updated state."""
    with _manual_runs_lock:
        state = _manual_runs.get(job_id)
        return dict(state) if state else None


def clear_manual_run_status(job_id: str):
    """Dismiss a finished status; an active run remains protected."""
    with _manual_runs_lock:
        if _manual_runs.get(job_id, {}).get("status") != "running":
            _manual_runs.pop(job_id, None)
