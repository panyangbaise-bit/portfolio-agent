"""Recommendations — pending agent suggestions with accept/dismiss."""

import streamlit as st

from app.components.recommendation_card import render_recommendations
from app.i18n import t

st.title(t("rec.page.title"))
st.caption(t("rec.page.caption"))
render_recommendations()
