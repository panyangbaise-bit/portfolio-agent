"""Holdings management — add, edit, delete positions."""

import streamlit as st
from app.i18n import enum_label, t
from db.repository import (
    get_session, get_all_holdings, create_holding,
    update_holding, delete_holding, create_transaction,
    get_transactions_for_holding,
)

st.title(t("holdings.title"))

tab_add, tab_edit, tab_history = st.tabs([
    t("holdings.tab.add"), t("holdings.tab.edit"), t("holdings.tab.history"),
])

# ── Add Position ──────────────────────────────────────────

with tab_add:
    st.subheader(t("holdings.add.title"))

    with st.form("add_holding_form"):
        col1, col2 = st.columns(2)
        with col1:
            ticker = st.text_input(t("holdings.field.ticker"), placeholder=t("holdings.field.ticker_placeholder"))
            name = st.text_input(t("holdings.field.name"), placeholder=t("holdings.field.name_placeholder"))
            market = st.selectbox(
                t("holdings.field.market"), ["US", "CN", "HK", "CRYPTO"],
                format_func=lambda value: t("market." + value),
            )
        with col2:
            shares = st.number_input(t("holdings.field.shares"), min_value=0.0, step=0.0001, format="%.10f")
            cost_basis = st.number_input(t("holdings.field.cost"), min_value=0.0, step=0.0001, format="%.10f")

        position_type = st.radio(
            t("holdings.field.position_type"), ["core", "satellite"], horizontal=True,
            format_func=lambda value: t("position_type." + value),
            help=t("holdings.field.position_help"),
        )

        submitted = st.form_submit_button(t("holdings.add.submit"), type="primary")
        if submitted:
            if not ticker or shares <= 0 or cost_basis <= 0:
                st.error(t("holdings.add.invalid"))
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
                    st.success(t("holdings.add.success", ticker=ticker.upper(), shares=shares, cost=cost_basis))
                    st.rerun()
                finally:
                    session.close()

# ── Edit / Delete ─────────────────────────────────────────

with tab_edit:
    st.subheader(t("holdings.edit.title"))

    session = get_session()
    try:
        holdings = get_all_holdings(session)
    finally:
        session.close()

    if not holdings:
        st.info(t("holdings.edit.empty"))
    else:
        for h in holdings:
            display = f"{h.name} ({h.ticker})" if h.name else h.ticker
            with st.expander(t(
                "holdings.edit.expander",
                display=display,
                shares=h.shares,
                cost=h.cost_basis,
                position_type=enum_label("position_type", h.position_type),
            )):
                col1, col2, col3 = st.columns(3)
                with col1:
                    new_shares = st.number_input(t("holdings.field.shares_short"), value=float(h.shares), step=0.0001, format="%.10f", key=f"shares_{h.id}")
                with col2:
                    new_cost = st.number_input(t("holdings.field.cost_short"), value=float(h.cost_basis), step=0.0001, format="%.10f", key=f"cost_{h.id}")
                with col3:
                    new_type = st.selectbox(
                        t("holdings.field.type"), ["core", "satellite"],
                        index=0 if h.position_type == "core" else 1,
                        format_func=lambda value: t("position_type." + value),
                        key=f"type_{h.id}",
                    )

                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button(t("holdings.edit.update"), key=f"update_{h.id}"):
                        session = get_session()
                        try:
                            update_holding(session, h.id,
                                           shares=new_shares, cost_basis=new_cost,
                                           position_type=new_type)
                            st.success(t("holdings.edit.updated", ticker=h.ticker))
                            st.rerun()
                        finally:
                            session.close()
                with col_b:
                    if st.button(t("holdings.edit.delete"), key=f"delete_{h.id}", type="secondary"):
                        session = get_session()
                        try:
                            delete_holding(session, h.id)
                            st.success(t("holdings.edit.deleted", ticker=h.ticker))
                            st.rerun()
                        finally:
                            session.close()

# ── Transaction History ───────────────────────────────────

with tab_history:
    st.subheader(t("holdings.history.title"))
    session = get_session()
    try:
        holdings = get_all_holdings(session)
        if not holdings:
            st.info(t("holdings.history.empty"))
        for h in holdings:
            txns = get_transactions_for_holding(session, h.id)
            if txns:
                st.caption(f"**{h.ticker}**")
                for txn in txns:
                    st.text(t(
                        "holdings.history.line",
                        date=txn.date.strftime("%Y-%m-%d"),
                        action=enum_label("action", txn.action),
                        shares=txn.shares,
                        price=txn.price,
                    ))
    finally:
        session.close()
