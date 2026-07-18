"""Holdings management — add, edit, delete positions."""

import streamlit as st
from db.repository import (
    get_session, get_all_holdings, create_holding,
    update_holding, delete_holding, create_transaction,
    get_transactions_for_holding,
)

st.title("📋 Holdings Management")

tab_add, tab_edit, tab_history = st.tabs(["Add Position", "Edit / Delete", "Transaction History"])

# ── Add Position ──────────────────────────────────────────

with tab_add:
    st.subheader("➕ Add New Position")

    with st.form("add_holding_form"):
        col1, col2 = st.columns(2)
        with col1:
            ticker = st.text_input("Ticker Symbol", placeholder="e.g., AAPL, 600519, BTC, 020357")
            name = st.text_input("Display Name (optional)", placeholder="e.g., 华夏半导体材料ETF联接C")
            market = st.selectbox("Market", ["US", "CN", "HK", "CRYPTO"])
        with col2:
            shares = st.number_input("Shares / Quantity", min_value=0.0, step=0.0001, format="%.10f")
            cost_basis = st.number_input("Cost Basis (per share/unit)", min_value=0.0, step=0.0001, format="%.10f")

        position_type = st.radio(
            "Position Type", ["core", "satellite"], horizontal=True,
            help="核心仓=长期持有 | 卫星仓=短期交易",
        )

        submitted = st.form_submit_button("Add Position", type="primary")
        if submitted:
            if not ticker or shares <= 0 or cost_basis <= 0:
                st.error("Please fill in all fields correctly.")
            else:
                session = get_session()
                try:
                    holding = create_holding(
                        session, ticker=ticker.upper(), market=market,
                        shares=shares, cost_basis=cost_basis,
                        position_type=position_type, name=name or None,
                    )
                    create_transaction(
                        session, holding.id, action="buy",
                        shares=shares, price=cost_basis,
                        notes="Initial position added.",
                    )
                    st.success(f"Added {ticker.upper()} — {shares} shares at {cost_basis}")
                    st.rerun()
                finally:
                    session.close()

# ── Edit / Delete ─────────────────────────────────────────

with tab_edit:
    st.subheader("✏️ Edit or Delete Positions")

    session = get_session()
    try:
        holdings = get_all_holdings(session)
    finally:
        session.close()

    if not holdings:
        st.info("No holdings to edit.")
    else:
        for h in holdings:
            display = f"{h.name} ({h.ticker})" if h.name else h.ticker
            with st.expander(f"{display} — {h.shares} shares @ {h.cost_basis} ({h.position_type})"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    new_shares = st.number_input("Shares", value=float(h.shares), step=0.0001, format="%.10f", key=f"shares_{h.id}")
                with col2:
                    new_cost = st.number_input("Cost Basis", value=float(h.cost_basis), step=0.0001, format="%.10f", key=f"cost_{h.id}")
                with col3:
                    new_type = st.selectbox(
                        "Type", ["core", "satellite"],
                        index=0 if h.position_type == "core" else 1,
                        key=f"type_{h.id}",
                    )

                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("💾 Update", key=f"update_{h.id}"):
                        session = get_session()
                        try:
                            update_holding(session, h.id,
                                           shares=new_shares, cost_basis=new_cost,
                                           position_type=new_type)
                            st.success(f"Updated {h.ticker}")
                            st.rerun()
                        finally:
                            session.close()
                with col_b:
                    if st.button("🗑️ Delete", key=f"delete_{h.id}", type="secondary"):
                        session = get_session()
                        try:
                            delete_holding(session, h.id)
                            st.success(f"Deleted {h.ticker}")
                            st.rerun()
                        finally:
                            session.close()

# ── Transaction History ───────────────────────────────────

with tab_history:
    st.subheader("📜 Transaction History")
    session = get_session()
    try:
        holdings = get_all_holdings(session)
        if not holdings:
            st.info("No transactions yet.")
        for h in holdings:
            txns = get_transactions_for_holding(session, h.id)
            if txns:
                st.caption(f"**{h.ticker}**")
                for t in txns:
                    st.text(f"  {t.date.strftime('%Y-%m-%d')} — {t.action}: {t.shares} shares @ {t.price}")
    finally:
        session.close()
