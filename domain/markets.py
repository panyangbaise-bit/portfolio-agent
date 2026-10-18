"""Canonical quote currencies shared by portfolio consumers."""

MARKET_CURRENCIES = {"CN": "CNY", "US": "USD", "CRYPTO": "USD", "HK": "HKD"}


def currency_for_market(market: str) -> str:
    """Return a supported market's native currency; reject unknown markets."""
    return MARKET_CURRENCIES[market.upper()]
