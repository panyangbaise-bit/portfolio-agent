"""Currency conversion helpers (no Streamlit dependency — safe for agent/jobs)."""

import logging
from typing import Dict, Tuple

import requests

logger = logging.getLogger(__name__)

# Process-local last-known rates (fallback after transient FX failures).
FX_RATES: Dict[str, float] = {}

_MARKET_CURRENCIES = {
    "CN": "CNY",
    "US": "USD",
    "CRYPTO": "USD",
    "HK": "HKD",
}
_FX_URL = "https://open.er-api.com/v6/latest/{}"


def currency_for_market(market: str) -> str:
    """Return the native quote currency for a supported market."""
    return _MARKET_CURRENCIES[market.upper()]


def _fetch_rate(base_currency: str) -> float:
    response = requests.get(_FX_URL.format(base_currency), timeout=2)
    response.raise_for_status()
    payload = response.json()
    if payload.get("result") != "success":
        raise ValueError("FX provider returned an unsuccessful response")
    return float(payload["rates"]["CNY"])


def get_cny_rates(markets: Tuple[str, ...]) -> Dict[str, float]:
    """Fetch CNY conversion rates required by the supplied markets.

    A transient provider failure uses the most recent process-local rate. A
    market is omitted when it has no usable rate, allowing callers to avoid
    presenting an unconverted value as CNY.
    """
    normalized_markets = {market.upper() for market in markets}
    rates: Dict[str, float] = {}

    if "CN" in normalized_markets:
        rates["CN"] = 1.0

    base_rates: Dict[str, float] = {}
    for market in normalized_markets - {"CN"}:
        base_currency = currency_for_market(market)
        if base_currency not in base_rates:
            try:
                base_rates[base_currency] = _fetch_rate(base_currency)
            except Exception as exc:
                logger.warning(
                    "Unable to fetch %s/CNY rate: %s", base_currency, exc
                )

        rate = base_rates.get(base_currency)
        if rate is not None:
            FX_RATES[market] = rate
        else:
            rate = FX_RATES.get(market)
        if rate is None:
            rate = next(
                (
                    saved_rate
                    for saved_market, saved_rate in FX_RATES.items()
                    if currency_for_market(saved_market) == base_currency
                ),
                None,
            )

        if rate is not None:
            rates[market] = rate

    return rates
