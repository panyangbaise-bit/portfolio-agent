"""History — past recommendations and decision audit trail."""

import streamlit as st
from app.i18n import enum_label, t
from app.timeutil import format_display_time
from db.repository import get_session, get_recommendation_history

st.title(t("history.title"))
st.caption(t("history.caption"))

session = get_session()
try:
    all_recs = get_recommendation_history(session, limit=100)
finally:
    session.close()

if not all_recs:
    st.info(t("history.empty"))
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
                    t(
                        "history.header",
                        ticker=rec.ticker,
                        action=enum_label("action", rec.action),
                        confidence=f"{rec.confidence:.0%}",
                        urgency=enum_label("urgency", rec.urgency),
                        status=enum_label("rec_status", rec.status),
                    )
                )
                st.caption(format_display_time(rec.created_at))
                st.write(rec.reasoning)
            st.divider()
