from app.styles.theme import (
    load_cyberpunk_css,
    build_theme_css,
    build_theme_html,
    build_locale_toggle_html,
)


def test_load_cyberpunk_css_returns_nonempty_when_file_exists(tmp_path, monkeypatch):
    css_file = tmp_path / "cyberpunk.css"
    css_file.write_text(":root { --cp-cyan: #00f0ff; }", encoding="utf-8")
    monkeypatch.setattr("app.styles.theme.CSS_PATH", css_file)
    assert "--cp-cyan" in load_cyberpunk_css()


def test_load_cyberpunk_css_returns_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("app.styles.theme.CSS_PATH", tmp_path / "missing.css")
    assert load_cyberpunk_css() == ""


def test_build_theme_css_includes_fonts_and_host_hide():
    css = build_theme_css(":root{--cp-bg:#05050a;}")
    assert "--cp-bg" in css
    assert "fonts.googleapis.com" in css
    assert "Orbitron" in css
    assert "stElementContainer" in css


def test_build_theme_html_wraps_style():
    html = build_theme_html(":root{--cp-bg:#05050a;}")
    assert html.startswith("<style>")
    assert html.rstrip().endswith("</style>")


def test_mobile_sidebar_layout_only_applies_when_expanded():
    """A collapsed sidebar must not retain the full-width drawer geometry."""
    css = load_cyberpunk_css()
    expanded_selector = 'section[data-testid="stSidebar"][aria-expanded="true"]'

    assert expanded_selector in css
    mobile_sidebar_start = css.index("/* Mobile sidebar drawer")
    mobile_sidebar_end = css.index("/* EN/CN toggle", mobile_sidebar_start)
    mobile_sidebar_css = css[mobile_sidebar_start:mobile_sidebar_end]
    assert '[data-testid="stSidebar"] {' not in mobile_sidebar_css


def test_chrome_hide_rules_keep_header_toolbar_visible():
    """stToolbar hosts stExpandSidebarButton (reopens a collapsed sidebar).

    Mobile auto-collapses the sidebar, so hiding the whole toolbar removes
    the only way to open navigation. Hide Deploy + main menu individually.
    """
    css = load_cyberpunk_css()
    assert 'div[data-testid="stToolbar"]' not in css
    assert '[data-testid="stAppDeployButton"]' in css
    assert '[data-testid="stMainMenu"]' in css


def test_locale_toggle_is_parent_anchor_not_iframe_navigation():
    """Component iframes are sandboxed without allow-top-navigation, so
    script-driven navigation throws SecurityError. The toggle must be a
    plain <a href> living in the parent document."""
    html = build_locale_toggle_html("en")
    assert 'createElement("a")' in html
    assert "location.assign" not in html
    assert "location.href =" not in html
    assert '"zh"' in html  # next locale baked into the href

    html_zh = build_locale_toggle_html("zh")
    assert '"en"' in html_zh
