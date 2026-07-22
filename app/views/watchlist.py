"""Watchlist 监察表 — track interested stocks before entering positions."""

import streamlit as st
from app.i18n import t
from db.repository import (
    get_session,
    get_watchlist_items,
    create_watchlist_item,
    update_watchlist_item,
    delete_watchlist_item,
    get_holding_by_ticker,
    create_holding,
    create_transaction,
)

_FLASH_KEY = "wl_flash"


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
    elif level == "error":
        st.error(message)
    else:
        st.info(message)


st.title(t("watchlist.title"))
st.caption(t("watchlist.caption"))
_show_flash()

# ── Add to Watchlist ──────────────────────────────────────

with st.expander(t("watchlist.add.title"), expanded=False):
    with st.form("add_watchlist_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            ticker = st.text_input(
                t("watchlist.field.ticker"),
                placeholder=t("watchlist.field.ticker_placeholder"),
                key="wl_add_ticker",
            )
            name = st.text_input(
                t("watchlist.field.name"),
                placeholder=t("watchlist.field.name_placeholder"),
                key="wl_add_name",
            )
        with col2:
            market = st.selectbox(
                t("watchlist.field.market"),
                ["US", "CN", "HK", "CRYPTO"],
                format_func=lambda v: t("market." + v),
                key="wl_add_market",
            )
            priority = st.selectbox(
                t("watchlist.field.priority"),
                ["high", "medium", "low"],
                format_func=lambda v: t("watchlist.priority." + v),
                key="wl_add_priority",
            )

        reason = st.text_area(
            t("watchlist.field.reason"),
            placeholder=t("watchlist.field.reason_placeholder"),
            key="wl_add_reason",
        )

        col_a, col_b = st.columns(2)
        with col_a:
            target_low = st.number_input(
                t("watchlist.field.target_low"),
                min_value=0.0,
                step=0.01,
                format="%.2f",
                key="wl_add_target_low",
                value=None,
            )
        with col_b:
            target_high = st.number_input(
                t("watchlist.field.target_high"),
                min_value=0.0,
                step=0.01,
                format="%.2f",
                key="wl_add_target_high",
                value=None,
            )

        if st.form_submit_button(t("watchlist.add.submit"), type="primary"):
            ticker_clean = (ticker or "").strip().upper()
            if not ticker_clean:
                st.error(t("watchlist.add.invalid"))
            else:
                session = get_session()
                try:
                    create_watchlist_item(
                        session,
                        ticker=ticker_clean,
                        market=market,
                        name=(name or "").strip() or None,
                        watch_reason=(reason or "").strip() or None,
                        target_price_low=target_low if target_low and target_low > 0 else None,
                        target_price_high=target_high if target_high and target_high > 0 else None,
                        priority=priority,
                    )
                    _set_flash("success", t("watchlist.add.success", ticker=ticker_clean))
                    st.rerun()
                except Exception as exc:
                    st.error(t("watchlist.add.failed", error=str(exc)))
                finally:
                    session.close()

# ── Watchlist Table ───────────────────────────────────────

session = get_session()
try:
    items = get_watchlist_items(session)
finally:
    session.close()

if not items:
    st.info(t("watchlist.empty"))
else:
    from datetime import datetime, timezone

    st.subheader(t("watchlist.table.title"))
    for item in items:
        display = f"{item.name} ({item.ticker})" if item.name else item.ticker
        priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(item.priority, "🟡")
        status_label = t("watchlist.status." + item.status)
        priority_label = t("watchlist.priority." + item.priority)

        with st.expander(
            f"{priority_icon} **{display}** — {t('market.' + item.market)} | {priority_label} | {status_label}",
            expanded=item.priority == "high",
        ):
            # info row
            c1, c2, c3 = st.columns(3)
            with c1:
                if item.watch_reason:
                    st.caption(f"💡 {t('watchlist.col.reason')}: {item.watch_reason}")
            with c2:
                if item.target_price_low or item.target_price_high:
                    lo = f"{item.target_price_low:.2f}" if item.target_price_low else "—"
                    hi = f"{item.target_price_high:.2f}" if item.target_price_high else "—"
                    st.caption(f"🎯 {t('watchlist.col.target')}: {lo} ~ {hi}")
            with c3:
                created = item.created_at
                if created:
                    st.caption(f"📅 {created.strftime('%Y-%m-%d')}")

            # action buttons
            ca, cb, cc = st.columns(3)
            with ca:
                # Check price now
                if st.button(
                    t("watchlist.action.check_price"), key=f"wl_check_{item.id}"
                ):
                    try:
                        from adapters.base import registry as adapter_registry
                        adapter = adapter_registry.get(item.market)
                        price_data = adapter.get_price(item.ticker)
                        price = price_data.get("price")
                        if price:
                            in_range = ""
                            if item.target_price_low and price < item.target_price_low:
                                in_range = f" ⬇️ {t('watchlist.below_target')}"
                            elif item.target_price_high and price > item.target_price_high:
                                in_range = f" ⬆️ {t('watchlist.above_target')}"
                            elif item.target_price_low and item.target_price_high and item.target_price_low <= price <= item.target_price_high:
                                in_range = f" ✅ {t('watchlist.in_range')}"
                            st.info(f"{item.ticker}: {price}{in_range}")
                        else:
                            st.warning(t("watchlist.price_unavailable"))
                    except Exception as e:
                        st.error(str(e))

            with cb:
                # Convert to holding
                item_id = item.id
                tkr = item.ticker
                mkt = item.market
                if st.button(
                    t("watchlist.action.convert"), key=f"wl_convert_{item.id}"
                ):
                    st.session_state[f"wl_convert_showing_{item.id}"] = True

                if st.session_state.get(f"wl_convert_showing_{item.id}"):
                    with st.form(key=f"wl_convert_form_{item.id}"):
                        shares = st.number_input(
                            t("holdings.field.shares"),
                            min_value=0.0,
                            step=0.0001,
                            format="%.10f",
                            key=f"wl_conv_shares_{item.id}",
                        )
                        cost = st.number_input(
                            t("holdings.field.cost"),
                            min_value=0.0,
                            step=0.0001,
                            format="%.10f",
                            key=f"wl_conv_cost_{item.id}",
                        )
                        pos_type = st.radio(
                            t("holdings.field.position_type"),
                            ["core", "satellite"],
                            horizontal=True,
                            key=f"wl_conv_type_{item.id}",
                        )
                        col_x, col_y = st.columns(2)
                        with col_x:
                            if st.form_submit_button(t("watchlist.convert.submit")):
                                if shares <= 0 or cost <= 0:
                                    st.error(t("holdings.add.invalid"))
                                else:
                                    txn_session = get_session()
                                    try:
                                        holding = create_holding(
                                            txn_session,
                                            ticker=tkr,
                                            market=mkt,
                                            shares=shares,
                                            cost_basis=cost,
                                            position_type=pos_type,
                                            name=item.name,
                                        )
                                        create_transaction(
                                            txn_session,
                                            holding.id,
                                            action="buy",
                                            shares=shares,
                                            price=cost,
                                            notes=f"建仓自监察表 ({tkr})",
                                        )
                                        update_watchlist_item(
                                            txn_session, item_id, status="converted"
                                        )
                                        _set_flash(
                                            "success",
                                            t("watchlist.convert.success", ticker=tkr),
                                        )
                                        st.rerun()
                                    except Exception as exc:
                                        st.error(
                                            t("watchlist.convert.failed", error=str(exc))
                                        )
                                    finally:
                                        txn_session.close()
                        with col_y:
                            if st.form_submit_button(
                                t("watchlist.convert.cancel"), type="secondary"
                            ):
                                st.session_state.pop(
                                    f"wl_convert_showing_{item.id}", None
                                )
                                st.rerun()

            with cc:
                if st.button(
                    t("watchlist.action.delete"), key=f"wl_delete_{item.id}"
                ):
                    d_session = get_session()
                    try:
                        delete_watchlist_item(d_session, item.id)
                        _set_flash(
                            "success", t("watchlist.delete.success", ticker=item.ticker)
                        )
                        st.rerun()
                    except Exception as exc:
                        _set_flash(
                            "error", t("watchlist.delete.failed", error=str(exc))
                        )
                        st.rerun()
                    finally:
                        d_session.close()
