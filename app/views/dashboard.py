"""Main dashboard — KPI overview, holdings snapshot, ask-agent."""

import time

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
            if not user_question:
                st.warning(t("ask_agent.empty"))
            else:
                st.session_state["ask_agent_run"] = {
                    "question": user_question,
                    "ts": time.time(),
                }

# Streamed Ask Agent output lives in the main body (popover is submit-only).
_ask_run = st.session_state.get("ask_agent_run")
if _ask_run and st.session_state.get("ask_agent_streamed_ts") != _ask_run.get("ts"):
    from agent.core import run_ad_hoc_query_stream

    st.subheader(t("ask_agent.response"))
    with st.status(t("ask_agent.streaming"), expanded=True) as status:
        tokens = []

        def _token_gen():
            for event in run_ad_hoc_query_stream(_ask_run["question"]):
                etype = event.get("type")
                text = event.get("text") or ""
                if etype == "status":
                    status.write(text)
                elif etype == "token":
                    tokens.append(text)
                    yield text
                elif etype == "error":
                    status.update(label=t("ask_agent.error"), state="error")
                    status.write(text)
                    st.session_state["ask_agent_last_error"] = text
                    return
                elif etype == "done":
                    st.session_state["ask_agent_last_response"] = text or "".join(tokens)
                    status.update(label=t("ask_agent.done"), state="complete")

        st.write_stream(_token_gen())
    st.session_state["ask_agent_streamed_ts"] = _ask_run.get("ts")
elif st.session_state.get("ask_agent_last_response"):
    with st.expander(t("ask_agent.response"), expanded=False):
        st.write(st.session_state["ask_agent_last_response"])

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
