"""Dashboard tables: scheduled jobs, runtime log, and agent session detail."""

import json

import pandas as pd
import streamlit as st

from app.i18n import enum_label, t
from app.timeutil import format_display_time
from config import config
from scheduler.cron_text import describe_cron
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

JOB_IDS = (
    "us_after_market",
    "cn_after_market",
    "hk_after_market",
    "crypto_daily",
    "hourly_news",
    "monthly_trade_review",
)

# Job | Schedule | Next Run | Run Now
_SCHEDULE_COLS = [2.4, 3.4, 2.2, 1.6]


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
    """Show the latest monthly summary above the schedule table."""
    st.subheader(t("jobs.monthly.title"))
    session = get_session()
    try:
        summary = latest_job_summary(session, "monthly_trade_review")
    finally:
        session.close()
    if summary:
        st.markdown(summary)
    else:
        st.caption(t("jobs.monthly.empty"))


def render_job_schedule_table():
    """Show registered APScheduler jobs with Run Now in the last column."""
    st.subheader(t("jobs.schedule.title"))
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
    else:
        st.caption(t("jobs.schedule.offline"))
        rows = [_schedule_row(job_id, None) for job_id in JOB_IDS]

    header = st.columns(_SCHEDULE_COLS)
    header[0].markdown(f"**{t('col.job')}**")
    header[1].markdown(f"**{t('col.schedule')}**")
    header[2].markdown(f"**{t('col.next_run')}**")
    header[3].markdown(f"**{t('col.trigger')}**")

    for row in rows:
        cols = st.columns(_SCHEDULE_COLS)
        cols[0].write(row["job"])
        cols[1].write(row["schedule"])
        cols[1].caption(row["crontab"])
        cols[2].write(row["next_run"])
        with cols[3]:
            _render_trigger_cell(row["id"])

    _render_news_crontab_editor()


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
    st.markdown(f"**{t('jobs.news_cron.title')}**")
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
    """Browse agent sessions with summary, saved recommendations, and tool calls."""
    st.subheader(t("jobs.detail.title"))

    filter_options = [""] + list(JOB_IDS) + ["ask_agent", "exit_analysis", "a2a"]
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
                # recommendation.reasoning is the saved decision rationale (not DeepSeek thinking)
                if rec.get("reasoning"):
                    st.write(rec["reasoning"])

    st.markdown(f"**{t('jobs.detail.tools')}**")
    tools = detail.get("tool_calls") or []
    if not tools:
        st.caption(t("jobs.detail.tools_empty"))
        return

    for i, call in enumerate(tools, start=1):
        title = f"{i}. {call['tool_name']} · {_fmt_time(call['called_at'])}"
        with st.expander(title, expanded=False):
            st.markdown(f"**{t('col.params')}**")
            st.code(_format_params(call.get("params")), language="json")
            st.markdown(f"**{t('col.result')}**")
            result = call.get("result_summary") or "—"
            st.text(result)


def render_analysis_section():
    """Scheduled jobs, runtime outcomes, and agent session detail."""
    render_monthly_summary()
    st.divider()
    render_job_schedule_table()
    st.divider()
    render_job_run_table()
    st.divider()
    render_agent_session_detail()
