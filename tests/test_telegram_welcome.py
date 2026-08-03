"""Welcome notification is process-once, not per page refresh."""

import notifier.telegram as telegram


def test_send_welcome_only_notifies_once(monkeypatch):
    telegram._welcome_sent = False
    calls = []

    def fake_notify(msg):
        calls.append(msg)
        return True

    monkeypatch.setattr(telegram, "notify", fake_notify)
    monkeypatch.setattr(telegram, "format_display_time", lambda *_a, **_k: "2026-07-19 12:00")

    assert telegram.send_welcome() is True
    assert telegram.send_welcome() is True
    assert telegram.send_welcome() is True

    assert len(calls) == 1
    assert "Portfolio Agent 已启动" in calls[0]


def test_send_welcome_retries_after_failed_notify(monkeypatch):
    telegram._welcome_sent = False
    calls = []
    results = [False, True]

    def fake_notify(msg):
        calls.append(msg)
        return results.pop(0)

    monkeypatch.setattr(telegram, "notify", fake_notify)
    monkeypatch.setattr(telegram, "format_display_time", lambda *_a, **_k: "2026-07-19 12:00")

    assert telegram.send_welcome() is False
    assert telegram._welcome_sent is False
    assert telegram.send_welcome() is True
    assert telegram._welcome_sent is True
    assert len(calls) == 2
