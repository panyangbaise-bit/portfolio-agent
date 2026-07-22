from app.i18n import translate


def test_translate_returns_requested_locale_and_formats_values():
    assert translate("zh", "dashboard.title") == "投资组合仪表盘"
    assert translate("en", "holdings.add.success", ticker="QQQ", shares=2, cost=100) == (
        "Added QQQ — 2 shares at 100"
    )


def test_translate_falls_back_to_english_for_unknown_locale():
    assert translate("unknown", "nav.dashboard") == "📊 Dashboard"


def test_watchlist_strings_are_localized():
    """EN watchlist copy must be English; ZH must be Chinese (not shared EN leak)."""
    en_title = translate("en", "watchlist.title")
    zh_title = translate("zh", "watchlist.title")
    assert en_title == "Watchlist"
    assert "监察" not in en_title
    assert zh_title == "监察表"

    assert translate("en", "watchlist.action.edit") == "✏️ Edit"
    assert translate("zh", "watchlist.action.edit") == "✏️ 编辑"
    assert translate("en", "watchlist.col.reason") == "Reason"
    assert translate("zh", "watchlist.col.reason") == "关注理由"


def test_locale_toggle_css_enables_pointer_events():
    """Locale button must opt into clicks when Streamlit header is pointer-events:none."""
    from app.styles.theme import load_cyberpunk_css

    css = load_cyberpunk_css()
    assert "button.pa-locale-toggle" in css
    assert "pointer-events: auto" in css
