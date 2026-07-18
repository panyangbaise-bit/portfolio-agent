"""Streamlit entry point — initializes DB, adapters, scheduler, and serves pages."""

import sys
import logging
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
from app.styles.theme import inject_cyberpunk_theme

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def init():
    """Initialize all subsystems once at startup."""
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

    send_welcome()


# ── Streamlit App ─────────────────────────────────────────

st.set_page_config(
    page_title="Portfolio Agent",
    page_icon="⚡",
    layout="wide",
)
inject_cyberpunk_theme()

if "initialized" not in st.session_state:
    init()
    st.session_state["initialized"] = True


# Navigation
pages = {
    "📊 Dashboard": "app/pages/dashboard.py",
    "📋 Holdings": "app/pages/holdings.py",
    "📜 History": "app/pages/history.py",
}

st.sidebar.title("Portfolio Agent")
st.sidebar.caption("NEURAL LINK // INVESTMENT OS")

# Use Streamlit's native page navigation
page = st.sidebar.radio("Navigation", list(pages.keys()), label_visibility="collapsed")

page_path = pages[page]
with open(page_path) as f:
    exec(f.read())

import atexit
atexit.register(stop_scheduler)
