"""Scheduler job definitions — what runs when the scheduler fires."""

import logging

from db.repository import get_session, get_all_holdings
from agent.core import (
    run_after_market_analysis,
    run_news_triggered_analysis,
    poll_news_for_portfolio,
)
from notifier.telegram import notify

logger = logging.getLogger(__name__)


def job_after_market_us():
    logger.info("Starting US after-market analysis...")
    try:
        result = run_after_market_analysis("US")
        logger.info(f"US analysis done: {result[:100]}...")
        notify(f"🇺🇸 美股盘后分析\n\n{result}")
    except Exception as e:
        logger.error(f"US analysis failed: {e}")


def job_after_market_cn():
    logger.info("Starting CN after-market analysis...")
    try:
        result = run_after_market_analysis("CN")
        logger.info(f"CN analysis done: {result[:100]}...")
        notify(f"🇨🇳 A股盘后分析\n\n{result}")
    except Exception as e:
        logger.error(f"CN analysis failed: {e}")


def job_after_market_hk():
    logger.info("Starting HK after-market analysis...")
    try:
        result = run_after_market_analysis("HK")
        logger.info(f"HK analysis done: {result[:100]}...")
        notify(f"🇭🇰 港股盘后分析\n\n{result}")
    except Exception as e:
        logger.error(f"HK analysis failed: {e}")


def job_after_market_crypto():
    logger.info("Starting crypto daily analysis...")
    try:
        result = run_after_market_analysis("CRYPTO")
        logger.info(f"Crypto analysis done: {result[:100]}...")
        notify(f"🪙 Crypto每日分析\n\n{result}")
    except Exception as e:
        logger.error(f"Crypto analysis failed: {e}")


def job_hourly_news_poll():
    logger.info("Running hourly news poll...")
    session = get_session()
    try:
        holdings = get_all_holdings(session)
        tickers = [h.ticker for h in holdings]
    finally:
        session.close()

    if not tickers:
        logger.info("No holdings, skipping news poll.")
        return

    try:
        news_items = poll_news_for_portfolio(tickers)
        logger.info(f"Found {len(news_items)} news items for {len(tickers)} tickers")

        if news_items:
            result = run_news_triggered_analysis(news_items)
            if result:
                notify(f"📰 新闻事件分析\n\n{result}")
            else:
                logger.info("No significant news impact detected.")
    except Exception as e:
        logger.error(f"News poll failed: {e}")
