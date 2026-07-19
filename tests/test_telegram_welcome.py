"""Welcome notification is process-once, not per page refresh."""

import notifier.telegram as telegram


def test_send_welcome_only_notifies_once(monkeypatch):
    telegram._welcome_sent = False
    calls = []

    monkeypatch.setattr(telegram, "notify", lambda msg: calls.append(msg))
    monkeypatch.setattr(telegram, "format_display_time", lambda *_a, **_k: "2026-07-19 12:00")

    telegram.send_welcome()
    telegram.send_welcome()
    telegram.send_welcome()

    assert len(calls) == 1
    assert "Portfolio Agent 已启动" in calls[0]
