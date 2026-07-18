"""Cyberpunk theme loader for Streamlit."""

from pathlib import Path

CSS_PATH = Path(__file__).parent / "cyberpunk.css"

FONT_LINK = (
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Orbitron:wght@500;700&family=Share+Tech+Mono&display=swap" '
    'rel="stylesheet">'
)


def load_cyberpunk_css():
    # type: () -> str
    if not CSS_PATH.is_file():
        return ""
    return CSS_PATH.read_text(encoding="utf-8")


def build_theme_markdown(css):
    # type: (str) -> str
    return FONT_LINK + "<style>" + css + "</style>"


def inject_cyberpunk_theme():
    # type: () -> None
    import logging

    import streamlit as st

    css = load_cyberpunk_css()
    if not css:
        logging.getLogger(__name__).warning("cyberpunk.css missing; theme skipped")
        return
    st.markdown(build_theme_markdown(css), unsafe_allow_html=True)
