import streamlit as st
from db.repository import get_session, get_all_holdings, get_pending_recommendations


def render_kpi_cards():
    """Render the top-row KPI metric cards."""
    session = get_session()
    try:
        holdings = get_all_holdings(session)
        pending = get_pending_recommendations(session)
    finally:
        session.close()

    total_value = 0.0
    total_cost = 0.0
    for h in holdings:
        total_cost += h.shares * h.cost_basis
        total_value += h.shares * h.cost_basis

    pnl = total_value - total_cost
    pnl_pct = (pnl / total_cost * 100) if total_cost else 0

    cols = st.columns(4)
    with cols[0]:
        st.metric("Total Value", f"¥{total_value:,.0f}",
                  delta=f"+¥{pnl:,.0f}" if pnl >= 0 else f"-¥{abs(pnl):,.0f}")
    with cols[1]:
        st.metric("Today's P&L", f"{pnl_pct:+.1f}%")
    with cols[2]:
        st.metric("Pending Recs", str(len(pending)) + (" ⚠️" if len(pending) > 0 else ""))
    with cols[3]:
        high_urgency = [r for r in pending if r.urgency == "high"]
        risk = "⚠️ High" if high_urgency else ("Moderate" if pending else "✅ Low")
        st.metric("Risk Level", risk)
