import streamlit as st
import pandas as pd
from app.i18n import t
from db.repository import get_session, get_open_holdings
from app.components.currency import fetch_cny_rates
from app.components.price_fetcher import fetch_prices_batch, resolve_display_price

_CURRENCY_SYMBOLS = {
    "CN": "¥",
    "US": "$",
    "CRYPTO": "$",
    "HK": "HK$",
}


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


def format_quote(value, market):
    """Format a native-currency price or cost basis."""
    return "{}{:.4f}".format(_CURRENCY_SYMBOLS[market.upper()], value)


def format_cny_market_value(value):
    """Format a market value that has already been converted to CNY."""
    return "¥{:,.2f}".format(value)


def build_holding_rows(holdings, prices, cny_rates):
    """Build display rows while preserving quotes in native currencies."""
    rows = []
    for h in holdings:
        display = h.name if h.name else h.ticker
        market = h.market.upper()
        price = resolve_display_price(
            prices.get((h.market, h.ticker)),
            h.cost_basis,
        )
        rate = cny_rates.get(market)
        market_value = (
            format_cny_market_value(h.shares * price * rate)
            if rate is not None
            else "—"
        )
        pnl_pct = (price / h.cost_basis - 1) * 100 if h.cost_basis else 0

        rows.append({
            t("col.name"): display,
            t("col.ticker"): h.ticker,
            t("col.market"): t("market." + market),
            t("col.type"): t("position_type." + h.position_type + "_badge"),
            t("col.shares"): f"{h.shares:.4f}",
            t("col.cost"): format_quote(h.cost_basis, market),
            t("col.price"): format_quote(price, market),
            t("col.pnl"): f"{pnl_pct:+.2f}%",
            t("col.market_value"): market_value,
        })

    return rows


def _styled_holdings(df):
    """Drop Type column and color the P&L % column."""
    display = df.drop(columns=[t("col.type")])
    styler = display.style
    # pandas 2.1+ uses map; older uses applymap
    if hasattr(styler, "map"):
        return styler.map(_color_pnl_cell, subset=[t("col.pnl")])
    return styler.applymap(_color_pnl_cell, subset=[t("col.pnl")])


def render_holdings_table(holdings=None, prices=None, cny_rates=None):
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

    if cny_rates is None:
        markets = tuple(sorted({h.market for h in holdings}))
        cny_rates = fetch_cny_rates(markets)

    rows = build_holding_rows(holdings, prices, cny_rates)

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
