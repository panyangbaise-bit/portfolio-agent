"""Main dashboard — KPI overview, holdings, recommendations, ask-agent."""

import streamlit as st
from app.components.kpi_cards import render_kpi_cards
from app.components.holdings_table import render_holdings_table
from app.components.recommendation_card import render_recommendations

st.title("📊 Portfolio Dashboard")
st.caption("AI-powered investment portfolio management")

render_kpi_cards()

st.divider()

col_left, col_right = st.columns([3, 2])

with col_left:
    render_holdings_table()

with col_right:
    st.subheader("💬 Ask Agent")
    user_question = st.text_area(
        "Question",
        placeholder="e.g., 现在该加仓什么？科技股风险大吗？",
        label_visibility="collapsed",
    )
    if st.button("Send to Agent", type="primary"):
        if user_question:
            with st.spinner("Agent is thinking..."):
                from agent.core import run_ad_hoc_query
                response = run_ad_hoc_query(user_question)
                st.success("Agent response:")
                st.write(response)
        else:
            st.warning("Please enter a question.")

st.divider()

render_recommendations()
