from types import SimpleNamespace

from app.components.holdings_table import format_cny_market_value, format_quote
from app.components.portfolio_valuation import calculate_portfolio_totals


def test_calculate_portfolio_totals_converts_cost_and_value_to_cny():
    holdings = [
        SimpleNamespace(market="CN", ticker="600519", shares=2, cost_basis=100),
        SimpleNamespace(market="US", ticker="QQQ", shares=3, cost_basis=10),
        SimpleNamespace(market="HK", ticker="0700", shares=4, cost_basis=20),
    ]
    prices = {
        ("CN", "600519"): 110,
        ("US", "QQQ"): 12,
        ("HK", "0700"): 15,
    }

    totals = calculate_portfolio_totals(
        holdings, prices, {"CN": 1.0, "US": 7.0, "HK": 0.9}
    )

    assert totals["cost"] == 482.0
    assert totals["market_value"] == 526.0
    assert totals["pnl"] == 44.0
    assert round(totals["pnl_pct"], 2) == 9.13


def test_calculate_portfolio_totals_returns_none_when_foreign_fx_is_missing():
    holdings = [SimpleNamespace(market="US", ticker="QQQ", shares=1, cost_basis=10)]

    assert calculate_portfolio_totals(holdings, {("US", "QQQ"): 12}, {}) is None


def test_quote_symbols_stay_native_while_market_value_is_cny():
    assert format_quote(687.99, "US") == "$687.9900"
    assert format_quote(590.53, "CRYPTO") == "$590.5300"
    assert format_quote(3.1935, "CN") == "¥3.1935"
    assert format_quote(134.81, "HK") == "HK$134.8100"
    assert format_cny_market_value(4960.89) == "¥4,960.89"
