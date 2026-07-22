"""Watchlist — track interested stocks before entering positions."""

import streamlit as st
from app.i18n import t
from db.repository import (
    get_session,
    get_watchlist_items,
    create_watchlist_item,
    update_watchlist_item,
    delete_watchlist_item,
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

            # action buttons: Edit reason + Delete
            ca, cb = st.columns(2)
            with ca:
                item_id = item.id
                tkr = item.ticker
                if st.button(t("watchlist.action.edit"), key=f"wl_edit_{item.id}"):
                    st.session_state[f"wl_edit_showing_{item.id}"] = True

                if st.session_state.get(f"wl_edit_showing_{item.id}"):
                    with st.form(key=f"wl_edit_form_{item.id}"):
                        new_reason = st.text_area(
                            t("watchlist.field.reason"),
                            value=item.watch_reason or "",
                            placeholder=t("watchlist.field.reason_placeholder"),
                            key=f"wl_edit_reason_{item.id}",
                        )
                        col_x, col_y = st.columns(2)
                        with col_x:
                            if st.form_submit_button(t("watchlist.edit.submit"), type="primary"):
                                edit_session = get_session()
                                try:
                                    update_watchlist_item(
                                        edit_session,
                                        item_id,
                                        watch_reason=(new_reason or "").strip(),
                                    )
                                    st.session_state.pop(f"wl_edit_showing_{item.id}", None)
                                    _set_flash(
                                        "success",
                                        t("watchlist.edit.success", ticker=tkr),
                                    )
                                    st.rerun()
                                except Exception as exc:
                                    st.error(t("watchlist.edit.failed", error=str(exc)))
                                finally:
                                    edit_session.close()
                        with col_y:
                            if st.form_submit_button(
                                t("watchlist.edit.cancel"), type="secondary"
                            ):
                                st.session_state.pop(f"wl_edit_showing_{item.id}", None)
                                st.rerun()

            with cb:
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
