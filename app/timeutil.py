"""Display-time helpers — DB stores UTC; UI shows configured local timezone."""

from datetime import datetime, timezone
from typing import Optional, Union
from zoneinfo import ZoneInfo

from config import config


def app_zone() -> ZoneInfo:
    return ZoneInfo(config.APP_TIMEZONE)


def to_display_tz(dt: datetime) -> datetime:
    """Interpret naive datetimes as UTC, then convert to APP_TIMEZONE."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(app_zone())


def format_display_time(
    dt: Optional[Union[datetime, str]],
    fmt: str = "%Y-%m-%d %H:%M",
) -> str:
    """Format a UTC (or naive-UTC) timestamp for UI display."""
    if not dt:
        return "—"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return str(dt)[:16]
    return to_display_tz(dt).strftime(fmt)


def format_now_for_agent() -> str:
    """Wall-clock block appended to the agent system prompt."""
    now = datetime.now(app_zone())
    stamp = now.strftime("%Y-%m-%d %H:%M")
    return f"## 当前时间\n{stamp} ({config.APP_TIMEZONE})"
