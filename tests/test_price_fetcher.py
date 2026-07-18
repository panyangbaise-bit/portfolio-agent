import time
from types import SimpleNamespace

from app.components import price_fetcher


def test_batch_price_fetch_returns_within_deadline(monkeypatch):
    """A slow provider must not block the dashboard's first render."""
    holdings = [
        SimpleNamespace(ticker="SLOW", market="US"),
        SimpleNamespace(ticker="FAST", market="US"),
    ]

    def get_price(ticker, market):
        if ticker == "SLOW":
            time.sleep(0.2)
        return 100.0

    monkeypatch.setattr(price_fetcher, "_cached_price", get_price)

    started = time.perf_counter()
    prices = price_fetcher.fetch_prices_batch(holdings, timeout_seconds=0.05)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.15
    assert prices[("US", "FAST")] == 100.0
    assert prices[("US", "SLOW")] is None
