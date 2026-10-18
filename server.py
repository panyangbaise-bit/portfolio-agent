#!/usr/bin/env python3
"""Production entry point: initialize services before the first page request."""

import logging
import sys
from pathlib import Path


def main() -> None:
    from streamlit.web import cli

    from runtime import start_services, stop_services

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    start_services(include_api=True)
    try:
        sys.argv = [
            "streamlit",
            "run",
            str(Path(__file__).parent / "app/main.py"),
            "--server.port",
            "8501",
            "--server.address",
            "0.0.0.0",
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ]
        cli.main()
    finally:
        stop_services()


if __name__ == "__main__":
    main()
