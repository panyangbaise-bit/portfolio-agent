"""Durable trading rules editor, outside the dashboard's live KPI fragment."""
import logging

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app.i18n import t
from app.timeutil import format_display_time
from db.repository import get_session, get_trading_discipline, save_trading_discipline

logger = logging.getLogger(__name__)


def render_trading_discipline():
    session = get_session()
    try:
        memo = get_trading_discipline(session)
        content = memo.content if memo else ""
        updated_at = memo.updated_at if memo else None
    finally:
        session.close()

    with st.container(border=True, key="trading_discipline_panel"):
        st.subheader(t("discipline.title"))
        st.caption(t("discipline.caption"))
        with st.form("trading_discipline_form"):
            draft = st.text_area(
                t("discipline.label"), value=content, height=160,
                placeholder=t("discipline.placeholder"), key="trading_discipline_draft",
                label_visibility="collapsed",
            )
            submitted = st.form_submit_button(t("discipline.save"), type="primary")
        if submitted:
            session = get_session()
            try:
                saved = save_trading_discipline(session, draft)
                updated_at = saved.updated_at
                st.success(t("discipline.saved"))
            except SQLAlchemyError:
                session.rollback()
                logger.exception("Could not save trading discipline")
                st.error(t("discipline.failed"))
            finally:
                session.close()
        if updated_at:
            st.caption(t("discipline.updated", date=format_display_time(updated_at)))
