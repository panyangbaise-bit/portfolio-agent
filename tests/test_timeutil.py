"""Display timezone helpers — UTC stored, Beijing shown by default."""

from datetime import datetime, timezone

from app.timeutil import format_display_time, to_display_tz


def test_naive_utc_converts_to_beijing_plus_eight(monkeypatch):
    monkeypatch.setattr("app.timeutil.config.APP_TIMEZONE", "Asia/Shanghai")
    # 04:00 UTC → 12:00 Beijing
    dt = datetime(2026, 7, 19, 4, 0, 0)
    assert format_display_time(dt) == "2026-07-19 12:00"
    assert to_display_tz(dt).hour == 12


def test_aware_utc_converts_to_beijing(monkeypatch):
    monkeypatch.setattr("app.timeutil.config.APP_TIMEZONE", "Asia/Shanghai")
    dt = datetime(2026, 7, 19, 4, 1, 0, tzinfo=timezone.utc)
    assert format_display_time(dt) == "2026-07-19 12:01"


def test_empty_time_is_em_dash():
    assert format_display_time(None) == "—"
