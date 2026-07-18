from app.i18n import translate


def test_translate_returns_requested_locale_and_formats_values():
    assert translate("zh", "dashboard.title") == "投资组合仪表盘"
    assert translate("en", "holdings.add.success", ticker="QQQ", shares=2, cost=100) == (
        "Added QQQ — 2 shares at 100"
    )


def test_translate_falls_back_to_english_for_unknown_locale():
    assert translate("unknown", "nav.dashboard") == "📊 Dashboard"
