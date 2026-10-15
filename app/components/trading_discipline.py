"""Durable trading rules editor, outside the dashboard's live KPI fragment."""
import logging

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app.i18n import t
from db.repository import get_session, get_trading_discipline, save_trading_discipline

logger = logging.getLogger(__name__)


def render_trading_discipline():
    session = get_session()
    try:
        memo = get_trading_discipline(session)
        content = memo.content if memo else ""
    finally:
        session.close()

    with st.container(border=True, key="trading_discipline_panel"):
        st.subheader(t("discipline.title"))
        st.caption(t("discipline.caption"))
        # Streamlit commits a text area when it loses focus. Persist that
        # committed value here so the editor has no save button.
        draft = st.text_area(
            t("discipline.label"),
            value=content,
            height="content",
            placeholder=t("discipline.placeholder"),
            key="trading_discipline_draft",
            label_visibility="collapsed",
        )
        if (draft or "").strip() == content.strip():
            return
        session = get_session()
        try:
            save_trading_discipline(session, draft or "")
        except SQLAlchemyError:
            session.rollback()
            logger.exception("Could not save trading discipline")
            st.error(t("discipline.failed"))
        finally:
            session.close()
