"""Dashboard tables: scheduled jobs, runtime log, and agent session detail."""

import json

import pandas as pd
import streamlit as st

from app.i18n import enum_label, t
from app.timeutil import format_display_time
from db.repository import (
    get_agent_session_detail,
    get_session,
    list_analysis_runs,
    list_job_runs,
)
from scheduler.cron import (
    clear_manual_run_status,
    get_manual_run_status,
    get_scheduler_status,
    trigger_job,
)

JOB_IDS = (
    "us_after_market",
    "cn_after_market",
    "hk_after_market",
    "crypto_daily",
    "hourly_news",
    "monthly_trade_review",
)

# Job | ID | Next Run | Run Now
_SCHEDULE_COLS = [3, 2, 3, 1.5]


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
    job_label = enum_label("job", job_id)
    run_status = get_manual_run_status(job_id)

    if run_status and run_status["status"] == "running":
        st.button(
            t("jobs.trigger.running"),
            key=f"trigger_{job_id}",
            disabled=True,
            use_container_width=True,
        )
    elif run_status and run_status["status"] == "completed":
        st.success(t("jobs.trigger.completed", job=job_label))
        if st.button("OK", key=f"clear_{job_id}", use_container_width=True):
            clear_manual_run_status(job_id)
            st.rerun()
    elif run_status and run_status["status"] == "failed":
        error_msg = run_status.get("error", "unknown error")
        st.error(t("jobs.trigger.failed", job=job_label, error=error_msg))
        if st.button("OK", key=f"clear_{job_id}", use_container_width=True):
            clear_manual_run_status(job_id)
            st.rerun()
    else:
        if st.button(
            t("jobs.trigger.button"),
            key=f"trigger_{job_id}",
            use_container_width=True,
            type="primary",
        ):
            ok = trigger_job(job_id)
            if ok:
                st.rerun()
            else:
                st.error(t("jobs.trigger.unknown", job_id=job_id))


def render_job_schedule_table():
    """Show registered APScheduler jobs with Run Now in the last column."""
    st.subheader(t("jobs.schedule.title"))
    jobs = get_scheduler_status()

    if jobs:
        rows = [
            {
                "job": _job_label(j.get("id"), ""),
                "id": j.get("id", "—"),
                "next_run": j.get("next_run", "—"),
            }
            for j in jobs
        ]
    else:
        st.caption(t("jobs.schedule.offline"))
        rows = [
            {"job": enum_label("job", job_id), "id": job_id, "next_run": "—"}
            for job_id in JOB_IDS
        ]

    header = st.columns(_SCHEDULE_COLS)
    header[0].markdown(f"**{t('col.job')}**")
    header[1].markdown(f"**{t('col.id')}**")
    header[2].markdown(f"**{t('col.next_run')}**")
    header[3].markdown(f"**{t('col.trigger')}**")

    for row in rows:
        cols = st.columns(_SCHEDULE_COLS)
        cols[0].write(row["job"])
        cols[1].write(row["id"])
        cols[2].write(row["next_run"])
        with cols[3]:
            _render_trigger_cell(row["id"])


def render_job_run_table(limit: int = 50):
    """Show every scheduler invocation, including skipped and failed jobs."""
    st.subheader(t("jobs.runtime.title"))
    session = get_session()
    try:
        runs = list_job_runs(session, limit=limit)
    finally:
        session.close()

    if not runs:
        st.caption(t("jobs.runtime.empty"))
        return

    rows = [
        {
            t("col.time"): _fmt_time(run.started_at),
            t("col.job"): enum_label("job", run.job_id),
            t("col.status"): enum_label("job_status", run.status),
            t("col.details"): run.details or "—",
            t("col.finished"): _fmt_time(run.ended_at),
        }
        for run in runs
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _format_params(params) -> str:
    if not params:
        return "—"
    try:
        return json.dumps(params, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(params)


def render_agent_session_detail(limit: int = 50):
    """Browse agent sessions with summary, recommendation reasoning, and tool calls."""
    st.subheader(t("jobs.detail.title"))

    filter_options = [""] + list(JOB_IDS) + ["ask_agent"]
    job_filter = st.selectbox(
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

    list_rows = [
        {
            t("col.time"): _fmt_time(r["started_at"]),
            t("col.job"): _job_label(r["job_id"], r["triggered_by"]),
            t("col.market"): enum_label("market", r["market"]) if r["market"] else "—",
            t("col.status"): enum_label("job_status", r["status"]),
            t("col.recs"): r["rec_count"],
            t("col.tools"): r.get("tool_count", 0),
            t("col.summary"): r["summary"],
        }
        for r in runs
    ]
    st.dataframe(pd.DataFrame(list_rows), width="stretch", hide_index=True)

    labels = {
        r["id"]: t(
            "jobs.detail.session_label",
            id=r["id"],
            time=_fmt_time(r["started_at"]),
            job=_job_label(r["job_id"], r["triggered_by"]),
        )
        for r in runs
    }
    selected_id = st.selectbox(
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

    st.markdown(f"**{t('jobs.detail.summary')}**")
    if detail.get("summary"):
        st.markdown(detail["summary"])
    else:
        st.caption(t("jobs.detail.summary_empty"))

    st.markdown(f"**{t('jobs.detail.recommendations')}**")
    recs = detail.get("recommendations") or []
    if not recs:
        st.caption(t("jobs.detail.recs_empty"))
    else:
        for rec in recs:
            with st.expander(
                f"{rec['ticker']} — {enum_label('action', rec['action'])} · {rec['confidence']:.0%}",
                expanded=True,
            ):
                st.caption(
                    t(
                        "rec.meta",
                        confidence=f"{rec['confidence']:.0%}",
                        urgency=enum_label("urgency", rec["urgency"]),
                        date=_fmt_time(rec["created_at"]),
                    )
                )
                st.markdown(f"**{t('col.reasoning')}**")
                st.write(rec["reasoning"])

    st.markdown(f"**{t('jobs.detail.tools')}**")
    tools = detail.get("tool_calls") or []
    if not tools:
        st.caption(t("jobs.detail.tools_empty"))
        return

    for i, call in enumerate(tools, start=1):
        title = f"{i}. {call['tool_name']} · {_fmt_time(call['called_at'])}"
        with st.expander(title, expanded=(i == 1)):
            st.markdown(f"**{t('col.params')}**")
            st.code(_format_params(call.get("params")), language="json")
            st.markdown(f"**{t('col.result')}**")
            result = call.get("result_summary") or "—"
            st.text(result)


def render_analysis_section():
    """Scheduled jobs, runtime outcomes, and agent session detail."""
    render_job_schedule_table()
    st.divider()
    render_job_run_table()
    st.divider()
    render_agent_session_detail()
