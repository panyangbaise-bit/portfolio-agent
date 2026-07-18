import streamlit as st
from app.i18n import enum_label, t
from db.repository import get_session, get_pending_recommendations, record_user_action


def render_recommendations():
    """Render the latest agent recommendations as cards with accept/dismiss buttons."""
    session = get_session()
    try:
        recommendations = get_pending_recommendations(session)
    finally:
        session.close()

    if not recommendations:
        st.info(t("rec.empty"))
        return

    action_emojis = {"buy_add": "🟢", "reduce": "🔴", "hold": "🟡", "watch": "👀"}

    st.subheader(t("rec.title"))
    for rec in recommendations:
        emoji = action_emojis.get(rec.action, "ℹ️")
        with st.container():
            cols = st.columns([1, 8, 1, 1])
            with cols[0]:
                st.markdown(f"### {emoji}")
            with cols[1]:
                st.markdown(t(
                    "rec.header",
                    ticker=rec.ticker,
                    action=enum_label("action", rec.action),
                ))
                st.caption(
                    t(
                        "rec.meta",
                        confidence=f"{rec.confidence:.0%}",
                        urgency=enum_label("urgency", rec.urgency),
                        date=rec.created_at.strftime("%Y-%m-%d %H:%M"),
                    )
                )
                st.write(rec.reasoning)
            with cols[2]:
                if st.button(t("rec.accept"), key=f"accept_{rec.id}"):
                    db = get_session()
                    try:
                        record_user_action(db, rec.id, "accept")
                    finally:
                        db.close()
                    st.rerun()
            with cols[3]:
                if st.button(t("rec.dismiss"), key=f"dismiss_{rec.id}"):
                    db = get_session()
                    try:
                        record_user_action(db, rec.id, "dismiss")
                    finally:
                        db.close()
                    st.rerun()
            st.divider()
