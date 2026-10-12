import logging

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app.i18n import enum_label, t
from app.timeutil import format_display_time
from db.repository import apply_recommendation_action, get_session, get_pending_recommendations

logger = logging.getLogger(__name__)


def _apply_action(recommendation_id, action, notes=None):
    db = get_session()
    try:
        result = apply_recommendation_action(db, recommendation_id, action, notes)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not apply recommendation action")
        st.error(t("rec.action_failed"))
        return
    finally:
        db.close()
    if result["status"] in ("applied", "already_handled", "not_found"):
        st.rerun()
    elif result["status"] == "reason_required":
        st.error(t("rec.reason_required"))
    else:
        st.error(t("rec.action_failed"))


def render_recommendations():
    """Render decisions with a required reason before dismissing a suggestion."""
    session = get_session()
    try:
        recommendations = get_pending_recommendations(session)
    finally:
        session.close()

    if not recommendations:
        st.info(t("rec.empty"))
        return

    st.subheader(t("rec.title"))
    for rec in recommendations:
        with st.container(border=True, key=f"recommendation_{rec.id}"):
            st.markdown(t(
                "rec.header", ticker=rec.ticker, action=enum_label("action", rec.action),
            ))
            st.caption(t(
                "rec.meta", confidence=f"{rec.confidence:.0%}",
                urgency=enum_label("urgency", rec.urgency),
                date=format_display_time(rec.created_at),
            ))
            st.write(rec.reasoning)
            accept_col, dismiss_col, _ = st.columns([1, 1, 3])
            with accept_col:
                if st.button(t("rec.accept"), key=f"accept_{rec.id}", width="stretch"):
                    _apply_action(rec.id, "accept")
            with dismiss_col:
                with st.popover(t("rec.dismiss"), width="stretch"):
                    with st.form(f"dismiss_form_{rec.id}"):
                        reason = st.text_area(
                            t("rec.dismiss_reason"), key=f"dismiss_reason_{rec.id}",
                            placeholder=t("rec.dismiss_placeholder"),
                        )
                        submitted = st.form_submit_button(t("rec.dismiss_confirm"), type="primary")
                    if submitted:
                        _apply_action(rec.id, "dismiss", reason)
