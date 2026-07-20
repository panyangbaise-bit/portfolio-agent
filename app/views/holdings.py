"""Holdings management — add, edit, delete positions."""

import streamlit as st
from app.i18n import enum_label, t
from db.repository import (
    get_session, get_all_holdings, create_holding,
    update_holding, delete_holding, create_transaction,
    get_transactions_for_holding, apply_trade,
)

_FLASH_KEY = "holdings_flash"
_PANEL_KEY = "holdings_panel"
_PANEL_PENDING_KEY = "holdings_panel_pending"
_RESET_ADD_PENDING_KEY = "holdings_reset_add_pending"
_CLEAR_HOLDING_KEYS_PENDING = "holdings_clear_keys_pending"
_ADD_KEYS = (
    "add_ticker",
    "add_name",
    "add_market",
    "add_shares",
    "add_cost",
    "add_position_type",
)
_PANELS = ("add", "edit", "trade", "history")


def _set_flash(level: str, message: str) -> None:
    st.session_state[_FLASH_KEY] = {"level": level, "message": message}


def _show_flash() -> None:
    flash = st.session_state.pop(_FLASH_KEY, None)
    if not flash:
        return
    level = flash.get("level")
    message = flash.get("message", "")
    if level == "success":
        st.success(message)
        st.toast(message, icon="✅")
    elif level == "error":
        st.error(message)
        st.toast(message, icon="⚠️")
    else:
        st.info(message)


def _request_panel(panel: str) -> None:
    """Queue a panel switch for the next run (before the radio widget exists)."""
    if panel in _PANELS:
        st.session_state[_PANEL_PENDING_KEY] = panel


def _apply_pending_panel() -> None:
    pending = st.session_state.pop(_PANEL_PENDING_KEY, None)
    if pending in _PANELS:
        st.session_state[_PANEL_KEY] = pending


def _request_reset_add_form() -> None:
    st.session_state[_RESET_ADD_PENDING_KEY] = True


def _apply_pending_reset_add_form() -> None:
    if not st.session_state.pop(_RESET_ADD_PENDING_KEY, False):
        return
    for key in _ADD_KEYS:
        st.session_state.pop(key, None)


def _clear_holding_widget_keys(holding_id: int) -> None:
    for prefix in ("shares", "cost", "type", "update", "delete", "confirm_delete", "cancel_delete"):
        st.session_state.pop(f"{prefix}_{holding_id}", None)


def _request_clear_holding_keys(holding_id: int) -> None:
    pending = st.session_state.setdefault(_CLEAR_HOLDING_KEYS_PENDING, [])
    pending.append(holding_id)


def _apply_pending_clear_holding_keys() -> None:
    for holding_id in st.session_state.pop(_CLEAR_HOLDING_KEYS_PENDING, []):
        _clear_holding_widget_keys(holding_id)


st.title(t("holdings.title"))
_apply_pending_panel()
_apply_pending_reset_add_form()
_apply_pending_clear_holding_keys()
_show_flash()

panel_labels = {
    "add": t("holdings.tab.add"),
    "edit": t("holdings.tab.edit"),
    "trade": t("holdings.tab.trade"),
    "history": t("holdings.tab.history"),
}
if _PANEL_KEY not in st.session_state:
    st.session_state[_PANEL_KEY] = "add"

panel = st.radio(
    t("holdings.title"),
    options=list(_PANELS),
    format_func=lambda key: panel_labels[key],
    horizontal=True,
    key=_PANEL_KEY,
    label_visibility="collapsed",
)

# ── Add Position ──────────────────────────────────────────

if panel == "add":
    st.subheader(t("holdings.add.title"))

    with st.form("add_holding_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            ticker = st.text_input(
                t("holdings.field.ticker"),
                placeholder=t("holdings.field.ticker_placeholder"),
                key="add_ticker",
            )
            name = st.text_input(
                t("holdings.field.name"),
                placeholder=t("holdings.field.name_placeholder"),
                key="add_name",
            )
            market = st.selectbox(
                t("holdings.field.market"),
                ["US", "CN", "HK", "CRYPTO"],
                format_func=lambda value: t("market." + value),
                key="add_market",
            )
        with col2:
            shares = st.number_input(
                t("holdings.field.shares"),
                min_value=0.0,
                step=0.0001,
                format="%.10f",
                key="add_shares",
            )
            cost_basis = st.number_input(
                t("holdings.field.cost"),
                min_value=0.0,
                step=0.0001,
                format="%.10f",
                key="add_cost",
            )

        position_type = st.radio(
            t("holdings.field.position_type"),
            ["core", "satellite"],
            horizontal=True,
            format_func=lambda value: t("position_type." + value),
            help=t("holdings.field.position_help"),
            key="add_position_type",
        )

        submitted = st.form_submit_button(t("holdings.add.submit"), type="primary")

    if submitted:
        ticker_clean = (ticker or "").strip().upper()
        if not ticker_clean or shares <= 0 or cost_basis <= 0:
            st.error(t("holdings.add.invalid"))
        else:
            session = get_session()
            try:
                holding = create_holding(
                    session,
                    ticker=ticker_clean,
                    market=market,
                    shares=shares,
                    cost_basis=cost_basis,
                    position_type=position_type,
                    name=(name or "").strip() or None,
                )
                create_transaction(
                    session,
                    holding.id,
                    action="buy",
                    shares=shares,
                    price=cost_basis,
                    notes="Initial position added.",
                )
                _set_flash(
                    "success",
                    t(
                        "holdings.add.success",
                        ticker=ticker_clean,
                        shares=shares,
                        cost=cost_basis,
                    ),
                )
                _request_reset_add_form()
                _request_panel("edit")
                st.rerun()
            except Exception as exc:
                st.error(t("holdings.add.failed", error=str(exc)))
            finally:
                session.close()

# ── Edit / Delete ─────────────────────────────────────────

elif panel == "edit":
    st.subheader(t("holdings.edit.title"))
    st.caption(t("holdings.edit.trade_hint"))

    session = get_session()
    try:
        holdings = get_all_holdings(session)
    finally:
        session.close()

    if not holdings:
        st.info(t("holdings.edit.empty"))
    else:
        for h in holdings:
            status = getattr(h, "status", "open") or "open"
            display = f"{h.name} ({h.ticker})" if h.name else h.ticker
            status_label = enum_label("holding_status", status)
            with st.expander(
                t(
                    "holdings.edit.expander",
                    display=f"{display} [{status_label}]",
                    shares=h.shares,
                    cost=h.cost_basis,
                    position_type=enum_label("position_type", h.position_type),
                ),
                expanded=False,
            ):
                col1, col2, col3 = st.columns(3)
                with col1:
                    new_shares = st.number_input(
                        t("holdings.field.shares_short"),
                        value=float(h.shares),
                        step=0.0001,
                        format="%.10f",
                        key=f"shares_{h.id}",
                    )
                with col2:
                    new_cost = st.number_input(
                        t("holdings.field.cost_short"),
                        value=float(h.cost_basis),
                        step=0.0001,
                        format="%.10f",
                        key=f"cost_{h.id}",
                    )
                with col3:
                    new_type = st.selectbox(
                        t("holdings.field.type"),
                        ["core", "satellite"],
                        index=0 if h.position_type == "core" else 1,
                        format_func=lambda value: t("position_type." + value),
                        key=f"type_{h.id}",
                    )

                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button(t("holdings.edit.update"), key=f"update_{h.id}", type="primary"):
                        if new_shares < 0 or new_cost <= 0:
                            _set_flash("error", t("holdings.add.invalid"))
                            st.rerun()
                        session = get_session()
                        try:
                            update_kwargs = {
                                "shares": new_shares,
                                "cost_basis": new_cost,
                                "position_type": new_type,
                            }
                            if new_shares == 0:
                                update_kwargs["status"] = "closed"
                            elif status == "closed" and new_shares > 0:
                                update_kwargs["status"] = "open"
                            update_holding(session, h.id, **update_kwargs)
                            _set_flash(
                                "success",
                                t("holdings.edit.updated", ticker=h.ticker),
                            )
                            _request_panel("edit")
                            st.rerun()
                        except Exception as exc:
                            _set_flash(
                                "error",
                                t("holdings.edit.update_failed", ticker=h.ticker, error=str(exc)),
                            )
                            _request_panel("edit")
                            st.rerun()
                        finally:
                            session.close()
                with col_b:
                    confirm_key = f"confirm_delete_{h.id}"
                    if st.session_state.get(confirm_key):
                        if st.button(
                            t("holdings.edit.delete_confirm", ticker=h.ticker),
                            key=f"delete_{h.id}",
                            type="primary",
                        ):
                            session = get_session()
                            try:
                                delete_holding(session, h.id)
                                _request_clear_holding_keys(h.id)
                                st.session_state.pop(confirm_key, None)
                                _set_flash(
                                    "success",
                                    t("holdings.edit.deleted", ticker=h.ticker),
                                )
                                _request_panel("edit")
                                st.rerun()
                            except Exception as exc:
                                _set_flash(
                                    "error",
                                    t(
                                        "holdings.edit.delete_failed",
                                        ticker=h.ticker,
                                        error=str(exc),
                                    ),
                                )
                                _request_panel("edit")
                                st.rerun()
                            finally:
                                session.close()
                        if st.button(t("holdings.edit.delete_cancel"), key=f"cancel_delete_{h.id}"):
                            st.session_state.pop(confirm_key, None)
                            _request_panel("edit")
                            st.rerun()
                    elif st.button(t("holdings.edit.delete"), key=f"delete_{h.id}", type="secondary"):
                        st.session_state[confirm_key] = True
                        _request_panel("edit")
                        st.rerun()

# ── Trade (buy / sell) ────────────────────────────────────

elif panel == "trade":
    st.subheader(t("holdings.trade.title"))
    st.caption(t("holdings.trade.caption"))

    session = get_session()
    try:
        holdings = get_all_holdings(session)
    finally:
        session.close()

    if not holdings:
        st.info(t("holdings.trade.empty"))
    else:
        holding_by_id = {h.id: h for h in holdings}

        def _holding_label(hid: int) -> str:
            h = holding_by_id[hid]
            name = h.name or h.ticker
            status = getattr(h, "status", "open") or "open"
            return (
                f"{name} ({h.ticker}) — {h.shares} @ {h.cost_basis} "
                f"[{enum_label('holding_status', status)}]"
            )

        with st.form("trade_holding_form", clear_on_submit=False):
            holding_id = st.selectbox(
                t("holdings.trade.holding"),
                options=list(holding_by_id.keys()),
                format_func=_holding_label,
                key="trade_holding_id",
            )
            action = st.radio(
                t("holdings.trade.action"),
                ["buy", "sell"],
                horizontal=True,
                format_func=lambda value: enum_label("action", value),
                key="trade_action",
            )
            col1, col2 = st.columns(2)
            with col1:
                trade_shares = st.number_input(
                    t("holdings.field.shares"),
                    min_value=0.0,
                    step=0.0001,
                    format="%.10f",
                    key="trade_shares",
                )
            with col2:
                trade_price = st.number_input(
                    t("holdings.trade.price"),
                    min_value=0.0,
                    step=0.0001,
                    format="%.10f",
                    key="trade_price",
                )
            notes = st.text_input(
                t("holdings.trade.notes"),
                placeholder=t("holdings.trade.notes_placeholder"),
                key="trade_notes",
            )
            use_custom_date = st.checkbox(
                t("holdings.trade.custom_date"),
                value=False,
                key="trade_use_date",
            )
            trade_day = st.date_input(
                t("holdings.trade.date"),
                key="trade_date",
            )
            submitted = st.form_submit_button(t("holdings.trade.submit"), type="primary")

        if submitted:
            if trade_shares <= 0 or trade_price <= 0:
                st.error(t("holdings.trade.invalid"))
            else:
                from datetime import datetime, timezone

                trade_date = None
                if use_custom_date and trade_day is not None:
                    trade_date = datetime(
                        trade_day.year, trade_day.month, trade_day.day,
                        tzinfo=timezone.utc,
                    )
                session = get_session()
                try:
                    h = holding_by_id[holding_id]
                    apply_trade(
                        session,
                        holding_id=holding_id,
                        action=action,
                        shares=trade_shares,
                        price=trade_price,
                        notes=(notes or "").strip() or None,
                        trade_date=trade_date,
                    )
                    _set_flash(
                        "success",
                        t(
                            "holdings.trade.success",
                            action=enum_label("action", action),
                            ticker=h.ticker,
                            shares=trade_shares,
                            price=trade_price,
                        ),
                    )
                    _request_panel("history")
                    st.rerun()
                except Exception as exc:
                    st.error(t("holdings.trade.failed", error=str(exc)))
                finally:
                    session.close()

# ── Transaction History ───────────────────────────────────

else:
    st.subheader(t("holdings.history.title"))
    session = get_session()
    try:
        holdings = get_all_holdings(session)
        if not holdings:
            st.info(t("holdings.history.empty"))
        for h in holdings:
            txns = get_transactions_for_holding(session, h.id)
            if txns:
                status = getattr(h, "status", "open") or "open"
                label = h.ticker
                if status == "closed":
                    label = f"{h.ticker} ({enum_label('holding_status', 'closed')})"
                st.caption(f"**{label}**")
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
