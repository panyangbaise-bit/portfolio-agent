"""Price fetching with caching and timeout protection.

Renders dashboard immediately; fetches prices async-style via Streamlit cache.
Failed/blocking adapters don't hold up the page.
"""

from typing import Optional
import streamlit as st
from adapters.base import registry as adapter_registry


@st.cache_data(ttl=60, show_spinner=False)
def _cached_price(ticker: str, market: str) -> Optional[float]:
    """Fetch a single price with cache. Returns None if unavailable."""
    try:
        adapter = adapter_registry.get(market)
        data = adapter.get_price(ticker)
        return data.get("price")
    except Exception:
        return None


def fetch_price(ticker: str, market: str) -> Optional[float]:
    """Get current price for a holding. Returns None on any failure."""
    return _cached_price(ticker, market)


def fetch_prices_batch(holdings: list) -> dict:
    """Fetch prices for multiple holdings. Returns {ticker: price} dict."""
    result = {}
    for h in holdings:
        result[h.ticker] = _cached_price(h.ticker, h.market)
    return result
