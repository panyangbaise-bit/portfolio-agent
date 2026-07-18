"""History — past recommendations and decision audit trail."""

import streamlit as st
from db.repository import get_session, get_recommendation_history

st.title("📜 Decision History")
st.caption("Full audit trail of agent recommendations and your actions")

session = get_session()
try:
    all_recs = get_recommendation_history(session, limit=100)
finally:
    session.close()

if not all_recs:
    st.info("No recommendations yet. Agent will start analyzing once you add holdings.")
else:
    for rec in all_recs:
        action_emoji = {"buy_add": "🟢", "reduce": "🔴", "hold": "🟡", "watch": "👀"}
        emoji = action_emoji.get(rec.action, "ℹ️")

        with st.container():
            cols = st.columns([1, 7])
            with cols[0]:
                st.markdown(f"### {emoji}")
            with cols[1]:
                st.markdown(
                    f"**{rec.ticker}** — `{rec.action}` | "
                    f"Confidence: {rec.confidence:.0%} | "
                    f"Urgency: {rec.urgency} | "
                    f"Status: {rec.status}"
                )
                st.caption(rec.created_at.strftime("%Y-%m-%d %H:%M"))
                st.write(rec.reasoning)
            st.divider()
