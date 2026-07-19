"""Scheduler job definitions — what runs when the scheduler fires."""

import logging

from db.repository import (
    create_job_run,
    finish_job_run,
    get_all_holdings,
    get_session,
)
from agent.core import (
    run_after_market_analysis,
    run_news_triggered_analysis,
    poll_news_for_portfolio,
)
from notifier.telegram import notify

logger = logging.getLogger(__name__)


def _start_job_run(job_id: str, job_name: str) -> int:
    session = get_session()
    try:
        return create_job_run(session, job_id, job_name).id
    finally:
        session.close()


def _finish_job_run(run_id: int, status: str, details: str = None):
    session = get_session()
    try:
        finish_job_run(session, run_id, status, details)
    finally:
        session.close()


def job_after_market_us():
    run_id = _start_job_run("us_after_market", "美股盘后分析")
    logger.info("Starting US after-market analysis...")
    try:
        result = run_after_market_analysis("US")
        logger.info(f"US analysis done: {result[:100]}...")
        notify(f"🇺🇸 美股盘后分析\n\n{result}")
        _finish_job_run(run_id, "completed", result[:500])
    except Exception as e:
        logger.error(f"US analysis failed: {e}")
        _finish_job_run(run_id, "failed", str(e))


def job_after_market_cn():
    run_id = _start_job_run("cn_after_market", "A股盘后分析")
    logger.info("Starting CN after-market analysis...")
    try:
        result = run_after_market_analysis("CN")
        logger.info(f"CN analysis done: {result[:100]}...")
        notify(f"🇨🇳 A股盘后分析\n\n{result}")
        _finish_job_run(run_id, "completed", result[:500])
    except Exception as e:
        logger.error(f"CN analysis failed: {e}")
        _finish_job_run(run_id, "failed", str(e))


def job_after_market_hk():
    run_id = _start_job_run("hk_after_market", "港股盘后分析")
    logger.info("Starting HK after-market analysis...")
    try:
        result = run_after_market_analysis("HK")
        logger.info(f"HK analysis done: {result[:100]}...")
        notify(f"🇭🇰 港股盘后分析\n\n{result}")
        _finish_job_run(run_id, "completed", result[:500])
    except Exception as e:
        logger.error(f"HK analysis failed: {e}")
        _finish_job_run(run_id, "failed", str(e))


def job_after_market_crypto():
    run_id = _start_job_run("crypto_daily", "Crypto每日分析")
    logger.info("Starting crypto daily analysis...")
    try:
        result = run_after_market_analysis("CRYPTO")
        logger.info(f"Crypto analysis done: {result[:100]}...")
        notify(f"🪙 Crypto每日分析\n\n{result}")
        _finish_job_run(run_id, "completed", result[:500])
    except Exception as e:
        logger.error(f"Crypto analysis failed: {e}")
        _finish_job_run(run_id, "failed", str(e))


def job_hourly_news_poll():
    run_id = _start_job_run("hourly_news", "每小时新闻轮询")
    logger.info("Running hourly news poll...")
    session = get_session()
    try:
        holdings = get_all_holdings(session)
        tickers = [h.ticker for h in holdings]
    finally:
        session.close()

    if not tickers:
        logger.info("No holdings, skipping news poll.")
        _finish_job_run(run_id, "skipped", "No holdings to monitor.")
        return

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
                _finish_job_run(run_id, "completed", result[:500])
            else:
                logger.info("No significant news impact detected.")
                _finish_job_run(run_id, "skipped", "No significant news impact.")
        else:
            _finish_job_run(
                run_id,
                "skipped",
                "No ticker news or headlines found.",
            )
    except Exception as e:
        logger.error(f"News poll failed: {e}")
        _finish_job_run(run_id, "failed", str(e))
