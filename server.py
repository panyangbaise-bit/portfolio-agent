#!/usr/bin/env python3
"""Portfolio Agent entry point — bootstrap services then launch Streamlit.

Previously bootstrap ran inside app/main.py which only executes on first
browser page load (Streamlit's Uvicorn starts but defers script execution).
This entry point runs all init before Streamlit so the scheduler and welcome
notification fire immediately on service start.
"""

import sys
import logging
import atexit
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("server")

# ── Bootstrap (runs before Streamlit) ──

from db.repository import init_db, engine
from db.migrate import migrate
from adapters.base import registry
from adapters.us_market import USMarketAdapter
from adapters.cn_market import CNMarketAdapter, HKMarketAdapter
from adapters.crypto import CryptoAdapter
from scheduler.cron import start_scheduler
from notifier.telegram import (
    send_welcome,
    start_callback_poller,
    stop_callback_poller,
)

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
start_callback_poller()
logger.info("Bootstrap complete. Launching Streamlit...")
atexit.register(stop_callback_poller)

# ── Launch Streamlit in the same process ──

import streamlit.web.cli as stcli

if __name__ == "__main__":
    sys.argv = [
        "streamlit", "run", "app/main.py",
        "--server.port", "8501",
        "--server.address", "0.0.0.0",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    stcli.main()
