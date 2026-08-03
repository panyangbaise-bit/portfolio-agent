"""Batch market tools must fetch prices concurrently."""

import time
from types import SimpleNamespace

import agent.tools as tools


def test_get_price_batch_fetches_in_parallel(monkeypatch):
    class FakeAdapter:
        def get_price(self, ticker):
            time.sleep(0.15)
            return {"ticker": ticker, "price": 1.0}

    class FakeRegistry:
        def get(self, market):
            return FakeAdapter()

    monkeypatch.setattr(tools, "adapter_registry", FakeRegistry())

    started = time.perf_counter()
    result = tools.get_price.invoke(
        {
            "ticker": "A,B,C,D",
            "market": "US,US,US,US",
        }
    )
    elapsed = time.perf_counter() - started

    assert result["batch"] is True
    assert set(result["results"]) == {"A", "B", "C", "D"}
    # Sequential would be ~0.60s; parallel should finish near one sleep.
    assert elapsed < 0.40


def test_get_portfolio_fetches_prices_in_parallel(monkeypatch):
    holdings = [
        SimpleNamespace(
            id=i,
            ticker=f"T{i}",
            market="US",
            shares=1.0,
            cost_basis=100.0,
            position_type="core",
        )
        for i in range(4)
    ]

    class FakeSession:
        def close(self):
            return None

    class FakeAdapter:
        def get_price(self, ticker):
            time.sleep(0.15)
            return {"ticker": ticker, "price": 110.0}

    class FakeRegistry:
        def get(self, market):
            return FakeAdapter()

    monkeypatch.setattr(tools, "get_session", lambda: FakeSession())
    monkeypatch.setattr(tools, "get_open_holdings", lambda _s: holdings)
    monkeypatch.setattr(tools, "adapter_registry", FakeRegistry())
    monkeypatch.setattr("app.fx.get_cny_rates", lambda markets: {"US": 7.0})

    started = time.perf_counter()
    result = tools.get_portfolio.invoke({})
    elapsed = time.perf_counter() - started

    assert isinstance(result, list)
    assert len(result) == 4
    assert elapsed < 0.40
