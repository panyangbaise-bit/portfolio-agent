"""Main dashboard — KPI overview, holdings, recommendations, ask-agent."""

import streamlit as st
from app.components.kpi_cards import render_kpi_cards
from app.components.holdings_table import render_holdings_table
from app.components.recommendation_card import render_recommendations

hdr_l, hdr_r = st.columns([5, 1])
with hdr_l:
    st.title("Portfolio Dashboard")
    st.caption("AI-powered investment portfolio management // ONLINE")
with hdr_r:
    st.write("")  # vertical align popover with title
    with st.popover("Ask Agent"):
        user_question = st.text_area(
            "Question",
            placeholder="e.g., 现在该加仓什么？科技股风险大吗？",
            label_visibility="collapsed",
            key="ask_agent_question",
        )
        if st.button("Send to Agent", type="primary", key="ask_agent_send"):
            if user_question:
                with st.spinner("Agent is thinking..."):
                    from agent.core import run_ad_hoc_query
                    response = run_ad_hoc_query(user_question)
                    st.success("Agent response:")
                    st.write(response)
            else:
                st.warning("Please enter a question.")

render_kpi_cards()
st.divider()
render_holdings_table()
st.divider()
render_recommendations()
