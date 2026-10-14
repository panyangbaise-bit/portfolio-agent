"""Scheduler job definitions — what runs when the scheduler fires."""

import logging

from db.repository import (
    create_job_run,
    finish_job_run,
    get_open_holdings,
    get_session,
)
from agent.core import (
    run_after_market_analysis,
    run_news_triggered_analysis,
    run_trade_review_analysis,
    poll_news_for_portfolio,
)
from notifier.telegram import notify
from scheduler.triggers import is_trading_day

from memory.context import current_run_id

logger = logging.getLogger(__name__)


def _start_job_run(job_id: str, job_name: str) -> int:
    session = get_session()
    try:
        run_id = create_job_run(session, job_id, job_name).id
        current_run_id.set(run_id)
        return run_id
    finally:
        session.close()


def _finish_job_run(run_id: int, status: str, details: str = None):
    session = get_session()
    try:
        finish_job_run(session, run_id, status, details)
        return {"status": status, "details": details}
    finally:
        current_run_id.set(None)
        session.close()


def job_after_market_us():
    run_id = _start_job_run("us_after_market", "美股盘后分析")
    if not is_trading_day("US"):
        logger.info("US market closed (weekend), skipping analysis.")
        return _finish_job_run(run_id, "skipped", "Non-trading day (weekend).")
    logger.info("Starting US after-market analysis...")
    try:
        result = run_after_market_analysis("US")
        logger.info(f"US analysis done: {result[:100]}...")
        notify(f"🇺🇸 美股盘后分析\n\n{result}")
        return _finish_job_run(run_id, "completed", result)
    except Exception as e:
        logger.error(f"US analysis failed: {e}")
        return _finish_job_run(run_id, "failed", str(e))


def job_after_market_cn():
    run_id = _start_job_run("cn_after_market", "A股盘后分析")
    if not is_trading_day("CN"):
        logger.info("CN market closed (weekend), skipping analysis.")
        return _finish_job_run(run_id, "skipped", "Non-trading day (weekend).")
    logger.info("Starting CN after-market analysis...")
    try:
        result = run_after_market_analysis("CN")
        logger.info(f"CN analysis done: {result[:100]}...")
        notify(f"🇨🇳 A股盘后分析\n\n{result}")
        return _finish_job_run(run_id, "completed", result)
    except Exception as e:
        logger.error(f"CN analysis failed: {e}")
        return _finish_job_run(run_id, "failed", str(e))


def job_after_market_hk():
    run_id = _start_job_run("hk_after_market", "港股盘后分析")
    if not is_trading_day("HK"):
        logger.info("HK market closed (weekend), skipping analysis.")
        return _finish_job_run(run_id, "skipped", "Non-trading day (weekend).")
    logger.info("Starting HK after-market analysis...")
    try:
        result = run_after_market_analysis("HK")
        logger.info(f"HK analysis done: {result[:100]}...")
        notify(f"🇭🇰 港股盘后分析\n\n{result}")
        return _finish_job_run(run_id, "completed", result)
    except Exception as e:
        logger.error(f"HK analysis failed: {e}")
        return _finish_job_run(run_id, "failed", str(e))


def job_after_market_crypto():
    run_id = _start_job_run("crypto_daily", "Crypto每日分析")
    # Crypto market operates 24/7 — no weekend skip
    logger.info("Starting crypto daily analysis...")
    try:
        result = run_after_market_analysis("CRYPTO")
        logger.info(f"Crypto analysis done: {result[:100]}...")
        notify(f"🪙 Crypto每日分析\n\n{result}")
        return _finish_job_run(run_id, "completed", result)
    except Exception as e:
        logger.error(f"Crypto analysis failed: {e}")
        return _finish_job_run(run_id, "failed", str(e))


def job_hourly_news_poll():
    run_id = _start_job_run("hourly_news", "新闻轮询")
    logger.info("Running news poll...")
    session = get_session()
    try:
        holdings = get_open_holdings(session)
        tickers = [h.ticker for h in holdings]
    finally:
        session.close()

    if not tickers:
        logger.info("No holdings, skipping news poll.")
        return _finish_job_run(run_id, "skipped", "No holdings to monitor.")

    try:
        news_items = poll_news_for_portfolio(tickers)
        headlines = sum(1 for n in news_items if n.get("category") == "headline")
        ticker_news = len(news_items) - headlines
        logger.info(
            f"Found {len(news_items)} news items "
            f"({ticker_news} ticker-related, {headlines} headlines) "
            f"for {len(tickers)} tickers"
        )

        if news_items:
            result = run_news_triggered_analysis(news_items)
            if result:
                notify(f"📰 新闻事件分析\n\n{result}")
                return _finish_job_run(run_id, "completed", result)
            else:
                logger.info("No significant news impact detected.")
                return _finish_job_run(run_id, "skipped", "No significant news impact.")
        else:
            return _finish_job_run(
                run_id,
                "skipped",
                "No ticker news or headlines found.",
            )
    except Exception as e:
        logger.error(f"News poll failed: {e}")
        return _finish_job_run(run_id, "failed", str(e))


def job_monthly_trade_review():
    run_id = _start_job_run("monthly_trade_review", "月度总结")
    logger.info("Starting monthly summary...")
    try:
        result = run_trade_review_analysis(days=31)
        if result:
            logger.info(f"Monthly summary done: {result[:100]}...")
            notify(f"📒 月度总结\n\n{result}")
            return _finish_job_run(run_id, "completed", result)
        else:
            logger.info("No holdings or trades; skipping monthly summary.")
            return _finish_job_run(run_id, "skipped", "No holdings or trades to summarize.")
    except Exception as e:
        logger.error(f"Monthly summary failed: {e}")
        return _finish_job_run(run_id, "failed", str(e))
