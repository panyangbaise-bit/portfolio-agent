import streamlit as st
import pandas as pd
from db.repository import get_session, get_all_holdings
from app.components.price_fetcher import fetch_price


def render_holdings_table():
    """Render the holdings data table with live P&L, grouped by position type."""
    session = get_session()
    try:
        holdings = get_all_holdings(session)
    finally:
        session.close()

    if not holdings:
        st.info("No holdings yet. Add your first position in the Holdings page.")
        return

    rows = []
    for h in holdings:
        display = h.name if h.name else h.ticker
        price = fetch_price(h.ticker, h.market)
        if price:
            market_value = h.shares * price
            cost_value = h.shares * h.cost_basis
            pnl_pct = (price / h.cost_basis - 1) * 100 if h.cost_basis else 0
        else:
            market_value = None
            pnl_pct = None

        rows.append({
            "Name": display,
            "Ticker": h.ticker,
            "Market": h.market,
            "Type": "🔵 Core" if h.position_type == "core" else "🟠 Satellite",
            "Shares": f"{h.shares:.4f}",
            "Cost": f"{h.cost_basis:.4f}",
            "Price": f"{price:.4f}" if price else "—",
            "P&L %": f"{pnl_pct:+.2f}%" if pnl_pct is not None else "—",
            "Mkt Value": f"{market_value:,.2f}" if price else "—",
        })

    df = pd.DataFrame(rows)

    core = df[df["Type"].str.contains("Core")]
    satellite = df[df["Type"].str.contains("Satellite")]

    st.subheader("🔵 Core Holdings")
    if not core.empty:
        st.dataframe(core.drop(columns=["Type"]), use_container_width=True, hide_index=True)
    else:
        st.caption("No core holdings.")

    st.subheader("🟠 Satellite Holdings")
    if not satellite.empty:
        st.dataframe(satellite.drop(columns=["Type"]), use_container_width=True, hide_index=True)
    else:
        st.caption("No satellite holdings.")
