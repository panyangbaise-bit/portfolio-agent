import streamlit as st
import pandas as pd
from app.i18n import t
from db.repository import get_session, get_open_holdings
from app.components.price_fetcher import fetch_prices_batch, resolve_display_price


def _color_pnl_cell(val):
    """Green for gains, red for losses (绿涨红跌)."""
    if not isinstance(val, str) or val == "—":
        return ""
    try:
        num = float(val.replace("%", "").replace(",", "").replace("+", ""))
    except ValueError:
        return ""
    if num > 0:
        return "color: #00ff9c; font-weight: 600"
    if num < 0:
        return "color: #ff2d6a; font-weight: 600"
    return ""


def _styled_holdings(df):
    """Drop Type column and color the P&L % column."""
    display = df.drop(columns=[t("col.type")])
    styler = display.style
    # pandas 2.1+ uses map; older uses applymap
    if hasattr(styler, "map"):
        return styler.map(_color_pnl_cell, subset=[t("col.pnl")])
    return styler.applymap(_color_pnl_cell, subset=[t("col.pnl")])


def render_holdings_table(holdings=None, prices=None):
    """Render holdings using an optional shared live-price snapshot."""
    if holdings is None:
        session = get_session()
        try:
            holdings = get_open_holdings(session)
        finally:
            session.close()

    if not holdings:
        st.info(t("holdings_table.empty"))
        return

    if prices is None:
        prices = fetch_prices_batch(holdings)

    rows = []
    for h in holdings:
        display = h.name if h.name else h.ticker
        price = resolve_display_price(
            prices.get((h.market, h.ticker)),
            h.cost_basis,
        )
        market_value = h.shares * price
        pnl_pct = (price / h.cost_basis - 1) * 100 if h.cost_basis else 0

        rows.append({
            t("col.name"): display,
            t("col.ticker"): h.ticker,
            t("col.market"): t("market." + h.market),
            t("col.type"): t("position_type." + h.position_type + "_badge"),
            t("col.shares"): f"{h.shares:.4f}",
            t("col.cost"): f"{h.cost_basis:.4f}",
            t("col.price"): f"{price:.4f}",
            t("col.pnl"): f"{pnl_pct:+.2f}%",
            t("col.market_value"): f"{market_value:,.2f}",
        })

    df = pd.DataFrame(rows)

    core = df[df[t("col.type")].str.contains("🔵")]
    satellite = df[df[t("col.type")].str.contains("🟠")]

    st.subheader(t("holdings_table.core"))
    if not core.empty:
        st.dataframe(_styled_holdings(core), width="stretch", hide_index=True)
    else:
        st.caption(t("holdings_table.core_empty"))

    st.subheader(t("holdings_table.satellite"))
    if not satellite.empty:
        st.dataframe(_styled_holdings(satellite), width="stretch", hide_index=True)
    else:
        st.caption(t("holdings_table.satellite_empty"))
