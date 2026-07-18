import streamlit as st
from db.repository import get_session, get_all_holdings, get_pending_recommendations
from app.components.price_fetcher import fetch_price


def render_kpi_cards():
    """Render the top-row KPI metric cards with live prices."""
    session = get_session()
    try:
        holdings = get_all_holdings(session)
        pending = get_pending_recommendations(session)
    finally:
        session.close()

    total_market_value = 0.0
    total_cost = 0.0
    has_live_data = False

    for h in holdings:
        cost = h.shares * h.cost_basis
        total_cost += cost
        price = fetch_price(h.ticker, h.market)
        if price:
            total_market_value += h.shares * price
            has_live_data = True
        else:
            total_market_value += cost

    pnl = total_market_value - total_cost
    pnl_pct = (pnl / total_cost * 100) if total_cost else 0

    cols = st.columns(4)
    with cols[0]:
        st.metric(
            "Total Value",
            f"¥{total_market_value:,.2f}",
            delta=f"+¥{pnl:,.2f}" if pnl >= 0 else f"-¥{abs(pnl):,.2f}",
        )
    with cols[1]:
        label = "Total P&L" if has_live_data else "Total P&L (cost)"
        st.metric(label, f"{pnl_pct:+.2f}%")
    with cols[2]:
        st.metric("Pending Recs", str(len(pending)) + (" ⚠️" if len(pending) > 0 else ""))
    with cols[3]:
        high_urgency = [r for r in pending if r.urgency == "high"]
        risk = "⚠️ High" if high_urgency else ("Moderate" if pending else "✅ Low")
        st.metric("Risk Level", risk)
