"""Main dashboard — KPI overview and holdings snapshot."""

import streamlit as st
from app.i18n import t
from app.components.currency import fetch_cny_rates
from app.components.kpi_cards import render_kpi_cards
from app.components.holdings_table import render_holdings_table
from app.components.price_fetcher import (
    fetch_prices_batch,
    load_cached_prices,
    overlay_live_prices,
    persist_cost_basis_fallbacks,
    save_live_prices,
)
from db.repository import get_open_holdings, get_session

st.title(t("dashboard.title"))


def _load_open_holdings():
    """Load the current open holdings from the database."""
    session = get_session()
    try:
        return get_open_holdings(session)
    finally:
        session.close()


@st.fragment(run_every=60)
def render_live_kpi_snapshot():
    """Refresh only portfolio KPIs without replacing the holdings table."""
    holdings = _load_open_holdings()
    cached_prices = load_cached_prices(holdings)
    cached_prices = persist_cost_basis_fallbacks(holdings, cached_prices)
    live_prices = fetch_prices_batch(holdings)
    save_live_prices(live_prices)
    prices = overlay_live_prices(cached_prices, live_prices)
    markets = tuple(sorted({holding.market for holding in holdings}))
    cny_rates = fetch_cny_rates(markets)
    render_kpi_cards(holdings=holdings, prices=prices, cny_rates=cny_rates)


holdings = _load_open_holdings()
table_prices = load_cached_prices(holdings)
table_prices = persist_cost_basis_fallbacks(holdings, table_prices)
markets = tuple(sorted({holding.market for holding in holdings}))
table_cny_rates = fetch_cny_rates(markets)

render_live_kpi_snapshot()
st.divider()
render_holdings_table(
    holdings=holdings,
    prices=table_prices,
    cny_rates=table_cny_rates,
)
