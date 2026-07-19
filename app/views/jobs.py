"""Jobs — scheduled jobs, manual triggers, and runtime log."""

import streamlit as st

from app.components.analysis_table import render_analysis_section
from app.i18n import t

st.title(t("jobs.page.title"))
st.caption(t("jobs.page.caption"))
render_analysis_section()
