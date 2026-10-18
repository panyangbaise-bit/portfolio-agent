"""Run only the external API; no scheduler, UI or Telegram startup."""

import logging
import signal
import threading


def main():
    from a2a.server import start_a2a_server, stop_a2a_server
    from runtime import initialize_infrastructure

    logging.basicConfig(level=logging.INFO)
    initialize_infrastructure()
    server = start_a2a_server()
    if server is None:
        raise SystemExit("Enable A2A_ENABLED or ACTIONS_ENABLED in .env first")
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    try:
        stop.wait()
    finally:
        stop_a2a_server()


if __name__ == "__main__":
    main()
