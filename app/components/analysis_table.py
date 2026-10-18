"""Operations workspace: schedules, execution records, and analysis reports."""

import json
from datetime import timezone

import pandas as pd
import streamlit as st

from app.i18n import enum_label, t
from common.time import format_display_time
from config import config
from db.repository import (
    get_agent_session_detail,
    get_session,
    latest_job_summary,
    list_analysis_runs,
    list_job_runs,
)
from scheduler.cron import (
    clear_manual_run_status,
    get_manual_run_status,
    get_news_crontab,
    get_scheduler_status,
    job_cron,
    trigger_job,
    update_news_crontab,
)
from scheduler.cron_text import describe_cron

JOB_IDS = (
    "us_after_market",
    "cn_after_market",
    "hk_after_market",
    "crypto_daily",
    "hourly_news",
    "monthly_trade_review",
)

# Name and cadence | Next run | Action
_SCHEDULE_COLS = [5, 2.6, 1.6]


def _fmt_time(dt):
    return format_display_time(dt)


def _job_label(job_id, triggered_by):
    if job_id:
        return enum_label("job", job_id)
    if triggered_by == "schedule":
        return t("job.after_market")
    if triggered_by == "event":
        return t("trigger.event")
    if triggered_by == "manual":
        return t("job.ask_agent")
    return triggered_by or "—"


def _render_trigger_cell(job_id: str) -> None:
    """Render the Run Now / status control for one scheduled job."""
    run_status = get_manual_run_status(job_id)

    if run_status and run_status["status"] == "running":
        st.button(
            t("jobs.trigger.running"),
            key=f"trigger_{job_id}",
            disabled=True,
            width="stretch",
        )
    elif run_status and run_status["status"] in ("completed", "skipped", "failed"):
        st.caption(_status_label(run_status["status"]))
        if run_status["status"] == "failed":
            with st.popover(t("jobs.trigger.error_details")):
                st.write(run_status.get("error") or "—")
        if st.button(t("jobs.trigger.reset"), key=f"clear_{job_id}", width="stretch"):
            clear_manual_run_status(job_id)
            st.rerun()
    else:
        if st.button(
            t("jobs.trigger.button"),
            key=f"trigger_{job_id}",
            width="stretch",
            type="secondary",
        ):
            ok = trigger_job(job_id)
            if ok:
                st.rerun()
            else:
                st.error(t("jobs.trigger.unknown", job_id=job_id))


def _schedule_locale() -> str:
    return st.session_state.get("locale", "en")


def _schedule_row(job_id: str, next_run, crontab: str = "", timezone: str = "") -> dict:
    if not crontab:
        crontab, timezone = job_cron(job_id)
    return {
        "job": _job_label(job_id, ""),
        "id": job_id,
        "schedule": describe_cron(crontab, _schedule_locale(), timezone or config.APP_TIMEZONE),
        "crontab": crontab or "—",
        "next_run": format_display_time(next_run) if next_run else "—",
    }


def render_monthly_summary():
    """Keep the full monthly report available without taking over the page."""
    with st.expander(t("jobs.monthly.title"), expanded=False):
        session = get_session()
        try:
            summary = latest_job_summary(session, "monthly_trade_review")
        finally:
            session.close()
        if summary:
            from app.components.kline_chart import render_report

            render_report(summary, key_prefix="monthly", ui=st)
        else:
            st.caption(t("jobs.monthly.empty"))


@st.fragment(run_every=5)
def render_job_schedule_table():
    """Compact job rows; refresh manual-run status without resetting editors."""
    jobs = get_scheduler_status()
    if jobs:
        rows = [
            _schedule_row(
                j.get("id") or "",
                j.get("next_run"),
                j.get("crontab") or "",
                j.get("timezone") or "",
            )
            for j in jobs
        ]
        st.caption(t("jobs.schedule.caption", count=len(rows), timezone=config.APP_TIMEZONE))
    else:
        st.info(t("jobs.schedule.offline"))
        rows = [_schedule_row(job_id, None) for job_id in JOB_IDS]

    for row in rows:
        with st.container(border=True, key=f"job_schedule_{row['id']}"):
            cols = st.columns(_SCHEDULE_COLS, vertical_alignment="center")
            with cols[0]:
                st.markdown(f"**{row['job']}**")
                st.caption(row["schedule"])
            with cols[1]:
                st.caption(t("col.next_run"))
                st.write(row["next_run"])
            with cols[2]:
                _render_trigger_cell(row["id"])


def _on_save_news_crontab():
    """Persist the news crontab from the button callback.

    Streamlit forbids writing a widget key after that widget is created in the
    same run. Callbacks run first, so the cleaned expression can replace the
    input value before the editor is drawn again.
    """
    expr = st.session_state.get("news_crontab_expr", "")
    try:
        cleaned = update_news_crontab(expr)
    except ValueError as exc:
        st.session_state["_news_crontab_notice"] = ("invalid", str(exc))
        return
    st.session_state["news_crontab_expr"] = cleaned
    st.session_state["_news_crontab_notice"] = ("saved", cleaned)


def _render_news_crontab_editor():
    """Allow editing the news poll 5-field crontab (persisted + live reschedule)."""
    st.caption(t("jobs.news_cron.help"))
    if "news_crontab_expr" not in st.session_state:
        st.session_state["news_crontab_expr"] = get_news_crontab()
    expr = st.text_input(
        t("jobs.news_cron.label"),
        key="news_crontab_expr",
    )
    st.caption(describe_cron(expr, _schedule_locale(), config.APP_TIMEZONE))
    st.button(
        t("jobs.news_cron.save"),
        type="primary",
        on_click=_on_save_news_crontab,
    )
    notice = st.session_state.pop("_news_crontab_notice", None)
    if not notice:
        return
    kind, payload = notice
    if kind == "saved":
        st.success(t("jobs.news_cron.saved", expr=payload))
    else:
        st.error(t("jobs.news_cron.invalid", error=payload))


def _duration(started_at, ended_at):
    if not started_at or not ended_at:
        return "—"
    start = started_at.replace(tzinfo=timezone.utc) if started_at.tzinfo is None else started_at
    end = ended_at.replace(tzinfo=timezone.utc) if ended_at.tzinfo is None else ended_at
    seconds = max(0, int((end - start).total_seconds()))
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def _status_label(status):
    marker = {"completed": "✓", "failed": "✕", "running": "●", "skipped": "—"}.get(status, "·")
    return f"{marker} {enum_label('job_status', status)}"


def render_job_run_table(limit: int = 50):
    """A scannable run index; select one row to read its complete output."""
    filters = st.columns([2, 1, 1])
    with filters[0]:
        job_filter = st.selectbox(
            t("jobs.detail.filter_job"),
            [""] + list(JOB_IDS) + ["exit_analysis"],
            format_func=lambda jid: enum_label("job", jid) if jid else t("jobs.detail.filter_all"),
            key="jobs_runtime_job_filter",
        )
    with filters[1]:
        status_filter = st.selectbox(
            t("col.status"),
            ["", "failed", "running", "completed", "skipped"],
            format_func=lambda status: enum_label("job_status", status)
            if status
            else t("jobs.runtime.all_status"),
            key="jobs_runtime_status_filter",
        )
    with filters[2]:
        limit = st.selectbox(
            t("jobs.record_limit"),
            sorted({limit, 50, 100, 200}),
            key="jobs_runtime_limit",
        )

    session = get_session()
    try:
        runs = list_job_runs(
            session, limit=limit, job_id=job_filter or None, status=status_filter or None
        )
    finally:
        session.close()
    if not runs:
        st.info(t("jobs.runtime.no_matches"))
        return

    st.caption(t("jobs.runtime.select_hint", count=len(runs)))
    rows = [
        {
            t("col.time"): _fmt_time(run.started_at),
            t("col.job"): enum_label("job", run.job_id),
            t("col.status"): _status_label(run.status),
            t("jobs.duration"): _duration(run.started_at, run.ended_at),
        }
        for run in runs
    ]
    # Reset row selection when filtering or refreshing changes the row order.
    selection_key = "jobs_runtime_rows_" + "_".join(str(run.id) for run in runs)
    event = st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=selection_key,
        height=min(460, 36 * len(rows) + 40),
    )
    selected = event.selection.rows
    if not selected or selected[0] >= len(runs):
        return
    run = runs[selected[0]]
    with st.container(border=True, key="jobs_run_detail"):
        st.subheader(enum_label("job", run.job_id))
        st.caption(
            f"#{run.id} · {_status_label(run.status)} · {_fmt_time(run.started_at)}"
            f" · {t('col.finished')}: {_fmt_time(run.ended_at)}"
        )
        if run.details:
            from app.components.kline_chart import render_report

            render_report(run.details, key_prefix=f"run_{run.id}", ui=st)
        else:
            st.caption(t("jobs.runtime.no_details"))


def _format_params(params) -> str:
    if not params:
        return "—"
    try:
        return json.dumps(params, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(params)


def render_agent_session_detail(limit: int = 50):
    """Browse agent sessions with summary, saved recommendations, and tool calls."""

    filter_options = [""] + list(JOB_IDS) + ["ask_agent", "exit_analysis", "a2a"]
    filters = st.columns([1, 2])
    job_filter = filters[0].selectbox(
        t("jobs.detail.filter_job"),
        options=filter_options,
        format_func=lambda jid: t("jobs.detail.filter_all") if not jid else enum_label("job", jid),
        key="jobs_detail_job_filter",
    )

    session = get_session()
    try:
        runs = list_analysis_runs(
            session,
            limit=limit,
            job_id=job_filter or None,
        )
    finally:
        session.close()

    if not runs:
        st.caption(t("jobs.detail.empty"))
        return

    labels = {
        r["id"]: t(
            "jobs.detail.session_label",
            id=r["id"],
            time=_fmt_time(r["started_at"]),
            job=_job_label(r["job_id"], r["triggered_by"]),
        )
        for r in runs
    }
    selected_id = filters[1].selectbox(
        t("jobs.detail.select"),
        options=[r["id"] for r in runs],
        format_func=lambda sid: labels.get(sid, str(sid)),
        key="jobs_detail_session_select",
    )

    session = get_session()
    try:
        detail = get_agent_session_detail(session, selected_id)
    finally:
        session.close()

    if not detail:
        st.caption(t("jobs.detail.empty"))
        return

    st.caption(
        t(
            "jobs.detail.metadata",
            status=enum_label("job_status", detail.get("status", "completed")),
            market=enum_label("market", detail["market"]) if detail.get("market") else "—",
            recs=len(detail.get("recommendations") or []),
            tools=len(detail.get("tool_calls") or []),
        )
    )
    summary_tab, recs_tab, tools_tab = st.tabs(
        [
            t("jobs.detail.summary"),
            t("jobs.detail.recommendations"),
            t("jobs.detail.tools"),
        ]
    )
    with summary_tab:
        if detail.get("summary"):
            from app.components.kline_chart import render_report

            render_report(detail["summary"], key_prefix=f"report_{selected_id}", ui=st)
        else:
            st.caption(t("jobs.detail.summary_empty"))
    with recs_tab:
        recs = detail.get("recommendations") or []
        if not recs:
            st.caption(t("jobs.detail.recs_empty"))
        for rec in recs:
            with st.expander(
                f"{rec['ticker']} — {enum_label('action', rec['action'])} · {rec['confidence']:.0%}",
                expanded=False,
            ):
                st.caption(
                    t(
                        "rec.meta",
                        confidence=f"{rec['confidence']:.0%}",
                        urgency=enum_label("urgency", rec["urgency"]),
                        date=_fmt_time(rec["created_at"]),
                    )
                )
                if rec.get("reasoning"):
                    st.write(rec["reasoning"])
    with tools_tab:
        tools = detail.get("tool_calls") or []
        if not tools:
            st.caption(t("jobs.detail.tools_empty"))
        for i, call in enumerate(tools, start=1):
            title = f"{i}. {call['tool_name']} · {_fmt_time(call['called_at'])}"
            with st.expander(title, expanded=False):
                st.markdown(f"**{t('col.params')}**")
                st.code(_format_params(call.get("params")), language="json")
                st.markdown(f"**{t('col.result')}**")
                st.text(call.get("result_summary") or "—")


def render_analysis_section():
    """Render one workspace at a time. Analysis reports open first."""
    navigation, refresh = st.columns([6, 1], vertical_alignment="bottom")
    with navigation:
        section = st.radio(
            t("jobs.navigation"),
            ["reports", "schedule", "runtime"],
            format_func=lambda value: t("jobs.tab." + value),
            horizontal=True,
            label_visibility="collapsed",
            key="jobs_section",
            index=0,
        )
    with refresh:
        if st.button(t("jobs.refresh"), key="jobs_refresh", width="stretch"):
            st.rerun()
    if section == "schedule":
        render_job_schedule_table()
        with st.expander(t("jobs.news_cron.title"), expanded=False):
            _render_news_crontab_editor()
    elif section == "runtime":
        render_job_run_table()
    else:
        render_monthly_summary()
        render_agent_session_detail()
