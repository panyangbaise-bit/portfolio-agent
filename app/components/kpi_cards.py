import streamlit as st
from app.i18n import t
from db.repository import get_session, get_open_holdings, get_pending_recommendations
from app.components.currency import fetch_cny_rates
from app.components.price_fetcher import fetch_prices_batch
from app.components.portfolio_valuation import calculate_portfolio_totals


def render_kpi_cards(holdings=None, prices=None, cny_rates=None):
    """Render KPI cards and return the shared holdings/price snapshot."""
    session = get_session()
    try:
        if holdings is None:
            holdings = get_open_holdings(session)
        pending = get_pending_recommendations(session)
    finally:
        session.close()

    if prices is None:
        prices = fetch_prices_batch(holdings)
    if cny_rates is None:
        markets = tuple(sorted({h.market for h in holdings}))
        cny_rates = fetch_cny_rates(markets)
    totals = calculate_portfolio_totals(holdings, prices, cny_rates)

    cols = st.columns(4)
    with cols[0]:
        if totals is None:
            st.metric(t("kpi.total_value"), "—")
        else:
            pnl = totals["pnl"]
            st.metric(
                t("kpi.total_value"),
                f"¥{totals['market_value']:,.2f}",
                delta=f"+¥{pnl:,.2f}" if pnl >= 0 else f"-¥{abs(pnl):,.2f}",
                delta_color="normal",
            )
    with cols[1]:
        if totals is None:
            label = t("kpi.total_pnl")
            pnl_pct = None
        else:
            label = t("kpi.total_pnl") if totals["has_live_data"] else t("kpi.total_pnl_cost")
            pnl_pct = totals["pnl_pct"]
        if pnl_pct is not None and pnl_pct > 0:
            tone = "gain"
        elif pnl_pct is not None and pnl_pct < 0:
            tone = "loss"
        else:
            tone = "flat"
        value = f"{pnl_pct:+.2f}%" if pnl_pct is not None else "—"
        st.html(
            '<div class="cp-pnl-metric">'
            '<div class="label">' + label + '</div>'
            '<div class="value ' + tone + '">' + value + '</div>'
            '</div>'
        )
    if totals is None:
        st.warning(t("kpi.fx_unavailable"))
    with cols[2]:
        st.metric(t("kpi.pending_recs"), str(len(pending)) + (" ⚠️" if len(pending) > 0 else ""))
    with cols[3]:
        high_urgency = [r for r in pending if r.urgency == "high"]
        risk = t("risk.high") if high_urgency else (t("risk.moderate") if pending else t("risk.low"))
        st.metric(t("kpi.risk_level"), risk)

    return holdings, prices
