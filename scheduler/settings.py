"""Persisted scheduler settings (editable from the Jobs page)."""

import json
import logging
from pathlib import Path
from typing import Any, Optional

from apscheduler.triggers.cron import CronTrigger

from config import PROJECT_ROOT, config

logger = logging.getLogger(__name__)

SETTINGS_PATH = PROJECT_ROOT / "data" / "scheduler_settings.json"
NEWS_CRONTAB_KEY = "news_crontab"


def _ensure_parent() -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_raw() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to read %s: %s", SETTINGS_PATH, e)
        return {}


def _save_raw(data: dict) -> None:
    _ensure_parent()
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(SETTINGS_PATH)


def validate_crontab(expr: str, timezone: Optional[str] = None) -> CronTrigger:
    """Parse a 5-field crontab; raises ValueError on invalid syntax."""
    cleaned = (expr or "").strip()
    if not cleaned:
        raise ValueError("crontab is empty")
    parts = cleaned.split()
    if len(parts) != 5:
        raise ValueError("crontab must have 5 fields: minute hour day month day_of_week")
    tz = timezone or config.APP_TIMEZONE
    try:
        return CronTrigger.from_crontab(cleaned, timezone=tz)
    except Exception as e:
        raise ValueError(f"invalid crontab: {e}") from e


def get_news_crontab() -> str:
    """Return persisted news crontab, or the configured default."""
    raw = _load_raw().get(NEWS_CRONTAB_KEY)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return config.DEFAULT_NEWS_CRONTAB


def set_news_crontab(expr: str) -> str:
    """Validate and persist news crontab. Returns the cleaned expression."""
    cleaned = expr.strip()
    validate_crontab(cleaned)
    data = _load_raw()
    data[NEWS_CRONTAB_KEY] = cleaned
    _save_raw(data)
    return cleaned


def get_setting(key: str, default: Any = None) -> Any:
    return _load_raw().get(key, default)
