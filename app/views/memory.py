"""Searchable, source-linked investment memory; inherits the shared app theme."""

import streamlit as st

from app.i18n import t
from common.time import format_display_time
from db.repository import get_session
from memory import retrieval
from memory.capture import SOURCE_TYPES


def render_source(db, ident, as_of=None):
    result = retrieval.read(db, ident, as_of=as_of)
    if result.get("status") != "ok":
        st.info(t("memory.empty"))
        return
    st.subheader(result["title"])
    st.caption(f"{result['evidence_id']} · {result['actor']} · {result['operation']}")
    st.caption(
        f"{t('memory.occurred')}: {format_display_time(result['occurred_at'])} · "
        f"{t('memory.known')}: {format_display_time(result['known_at'])}"
    )
    if result["time_quality"] == "imported":
        st.info(t("memory.imported"))
    # Render the readable immutable source; do not execute raw HTML from reports.
    from db.models import MemoryDocument

    doc = db.get(MemoryDocument, result["version"])
    data = doc.snapshot
    content = (
        data.get("summary")
        or data.get("reasoning")
        or data.get("content")
        or data.get("details")
        or data.get("notes")
        or data.get("watch_reason")
    )
    if content:
        from app.components.kline_chart import render_report

        render_report(str(content), key_prefix=f"memory_{ident}", ui=st)
    with st.expander(t("memory.snapshot"), expanded=not bool(content)):
        st.json(data)
        if doc.previous:
            st.json({"previous": doc.previous})
    if result["related_evidence"]:
        st.caption(t("memory.related"))
        for related in result["related_evidence"]:
            if st.button(
                f"{related['evidence_id']} · {related['title']}",
                key=f"related_{ident}_{related['evidence_id']}",
            ):
                st.query_params["memory"] = related["evidence_id"]
                st.rerun()


def render_memory():
    st.title(t("memory.title"))
    st.caption(t("memory.caption"))
    try:
        with get_session() as db:
            coverage = retrieval.status(db)
        cols = st.columns(3)
        for col, label, value in zip(
            cols,
            ("total", "indexed", "vectors"),
            (
                coverage["total_documents"],
                coverage["indexed_documents"],
                coverage["vector_documents"],
            ),
        ):
            col.metric(t("memory." + label), value)
        if not coverage["backfill_complete"]:
            st.info(t("memory.importing"))
        if coverage["pending_documents"]:
            st.info(t("memory.pending", count=coverage["pending_documents"]))
        if not coverage["vector_configured"]:
            st.caption(t("memory.lexical"))
        elif coverage["vector_documents"] < coverage["indexed_documents"]:
            st.caption(t("memory.vectorpending"))
        if st.button(t("memory.refresh")):
            st.rerun()
        with st.form("memory_search"):
            query = st.text_input(
                t("memory.query"), placeholder=t("memory.placeholder"), max_chars=2000
            )
            left, right = st.columns([1, 2])
            instrument = left.text_input(t("memory.instrument"), placeholder="US:AAPL / CN:020357")
            sources = right.multiselect(
                t("memory.sources"),
                sorted(set(SOURCE_TYPES.values())),
                format_func=lambda x: t("memory.source." + x),
            )
            with st.expander(t("memory.filters")):
                st.caption(t("memory.timehelp"))
                a, b, c = st.columns(3)
                start = a.text_input(t("memory.start"), placeholder="2026-09-01T00:00:00")
                end = b.text_input(t("memory.end"), placeholder="2026-09-30T23:59:59")
                asof = c.text_input(t("memory.asof"), placeholder="2026-10-01T00:00:00")
            search = st.form_submit_button(t("memory.search"), type="primary")
            browse = st.form_submit_button(t("memory.browse"))
        if search or browse:
            options = dict(
                start_at=start or None,
                end_at=end or None,
                as_of=asof or None,
                source_types=sources or None,
            )
            with get_session() as db:
                if browse:
                    result = retrieval.timeline(db, instrument=instrument or None, **options)
                else:
                    result = retrieval.search(
                        db, query, instruments=[instrument] if instrument else None, **options
                    )
            st.session_state["memory_results"] = result
            st.session_state["memory_options"] = dict(instrument=instrument or None, **options)
            st.query_params.pop("memory", None)
        result = st.session_state.get("memory_results")
        if result:
            if result.get("status") == "degraded":
                st.warning(t("memory.degraded"))
            st.caption(t("memory.revisions"))
            if not result["results"]:
                st.info(t("memory.empty"))
            for item in result["results"]:
                with st.container(border=True):
                    st.caption(
                        f"{t('memory.source.' + item['source_type'])} · "
                        f"{format_display_time(item['occurred_at'])} · {item['evidence_id']}"
                    )
                    title = ", ".join(item["instruments"]) or t(
                        "memory.source." + item["source_type"]
                    )
                    if item.get("action"):
                        title += " · " + t("action." + item["action"])
                    st.markdown(f"**{title}**")
                    st.text(item["preview"][:400])
                    if st.button(t("memory.open"), key="open_" + item["evidence_id"]):
                        st.query_params["memory"] = item["evidence_id"]
            if result.get("next_cursor") and st.button(t("memory.more")):
                with get_session() as db:
                    page = retrieval.timeline(
                        db, cursor=result["next_cursor"], **st.session_state["memory_options"]
                    )
                result["results"].extend(page["results"])
                result["next_cursor"] = page["next_cursor"]
                st.rerun()
        ident = st.query_params.get("memory")
        if ident:
            st.divider()
            with get_session() as db:
                render_source(db, ident, st.session_state.get("memory_options", {}).get("as_of"))
    except ValueError as exc:
        st.error(str(exc))
    except Exception:
        st.error(t("memory.error"))


def render() -> None:
    """Render the investment memory workspace."""
    render_memory()


if __name__ == "__main__":
    render()
