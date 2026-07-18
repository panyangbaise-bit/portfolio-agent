"""Price fetching with caching and dashboard render deadlines."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Optional

import streamlit as st
from adapters.base import registry as adapter_registry
from db.repository import get_latest_prices, get_session, upsert_price

logger = logging.getLogger(__name__)


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


def overlay_live_prices(cached_prices: dict, live_prices: dict) -> dict:
    """Keep a cached value when the corresponding live request is unfinished."""
    prices = dict(cached_prices)
    for key, value in live_prices.items():
        if value is not None:
            prices[key] = value
    return prices


def resolve_display_price(price: Optional[float], cost_basis: float) -> float:
    """Use cost basis when no live or persisted price is available."""
    return float(price) if price is not None else float(cost_basis)


def load_cached_prices(holdings: list) -> dict:
    """Load persisted prices without making any remote API request."""
    session = get_session()
    try:
        return get_latest_prices(session, holdings)
    finally:
        session.close()


def persist_cost_basis_fallbacks(holdings: list, prices: dict) -> dict:
    """Persist cost basis for holdings that have no quote history yet.

    This guarantees a complete restart-safe portfolio snapshot from the first
    dashboard render. A later live quote overwrites the fallback for the day.
    """
    snapshot_date = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    completed_prices = dict(prices)
    session = get_session()
    try:
        for holding in holdings:
            key = (holding.market, holding.ticker)
            if completed_prices.get(key) is None:
                fallback = resolve_display_price(None, holding.cost_basis)
                upsert_price(
                    session,
                    ticker=holding.ticker,
                    market=holding.market,
                    date=snapshot_date,
                    close=fallback,
                    source="cost_basis",
                )
                completed_prices[key] = fallback
    finally:
        session.close()
    return completed_prices


def save_live_prices(prices: dict):
    """Persist successful dashboard prices as today's fallback snapshot."""
    snapshot_date = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    session = get_session()
    try:
        for (market, ticker), price in prices.items():
            if price is not None:
                upsert_price(
                    session,
                    ticker=ticker,
                    market=market,
                    date=snapshot_date,
                    close=float(price),
                    source="dashboard_live",
                )
    finally:
        session.close()


def fetch_prices_batch(holdings: list, timeout_seconds: float = 2.0) -> dict:
    """Fetch dashboard prices concurrently without delaying the first render.

    A provider may be slow or unavailable. Returning ``None`` for an unfinished
    request lets the dashboard show cost-basis data instead of waiting for every
    remote API. Completed values remain in Streamlit's 60-second cache.
    """
    unique_pairs = {(h.ticker, h.market) for h in holdings}
    prices = {(market, ticker): None for ticker, market in unique_pairs}
    if not unique_pairs:
        return prices

    started = time.perf_counter()
    executor = ThreadPoolExecutor(max_workers=len(unique_pairs))
    futures = {
        executor.submit(_cached_price, ticker, market): (market, ticker)
        for ticker, market in unique_pairs
    }
    done, pending = wait(futures, timeout=timeout_seconds)

    for future in done:
        market, ticker = futures[future]
        try:
            prices[(market, ticker)] = future.result()
        except Exception:
            logger.exception("Price fetch failed for %s:%s", market, ticker)

    for future in pending:
        future.cancel()

    # Do not wait for a provider already past the UI deadline.
    executor.shutdown(wait=False)
    elapsed = time.perf_counter() - started
    logger.info(
        "Dashboard prices: %d/%d completed in %.2fs (deadline %.2fs)",
        len(done),
        len(unique_pairs),
        elapsed,
        timeout_seconds,
    )
    return prices
