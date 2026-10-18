"""Operations — schedules, run history, and analysis reports."""

import streamlit as st

from app.components.analysis_table import render_analysis_section
from app.i18n import t


def render() -> None:
    """Render this page for the current Streamlit session."""
    st.title(t("jobs.page.title"))
    st.caption(t("jobs.page.caption"))
    with st.container(key="jobs_workspace"):
        render_analysis_section()


if __name__ == "__main__":
    render()
