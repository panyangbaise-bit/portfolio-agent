"""Streamlit composition: authenticate, initialize once, then render a view."""

import logging
import sys
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from app.auth import render_account_menu, require_auth
from app.components.ask_agent_chat import render_ask_agent_chat
from app.i18n import t
from app.styles.theme import inject_cyberpunk_theme, inject_locale_toggle
from runtime import start_services

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Stable nav keys so locale switches do not reset the selected page.
NAV_ITEMS = [
    ("dashboard", "app.views.dashboard"),
    ("holdings", "app.views.holdings"),
    ("watchlist", "app.views.watchlist"),
    ("recommendations", "app.views.recommendations"),
    ("jobs", "app.views.operations"),
    ("history", "app.views.history"),
    ("memory", "app.views.memory"),
]


def _sync_locale_from_query():
    """Apply `?locale=en|zh` from the banner toggle into session state."""
    st.session_state.setdefault("locale", "en")
    raw = st.query_params.get("locale")
    if raw in ("en", "zh"):
        st.session_state["locale"] = raw


# ── Streamlit App ─────────────────────────────────────────

st.set_page_config(
    page_title="Portfolio Agent | 投资组合助手",
    page_icon=str(Path(__file__).parent / "styles" / "favicon.svg"),
    layout="wide",
)
inject_cyberpunk_theme()

_sync_locale_from_query()
inject_locale_toggle(st.session_state["locale"])

# Authenticate before initializing app subsystems or rendering private pages.
require_auth()
start_services()

st.sidebar.markdown('<div class="pa-brand-mark">P<span> / </span>A</div>', unsafe_allow_html=True)
st.sidebar.title(t("app.title"))
st.sidebar.caption(t("app.tagline"))
render_account_menu()
st.sidebar.divider()

# Views live in app/views/ (NOT app/pages/) so Streamlit won't auto-add multipage tabs.
memory_link = st.query_params.get("memory")
if memory_link and st.session_state.get("opened_memory_link") != memory_link:
    st.session_state["nav_page"] = "memory"
    st.session_state["opened_memory_link"] = memory_link
page_key = st.sidebar.radio(
    "Navigation",
    options=[key for key, _ in NAV_ITEMS],
    format_func=lambda key: t("nav." + key),
    key="nav_page",
    label_visibility="collapsed",
)

page_module = import_module(dict(NAV_ITEMS)[page_key])
page_module.render()

# Own nested vertical block so dock JS can target Ask Agent without the page.
with st.container():
    render_ask_agent_chat()
