"""get_portfolio weight_pct must use CNY-converted market values."""

from types import SimpleNamespace

import agent.tools as tools


def test_get_portfolio_weights_use_cny_not_native_sum(monkeypatch):
    holdings = [
        SimpleNamespace(
            id=1,
            ticker="020357",
            market="CN",
            shares=4881.03,
            cost_basis=4.0975,
            position_type="core",
        ),
        SimpleNamespace(
            id=2,
            ticker="QQQ",
            market="US",
            shares=7.0,
            cost_basis=660.27,
            position_type="core",
        ),
    ]

    class FakeSession:
        def close(self):
            return None

    class FakeAdapter:
        def __init__(self, price):
            self.price = price

        def get_price(self, ticker):
            return {"ticker": ticker, "price": self.price, "currency": "CNY"}

    class FakeRegistry:
        def get(self, market):
            if market == "CN":
                return FakeAdapter(3.1935)
            return FakeAdapter(687.99)

    monkeypatch.setattr(tools, "get_session", lambda: FakeSession())
    monkeypatch.setattr(tools, "get_open_holdings", lambda _s: holdings)
    monkeypatch.setattr(tools, "adapter_registry", FakeRegistry())
    monkeypatch.setattr(
        "app.fx.get_cny_rates",
        lambda markets: {"CN": 1.0, "US": 7.2},
    )

    result = tools.get_portfolio.invoke({})
    assert isinstance(result, list)
    by_ticker = {row["ticker"]: row for row in result}

    cn_mv_cny = 4881.03 * 3.1935 * 1.0
    us_mv_cny = 7.0 * 687.99 * 7.2
    total = cn_mv_cny + us_mv_cny
    expected_cn_weight = round(cn_mv_cny / total * 100, 2)
    expected_us_weight = round(us_mv_cny / total * 100, 2)

    assert by_ticker["020357"]["weight_pct"] == expected_cn_weight
    assert by_ticker["QQQ"]["weight_pct"] == expected_us_weight
    # Without FX, CN would dominate (~67%); with FX it should be well below 50%.
    assert by_ticker["020357"]["weight_pct"] < 40
    assert by_ticker["020357"]["currency"] == "CNY"
    assert by_ticker["QQQ"]["currency"] == "USD"
    assert by_ticker["QQQ"]["market_value_cny"] == round(us_mv_cny, 2)


def test_get_portfolio_returns_error_when_fx_missing(monkeypatch):
    holdings = [
        SimpleNamespace(
            id=1,
            ticker="QQQ",
            market="US",
            shares=1.0,
            cost_basis=100.0,
            position_type="core",
        ),
    ]

    class FakeSession:
        def close(self):
            return None

    class FakeAdapter:
        def get_price(self, ticker):
            return {"ticker": ticker, "price": 110.0}

    class FakeRegistry:
        def get(self, market):
            return FakeAdapter()

    monkeypatch.setattr(tools, "get_session", lambda: FakeSession())
    monkeypatch.setattr(tools, "get_open_holdings", lambda _s: holdings)
    monkeypatch.setattr(tools, "adapter_registry", FakeRegistry())
    monkeypatch.setattr("app.fx.get_cny_rates", lambda markets: {})

    result = tools.get_portfolio.invoke({})
    assert isinstance(result, dict)
    assert "error" in result
