"""Streamlit entry point — initializes DB, adapters, scheduler, and serves pages."""

import sys
import logging
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from db.repository import init_db, engine
from db.migrate import migrate
from adapters.base import registry
from adapters.us_market import USMarketAdapter
from adapters.cn_market import CNMarketAdapter, HKMarketAdapter
from adapters.crypto import CryptoAdapter
from scheduler.cron import start_scheduler, stop_scheduler
from notifier.telegram import send_welcome
from app.auth import require_auth
from app.i18n import t
from app.styles.theme import inject_cyberpunk_theme, inject_locale_toggle

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Process-lifetime bootstrap (survives Streamlit page refresh / new browser sessions).
_PROCESS_BOOTSTRAPPED = False
_PROCESS_LOCK = threading.Lock()

# Stable nav keys so locale switches do not reset the selected page.
NAV_ITEMS = [
    ("dashboard", "app/views/dashboard.py"),
    ("holdings", "app/views/holdings.py"),
    ("watchlist", "app/views/watchlist.py"),
    ("recommendations", "app/views/recommendations.py"),
    ("jobs", "app/views/jobs.py"),
    ("history", "app/views/history.py"),
]


def init():
    """Initialize subsystems once per server process (not per page refresh)."""
    global _PROCESS_BOOTSTRAPPED
    with _PROCESS_LOCK:
        if _PROCESS_BOOTSTRAPPED:
            return

        init_db()
        migrate(engine)
        logger.info("Database initialized and migrated.")

        registry.register("US", USMarketAdapter())
        registry.register("CN", CNMarketAdapter())
        registry.register("HK", HKMarketAdapter())
        registry.register("CRYPTO", CryptoAdapter())
        logger.info(f"Adapters registered: {registry.markets}")

        start_scheduler()
        logger.info("Scheduler started.")

        # True process startup only — guarded again inside send_welcome().
        send_welcome()
        _PROCESS_BOOTSTRAPPED = True
        logger.info("Process bootstrap complete.")


def _sync_locale_from_query():
    """Apply `?locale=en|zh` from the banner toggle into session state."""
    st.session_state.setdefault("locale", "en")
    raw = st.query_params.get("locale")
    if raw in ("en", "zh"):
        st.session_state["locale"] = raw


# ── Streamlit App ─────────────────────────────────────────

st.set_page_config(
    page_title="Portfolio Agent | 投资组合助手",
    page_icon="⚡",
    layout="wide",
)
inject_cyberpunk_theme()

# Always call init(); process lock makes it a no-op after first real start.
init()

_sync_locale_from_query()
inject_locale_toggle(st.session_state["locale"])

# Optional password gate before any app UI (toggle via AUTH_ENABLED).
require_auth()

st.sidebar.title(t("app.title"))

# Views live in app/views/ (NOT app/pages/) so Streamlit won't auto-add multipage tabs.
page_key = st.sidebar.radio(
    "Navigation",
    options=[key for key, _ in NAV_ITEMS],
    format_func=lambda key: t("nav." + key),
    key="nav_page",
    label_visibility="collapsed",
)

page_path = dict(NAV_ITEMS)[page_key]
with open(page_path) as f:
    exec(f.read())

import atexit
atexit.register(stop_scheduler)
