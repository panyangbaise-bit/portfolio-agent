"""Currency conversion helpers for dashboard portfolio valuation."""

from typing import Dict, Tuple

import streamlit as st

from app.fx import FX_RATES, currency_for_market, get_cny_rates

# Re-export for existing imports/tests.
__all__ = ["FX_RATES", "currency_for_market", "fetch_cny_rates", "get_cny_rates"]


@st.cache_data(ttl=60, show_spinner=False)
def fetch_cny_rates(markets: Tuple[str, ...]) -> Dict[str, float]:
    """Streamlit-cached wrapper around :func:`app.fx.get_cny_rates`."""
    return get_cny_rates(markets)
