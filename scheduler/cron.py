"""APScheduler configuration — starts and manages all scheduled jobs."""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from scheduler.jobs import (
    job_after_market_us,
    job_after_market_cn,
    job_after_market_hk,
    job_after_market_crypto,
    job_hourly_news_poll,
)

logger = logging.getLogger(__name__)

from typing import Optional

_scheduler: Optional[BackgroundScheduler] = None


def start_scheduler():
    """Start the background scheduler with all jobs configured."""
    global _scheduler

    if _scheduler is not None:
        logger.warning("Scheduler already running.")
        return

    _scheduler = BackgroundScheduler(
        job_defaults={"coalesce": True, "max_instances": 1},
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

    _scheduler.add_job(
        job_hourly_news_poll,
        trigger=CronTrigger(minute=0),
        id="hourly_news",
        name="每小时新闻轮询",
    )

    _scheduler.start()
    logger.info("Scheduler started with 5 jobs.")


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
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else "paused",
        })
    return jobs
