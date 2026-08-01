"""Pure portfolio valuation helpers expressed in CNY."""

from typing import Dict, Optional


def calculate_portfolio_totals(
    holdings: list, prices: dict, cny_rates: Dict[str, float]
) -> Optional[dict]:
    """Calculate CNY cost, market value, P&L and percentage for holdings.

    Returns ``None`` if a held market has no available CNY conversion rate.
    """
    total_cost = 0.0
    total_market_value = 0.0
    has_live_data = False

    for holding in holdings:
        market = holding.market.upper()
        rate = cny_rates.get(market)
        if rate is None:
            return None

        price = prices.get((holding.market, holding.ticker))
        if price is None:
            price = holding.cost_basis
        else:
            has_live_data = True

        total_cost += holding.shares * holding.cost_basis * rate
        total_market_value += holding.shares * price * rate

    pnl = total_market_value - total_cost
    return {
        "cost": total_cost,
        "market_value": total_market_value,
        "pnl": pnl,
        "pnl_pct": pnl / total_cost * 100 if total_cost else 0.0,
        "has_live_data": has_live_data,
    }
