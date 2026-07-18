"""Telegram Bot notification sender."""

import logging
from datetime import datetime

from config import config

logger = logging.getLogger(__name__)

_initialized = bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def notify(message: str):
    """Send a Telegram notification. No-op if Telegram is not configured."""
    if not _initialized:
        logger.debug("Telegram not configured, skipping notification.")
        return

    try:
        import requests

        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(f"Telegram send failed: {resp.status_code} {resp.text}")
        else:
            logger.info("Telegram notification sent.")
    except Exception as e:
        logger.error(f"Telegram notification error: {e}")


def send_welcome():
    """Send a startup notification."""
    notify(f"🤖 <b>Portfolio Agent 已启动</b>\n<code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>")


def send_urgent_recommendation(ticker: str, action: str, reasoning: str, confidence: float):
    """Send a high-urgency recommendation as a formatted Telegram message."""
    action_emoji = {"buy_add": "🟢", "reduce": "🔴", "hold": "🟡", "watch": "👀"}
    emoji = action_emoji.get(action, "ℹ️")

    msg = (
        f"{emoji} <b>建议操作</b>\n\n"
        f"<b>标的：</b>{ticker}\n"
        f"<b>建议：</b>{action}\n"
        f"<b>置信度：</b>{confidence:.0%}\n\n"
        f"<b>理由：</b>\n{reasoning}"
    )
    notify(msg)
