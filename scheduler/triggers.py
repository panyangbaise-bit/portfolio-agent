"""Market trading calendar and timezone-aware trigger logic."""

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from config import config


def is_market_closed(market: str) -> bool:
    """Check if market just closed (within last 30 minutes)."""
    if market == "CRYPTO":
        current = datetime.now(ZoneInfo("Asia/Shanghai"))
        return current.hour == 21 and current.minute < 30

    market_info = config.TRADING_MARKETS.get(market)
    if not market_info:
        return False

    tz = ZoneInfo(market_info["timezone"])
    now = datetime.now(tz)

    if now.weekday() >= 5:
        return False

    close_hour = market_info["close_hour"]
    close_minute = market_info["close_minute"]

    return (
        now.hour == close_hour
        and close_minute <= now.minute < close_minute + 30
    )


def get_next_market_close(market: str) -> Optional[datetime]:
    """Calculate the next market close time in local time."""
    if market == "CRYPTO":
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        target = now.replace(hour=21, minute=0, second=0, microsecond=0)
        if now >= target:
            target = target + timedelta(days=1)
        return target

    market_info = config.TRADING_MARKETS.get(market)
    if not market_info:
        return None

    tz = ZoneInfo(market_info["timezone"])
    now = datetime.now(tz)

    close = now.replace(
        hour=market_info["close_hour"],
        minute=market_info["close_minute"],
        second=0, microsecond=0,
    )

    if now >= close:
        close = close + timedelta(days=1)

    while close.weekday() >= 5:
        close = close + timedelta(days=1)

    return close


def is_trading_day(market: str) -> bool:
    """Check if today is a trading day for the given market."""
    if market == "CRYPTO":
        return True
    market_info = config.TRADING_MARKETS.get(market)
    if not market_info:
        return True
    tz = ZoneInfo(market_info["timezone"])
    now = datetime.now(tz)
    return now.weekday() < 5
