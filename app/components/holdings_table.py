import streamlit as st
import pandas as pd
from db.repository import get_session, get_all_holdings
from adapters.base import registry as adapter_registry


def _fetch_price(h):
    """Fetch current price for a holding. Returns None on failure."""
    try:
        adapter = adapter_registry.get(h.market)
        data = adapter.get_price(h.ticker)
        return data.get("price")
    except Exception:
        return None


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
        price = _fetch_price(h)
        if price:
            market_value = h.shares * price
            cost_value = h.shares * h.cost_basis
            pnl = market_value - cost_value
            pnl_pct = (price / h.cost_basis - 1) * 100 if h.cost_basis else 0
        else:
            market_value = None
            pnl = None
            pnl_pct = None

        rows.append({
            "Name": display,
            "Ticker": h.ticker,
            "Market": h.market,
            "Type": "🔵 Core" if h.position_type == "core" else "🟠 Satellite",
            "Shares": h.shares,
            "Cost": h.cost_basis,
            "Price": price,
            "Mkt Value": market_value,
            "P&L %": pnl_pct,
        })

    df = pd.DataFrame(rows)

    core = df[df["Type"].str.contains("Core")]
    satellite = df[df["Type"].str.contains("Satellite")]

    st.subheader("🔵 Core Holdings")
    if not core.empty:
        _render_table(core)
    else:
        st.caption("No core holdings.")

    st.subheader("🟠 Satellite Holdings")
    if not satellite.empty:
        _render_table(satellite)
    else:
        st.caption("No satellite holdings.")


def _render_table(subset: pd.DataFrame):
    """Render a formatted holdings table with P&L coloring."""
    display_cols = ["Name", "Ticker", "Market", "Shares", "Cost", "Price", "P&L %", "Mkt Value"]
    df = subset[display_cols].copy()

    # Format columns
    format_map = {
        "Shares": "{:.4f}",
        "Cost": "{:.4f}",
        "Price": "{:.4f}",
        "Mkt Value": "{:.2f}",
        "P&L %": "{:+.2f}%",
    }
    styled = df.style.format(format_map, na_rep="—")

    # Color P&L column
    def _color_pnl(val):
        if isinstance(val, str) or val is None:
            return ""
        try:
            v = float(str(val).rstrip("%"))
            return "color: #22c55e" if v > 0 else ("color: #ef4444" if v < 0 else "")
        except (ValueError, TypeError):
            return ""

    styled = styled.applymap(_color_pnl, subset=["P&L %"])

    st.dataframe(styled, use_container_width=True, hide_index=True)
