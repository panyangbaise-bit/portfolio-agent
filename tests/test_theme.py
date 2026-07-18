from app.styles.theme import load_cyberpunk_css, build_theme_css, build_theme_html


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
