"""Run only the external API; no scheduler, UI or Telegram startup."""

import logging
import signal
import threading


def main():
    from adapters.base import registry
    from adapters.us_market import USMarketAdapter
    from adapters.cn_market import CNMarketAdapter, HKMarketAdapter
    from adapters.crypto import CryptoAdapter
    from db.repository import init_db, engine
    from db.migrate import migrate
    from a2a.server import start_a2a_server

    logging.basicConfig(level=logging.INFO)
    init_db()
    migrate(engine)
    for market, adapter in (("US", USMarketAdapter()), ("CN", CNMarketAdapter()),
                            ("HK", HKMarketAdapter()), ("CRYPTO", CryptoAdapter())):
        registry.register(market, adapter)
    server = start_a2a_server()
    if server is None:
        raise SystemExit("Enable A2A_ENABLED or ACTIONS_ENABLED in .env first")
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    stop.wait()
    server.shutdown()
    server.server_close()


if __name__ == "__main__":
    main()
