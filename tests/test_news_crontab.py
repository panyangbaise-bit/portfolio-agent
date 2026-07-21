"""News poll crontab persistence and validation."""

import pytest
from apscheduler.triggers.cron import CronTrigger

from scheduler.settings import (
    get_news_crontab,
    set_news_crontab,
    validate_crontab,
)


def test_default_news_crontab(monkeypatch, tmp_path):
    monkeypatch.setattr("scheduler.settings.SETTINGS_PATH", tmp_path / "scheduler_settings.json")
    monkeypatch.setattr(
        "scheduler.settings.config.DEFAULT_NEWS_CRONTAB",
        "0 8-22/2 * * *",
    )
    assert get_news_crontab() == "0 8-22/2 * * *"


def test_set_and_get_news_crontab(monkeypatch, tmp_path):
    monkeypatch.setattr("scheduler.settings.SETTINGS_PATH", tmp_path / "scheduler_settings.json")
    cleaned = set_news_crontab("0 9-21/2 * * *")
    assert cleaned == "0 9-21/2 * * *"
    assert get_news_crontab() == "0 9-21/2 * * *"


def test_validate_crontab_rejects_bad_expr():
    with pytest.raises(ValueError):
        validate_crontab("not a cron")
    with pytest.raises(ValueError):
        validate_crontab("0 * * *")  # only 4 fields


def test_validate_crontab_accepts_default():
    trigger = validate_crontab("0 8-22/2 * * *", timezone="Asia/Shanghai")
    assert isinstance(trigger, CronTrigger)
