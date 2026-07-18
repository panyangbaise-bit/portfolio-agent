"""Dashboard tables: scheduled jobs + historical agent analysis runs."""

from datetime import datetime

import pandas as pd
import streamlit as st

from app.i18n import enum_label, t
from db.repository import get_session, list_analysis_runs, list_job_runs
from scheduler.cron import get_scheduler_status

JOB_IDS = ("us_after_market", "cn_after_market", "hk_after_market", "crypto_daily", "hourly_news")


def _fmt_time(dt):
    if not dt:
        return "—"
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M")
    return str(dt)[:16]


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


def render_job_schedule_table():
    """Show registered APScheduler jobs and next run times."""
    st.subheader(t("jobs.schedule.title"))
    jobs = get_scheduler_status()
    if not jobs:
        st.caption(t("jobs.schedule.offline"))
        # Still show the known job catalog so the section is never empty.
        catalog = [
            {t("col.job"): enum_label("job", job_id), t("col.id"): job_id, t("col.next_run"): "—"}
            for job_id in JOB_IDS
        ]
        st.dataframe(pd.DataFrame(catalog), use_container_width=True, hide_index=True)
        return

    rows = []
    for j in jobs:
        rows.append({
            t("col.job"): _job_label(j.get("id"), ""),
            t("col.id"): j.get("id", "—"),
            t("col.next_run"): j.get("next_run", "—"),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_analysis_runs_table(limit: int = 50):
    """Show historical agent analysis runs from all jobs."""
    st.subheader(t("jobs.analysis.title"))
    session = get_session()
    try:
        runs = list_analysis_runs(session, limit=limit)
    finally:
        session.close()

    if not runs:
        st.caption(t("jobs.analysis.empty"))
        return

    rows = []
    for r in runs:
        conf = r["max_confidence"]
        rows.append({
            t("col.time"): _fmt_time(r["started_at"]),
            t("col.job"): _job_label(r["job_id"], r["triggered_by"]),
            t("col.market"): enum_label("market", r["market"]) if r["market"] else "—",
            t("col.status"): enum_label("job_status", r["status"]),
            t("col.recs"): r["rec_count"],
            t("col.pending"): r["pending_count"],
            t("col.actions"): r["actions"],
            t("col.max_conf"): f"{conf:.0%}" if conf is not None else "—",
            t("col.summary"): r["summary"],
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


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
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_analysis_section():
    """Scheduled jobs, runtime outcomes, and agent analysis history."""
    render_job_schedule_table()
    st.divider()
    render_job_run_table()
    st.divider()
    render_analysis_runs_table()
