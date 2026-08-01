from types import SimpleNamespace

import notifier.telegram as telegram


def test_send_recommendation_adds_accept_and_dismiss_inline_buttons(monkeypatch):
    sent = []
    recommendation = SimpleNamespace(
        id=42,
        ticker="AAPL",
        action="buy_add",
        urgency="high",
        confidence=0.8,
        reasoning="Earnings momentum remains strong.",
    )

    monkeypatch.setattr(telegram, "_is_configured", lambda: True)
    monkeypatch.setattr(
        telegram,
        "_send_message",
        lambda text, reply_markup=None: sent.append((text, reply_markup)),
    )

    telegram.send_recommendation(recommendation)

    assert "AAPL" in sent[0][0]
    assert sent[0][1]["inline_keyboard"] == [[
        {"text": "✅ Accept", "callback_data": "rec:42:accept"},
        {"text": "❌ Dismiss", "callback_data": "rec:42:dismiss"},
    ]]


def test_callback_poller_applies_authorized_recommendation_action(monkeypatch):
    answers = []
    actions = []
    poller = telegram.TelegramCallbackPoller()

    monkeypatch.setattr(telegram.config, "TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(telegram, "get_session", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(
        telegram,
        "apply_recommendation_action",
        lambda _db, rec_id, action: actions.append((rec_id, action)) or {"status": "applied"},
    )
    monkeypatch.setattr(
        poller,
        "_answer_callback",
        lambda callback_id, text, show_alert=False: answers.append((callback_id, text, show_alert)),
    )

    poller.process_update({
        "callback_query": {
            "id": "callback-1",
            "data": "rec:42:accept",
            "message": {"chat": {"id": 123}},
        },
    })

    assert actions == [(42, "accept")]
    assert answers == [("callback-1", "Recommendation accepted.", False)]


def test_callback_poller_rejects_callbacks_from_other_chats(monkeypatch):
    answers = []
    poller = telegram.TelegramCallbackPoller()

    monkeypatch.setattr(telegram.config, "TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(
        poller,
        "_answer_callback",
        lambda callback_id, text, show_alert=False: answers.append((callback_id, text, show_alert)),
    )

    poller.process_update({
        "callback_query": {
            "id": "callback-2",
            "data": "rec:42:dismiss",
            "message": {"chat": {"id": 999}},
        },
    })

    assert answers == [("callback-2", "Unauthorized callback.", True)]
