"""Integration test: manually trigger all scheduler jobs and verify outcomes.

Usage:
    PYTHONPATH=. python3 tests/test_manual_trigger_all_jobs.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from config import config
from db.repository import get_session, list_job_runs
from scheduler.cron import (
    start_scheduler,
    stop_scheduler,
    trigger_job,
    _manual_runs,
)

ALL_JOBS = [
    ("us_after_market", "美股盘后分析"),
    ("cn_after_market", "A股盘后分析"),
    ("hk_after_market", "港股盘后分析"),
    ("crypto_daily", "Crypto每日分析"),
    ("hourly_news", "新闻轮询"),
    ("monthly_trade_review", "月度交易复盘"),
]

JOB_TIMEOUT = 120  # seconds per job — DeepSeek API can be slow


def wait_for_job(job_id: str, timeout: int = JOB_TIMEOUT) -> dict:
    """Poll _manual_runs until the job finishes or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = _manual_runs.get(job_id)
        if status and status["status"] in ("completed", "failed"):
            return status
        time.sleep(2)
    return {"status": "timeout", "error": f"Timed out after {timeout}s"}


def main():
    print("=" * 60)
    print("Manual Job Trigger — Integration Test")
    print("=" * 60)

    # --- Config check ---
    print(f"\n📱 Telegram:")
    print(f"   Bot token: {'✅ set' if config.TELEGRAM_BOT_TOKEN else '❌ MISSING'}")
    if config.TELEGRAM_CHAT_ID:
        print(f"   Chat ID:   ✅ {config.TELEGRAM_CHAT_ID}")
    else:
        print(f"   Chat ID:   ⚠️  NOT SET — notifications will be logged but not sent")
        print(f"   → To fix: message your bot on Telegram, then set TELEGRAM_CHAT_ID in .env")

    print(f"\n🤖 DeepSeek: {'✅ ' + config.DEEPSEEK_MODEL if config.DEEPSEEK_API_KEY else '❌ MISSING'}")

    # --- Start scheduler ---
    start_scheduler()
    print("\n📋 Scheduler started with 5 jobs.\n")

    # --- Trigger all jobs ---
    print("▶️  Triggering all jobs manually...\n")
    for job_id, job_name in ALL_JOBS:
        ok = trigger_job(job_id)
        icon = "✅" if ok else "❌"
        print(f"   {icon} {job_name} ({job_id})")

    # --- Wait for all jobs ---
    print(f"\n⏳ Waiting for jobs to complete (timeout: {JOB_TIMEOUT}s each)...\n")
    all_ok = True
    for job_id, job_name in ALL_JOBS:
        outcome = wait_for_job(job_id)
        status = outcome["status"]
        if status == "completed":
            print(f"   ✅ {job_name}: completed")
        elif status == "failed":
            print(f"   ❌ {job_name}: FAILED — {outcome.get('error', 'unknown')[:120]}")
            all_ok = False
        elif status == "timeout":
            print(f"   ⏰ {job_name}: TIMEOUT after {JOB_TIMEOUT}s — still running?")
            all_ok = False
        else:
            print(f"   ❓ {job_name}: {status}")

    # --- Verify DB records ---
    print("\n📊 Job run records in DB:\n")
    session = get_session()
    try:
        runs = list_job_runs(session, limit=50)
        # Filter to runs created in the last few minutes
        by_job = {}
        for r in runs:
            if r.job_id not in by_job:
                by_job[r.job_id] = r

        for job_id, job_name in ALL_JOBS:
            r = by_job.get(job_id)
            if r:
                icon = "✅" if r.status == "completed" else "⚠️" if r.status == "skipped" else "❌"
                detail_preview = (r.details or "—")[:100]
                print(f"   {icon} {job_name}: status={r.status} | {detail_preview}")
            else:
                print(f"   ❌ {job_name}: no job_run record!")
                all_ok = False
    finally:
        session.close()

    # --- Summary ---
    print("\n" + "=" * 60)
    if all_ok:
        print("✅ ALL JOBS TRIGGERED AND COMPLETED SUCCESSFULLY")
        telegram_ok = bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)
        if telegram_ok:
            print("✅ Telegram notifications should have been sent")
        else:
            print("⚠️  Telegram chat ID not set — notifications were skipped")
            print("   Set TELEGRAM_CHAT_ID in .env and re-run to test notifications")
    else:
        print("❌ SOME JOBS FAILED — see details above")
    print("=" * 60)

    # --- Cleanup ---
    stop_scheduler()
    return all_ok


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
