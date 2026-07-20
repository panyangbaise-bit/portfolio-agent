import streamlit as st
from app.i18n import t
from db.repository import get_session, get_open_holdings, get_pending_recommendations
from app.components.price_fetcher import fetch_prices_batch


def render_kpi_cards(holdings=None, prices=None):
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
    total_market_value = 0.0
    total_cost = 0.0
    has_live_data = False

    for h in holdings:
        cost = h.shares * h.cost_basis
        total_cost += cost
        price = prices.get((h.market, h.ticker))
        if price is not None:
            total_market_value += h.shares * price
            has_live_data = True
        else:
            total_market_value += cost

    pnl = total_market_value - total_cost
    pnl_pct = (pnl / total_cost * 100) if total_cost else 0

    cols = st.columns(4)
    with cols[0]:
        st.metric(
            t("kpi.total_value"),
            f"¥{total_market_value:,.2f}",
            delta=f"+¥{pnl:,.2f}" if pnl >= 0 else f"-¥{abs(pnl):,.2f}",
            delta_color="normal",
        )
    with cols[1]:
        label = t("kpi.total_pnl") if has_live_data else t("kpi.total_pnl_cost")
        if pnl_pct > 0:
            tone = "gain"
        elif pnl_pct < 0:
            tone = "loss"
        else:
            tone = "flat"
        st.html(
            '<div class="cp-pnl-metric">'
            '<div class="label">' + label + '</div>'
            '<div class="value ' + tone + '">' + f"{pnl_pct:+.2f}%" + '</div>'
            '</div>'
        )
    with cols[2]:
        st.metric(t("kpi.pending_recs"), str(len(pending)) + (" ⚠️" if len(pending) > 0 else ""))
    with cols[3]:
        high_urgency = [r for r in pending if r.urgency == "high"]
        risk = t("risk.high") if high_urgency else (t("risk.moderate") if pending else t("risk.low"))
        st.metric(t("kpi.risk_level"), risk)

    return holdings, prices
