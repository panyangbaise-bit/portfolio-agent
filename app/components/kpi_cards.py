import html

import streamlit as st
from app.i18n import t
from app.icons import icon
from db.repository import (
    get_all_holdings,
    get_open_holdings,
    get_pending_recommendations,
    get_session,
    list_transactions,
)
from app.components.currency import fetch_cny_rates
from app.components.price_fetcher import fetch_prices_batch
from app.components.portfolio_valuation import calculate_portfolio_totals


def _signed_cny(amount: float) -> str:
    sign = "+" if amount >= 0 else "-"
    return f"{sign}¥{abs(amount):,.2f}"


def _pnl_tone(amount: float) -> str:
    if amount > 0:
        return "gain"
    if amount < 0:
        return "loss"
    return "flat"


def _return_split_html(realized: float, unrealized: float) -> str:
    """Cyberpunk footer inside the Total Return card (not a caption below it)."""
    return (
        '<div class="split">'
        '<div class="split-row">'
        '<span class="split-label">' + html.escape(t("kpi.realized")) + "</span>"
        '<span class="split-amt ' + _pnl_tone(realized) + '">'
        + html.escape(_signed_cny(realized))
        + "</span>"
        "</div>"
        '<div class="split-row">'
        '<span class="split-label">' + html.escape(t("kpi.open")) + "</span>"
        '<span class="split-amt ' + _pnl_tone(unrealized) + '">'
        + html.escape(_signed_cny(unrealized))
        + "</span>"
        "</div>"
        "</div>"
    )


def render_kpi_cards(holdings=None, prices=None, cny_rates=None):
    """Render KPI cards and return the shared holdings/price snapshot."""
    session = get_session()
    try:
        if holdings is None:
            holdings = get_open_holdings(session)
        all_holdings = get_all_holdings(session)
        transactions = list_transactions(session)
        pending = get_pending_recommendations(session)
    finally:
        session.close()

    if prices is None:
        prices = fetch_prices_batch(holdings)
    needed = tuple(sorted({h.market for h in all_holdings}))
    have = {market.upper() for market in (cny_rates or {})}
    if cny_rates is None or any(market.upper() not in have for market in needed):
        cny_rates = fetch_cny_rates(needed)
    totals = calculate_portfolio_totals(
        all_holdings, prices, cny_rates, transactions
    )

    cols = st.columns(4)
    with cols[0]:
        if totals is None:
            st.metric(t("kpi.total_value"), "—")
        else:
            pnl = totals["pnl"]
            st.metric(
                t("kpi.total_value"),
                f"¥{totals['market_value']:,.2f}",
                delta=f"+¥{pnl:,.2f}" if pnl >= 0 else f"-¥{abs(pnl):,.2f}",
                delta_color="normal",
            )
    with cols[1]:
        if totals is None:
            label = t("kpi.total_return")
            pnl_pct = None
        else:
            label = t("kpi.total_return")
            pnl_pct = totals["pnl_pct"]
        if pnl_pct is not None and pnl_pct > 0:
            tone = "gain"
        elif pnl_pct is not None and pnl_pct < 0:
            tone = "loss"
        else:
            tone = "flat"
        value = f"{pnl_pct:+.2f}%" if pnl_pct is not None else "—"
        split = ""
        if totals is not None:
            split = _return_split_html(
                totals["realized_pnl"], totals["unrealized_pnl"]
            )
        st.html(
            '<div class="cp-pnl-metric">'
            '<div class="label">' + html.escape(label) + "</div>"
            '<div class="value ' + tone + '">' + html.escape(value) + "</div>"
            + split
            + "</div>"
        )
    if totals is None:
        st.warning(t("kpi.fx_unavailable"))
    with cols[2]:
        pending_tone = "pa-tone-warn" if pending else "pa-tone-flat"
        pending_icon = "warning" if pending else "check"
        st.html(
            '<div class="cp-pnl-metric">'
            '<div class="label">' + html.escape(t("kpi.pending_recs")) + "</div>"
            '<div class="value pa-kpi-value ' + pending_tone + '">'
            + icon(pending_icon)
            + html.escape(str(len(pending)))
            + "</div></div>"
        )
    with cols[3]:
        high_urgency = [r for r in pending if r.urgency == "high"]
        if high_urgency:
            risk, risk_icon, risk_tone = t("risk.high"), "warning", "pa-tone-loss"
        elif pending:
            risk, risk_icon, risk_tone = t("risk.moderate"), "hold", "pa-tone-warn"
        else:
            risk, risk_icon, risk_tone = t("risk.low"), "safe", "pa-tone-gain"
        st.html(
            '<div class="cp-pnl-metric">'
            '<div class="label">' + html.escape(t("kpi.risk_level")) + "</div>"
            '<div class="value pa-kpi-value ' + risk_tone + '">'
            + icon(risk_icon)
            + html.escape(risk)
            + "</div></div>"
        )

    return holdings, prices
