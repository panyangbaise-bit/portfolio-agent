"""Main dashboard — KPI overview, holdings snapshot, ask-agent."""

import time

import streamlit as st
from app.i18n import t
from app.components.kpi_cards import render_kpi_cards
from app.components.holdings_table import render_holdings_table
from app.components.price_fetcher import (
    fetch_prices_batch,
    load_cached_prices,
    overlay_live_prices,
    persist_cost_basis_fallbacks,
    save_live_prices,
)
from db.repository import get_all_holdings, get_session

hdr_l, hdr_r = st.columns([5, 1])
with hdr_l:
    st.title(t("dashboard.title"))
with hdr_r:
    st.write("")  # vertical align popover with title
    with st.popover(t("ask_agent.popover")):
        user_question = st.text_area(
            t("ask_agent.question"),
            placeholder=t("ask_agent.placeholder"),
            label_visibility="collapsed",
            key="ask_agent_question",
        )
        if st.button(t("ask_agent.send"), type="primary", key="ask_agent_send"):
            if user_question:
                with st.spinner(t("ask_agent.thinking")):
                    from agent.core import run_ad_hoc_query
                    response = run_ad_hoc_query(user_question)
                    st.success(t("ask_agent.response"))
                    st.write(response)
            else:
                st.warning(t("ask_agent.empty"))

@st.fragment(run_every=1)
def render_portfolio_snapshot():
    """Render cached values first, then refresh live prices on later ticks."""
    session = get_session()
    try:
        holdings = get_all_holdings(session)
    finally:
        session.close()

    cached_prices = load_cached_prices(holdings)
    cached_prices = persist_cost_basis_fallbacks(holdings, cached_prices)
    now = time.monotonic()
    initial_rendered = st.session_state.get("portfolio_snapshot_rendered", False)
    last_refresh = st.session_state.get("portfolio_live_refresh_at", 0.0)
    should_refresh = initial_rendered and now - last_refresh >= 60

    prices = cached_prices
    if should_refresh:
        live_prices = fetch_prices_batch(holdings)
        save_live_prices(live_prices)
        prices = overlay_live_prices(cached_prices, live_prices)
        st.session_state["portfolio_live_refresh_at"] = now

    render_kpi_cards(holdings=holdings, prices=prices)
    st.divider()
    render_holdings_table(holdings=holdings, prices=prices)
    st.session_state["portfolio_snapshot_rendered"] = True


render_portfolio_snapshot()
