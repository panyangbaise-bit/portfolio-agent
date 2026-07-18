import streamlit as st
import pandas as pd
from db.repository import get_session, get_all_holdings


def render_holdings_table():
    """Render the holdings data table grouped by position type."""
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
        rows.append({
            "Ticker": h.ticker,
            "Market": h.market,
            "Type": "🔵 Core" if h.position_type == "core" else "🟠 Satellite",
            "Shares": h.shares,
            "Cost Basis": h.cost_basis,
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
