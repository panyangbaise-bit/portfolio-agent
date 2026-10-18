"""Capture immutable business snapshots in the same transaction as the write."""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

_INSTALLED = False
SOURCE_TYPES = {
    "holdings": "holding",
    "transactions": "transaction",
    "recommendations": "recommendation",
    "user_actions": "feedback",
    "agent_sessions": "analysis",
    "job_runs": "run",
    "watchlist_items": "watchlist",
    "trading_discipline": "discipline",
    "conversation_messages": "message",
    "news_articles": "news",
    "financial_reports": "financial",
}


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def scalar(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def snapshot(obj):
    return {c.key: scalar(getattr(obj, c.key)) for c in inspect(obj).mapper.column_attrs}


def _date(value, fallback):
    if not value:
        return fallback
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def build_document(conn, obj, operation, previous=None, actor=None, backfill=False):
    from db.models import AgentSession, Holding, JobRun, MemoryDocument, Recommendation

    source = SOURCE_TYPES.get(obj.__tablename__)
    if source is None:
        return None
    data = snapshot(obj)
    # Running sessions are not yet a report. Conversations use individual messages.
    if source == "analysis":
        if not data.get("summary") and not data.get("news_snapshot"):
            return None
        if data.get("job_id") in ("ask_agent", "a2a") and not backfill:
            return None
    if source == "run" and data.get("status") == "running":
        return None
    now = utcnow()
    relations = []
    ticker, market, name = data.get("ticker"), data.get("market"), data.get("name")

    def related(model, ident, kind):
        if not ident:
            return {}
        relations.append({"source_type": kind, "source_id": ident})
        row = conn.execute(select(model.__table__).where(model.id == ident)).mappings().first()
        return dict(row) if row else {}

    if source == "transaction":
        holding = related(Holding, data.get("holding_id"), "holding")
        ticker, market, name = holding.get("ticker"), holding.get("market"), holding.get("name")
    if source == "feedback":
        rec = related(Recommendation, data.get("recommendation_id"), "recommendation")
        ticker = rec.get("ticker")
        sess = related(AgentSession, rec.get("session_id"), "analysis")
        market = sess.get("market")
    elif data.get("session_id"):
        sess = related(AgentSession, data["session_id"], "analysis")
        market = market or sess.get("market")
    if ticker and not market:
        markets = list(
            conn.execute(
                select(Holding.market).where(Holding.ticker == ticker).distinct()
            ).scalars()
        )
        if len(markets) == 1:
            market = markets[0]
    if source == "analysis" and data.get("job_run_id"):
        related(JobRun, data["job_run_id"], "run")
    if source == "run":
        for session_id in conn.execute(
            select(AgentSession.id).where(AgentSession.job_run_id == obj.id)
        ).scalars():
            relations.append({"source_type": "analysis", "source_id": session_id})
    instruments = [f"{market or '?'}:{str(ticker).upper()}"] if ticker else []
    # Reports may cover many markets. Match exact codes / known names, never guess market.
    if source in ("analysis", "run", "message"):
        import re

        content = str(data.get("summary") or data.get("details") or data.get("content") or "")
        from db.models import WatchlistItem

        for model in (Holding, WatchlistItem):
            for row in conn.execute(select(model.ticker, model.market, model.name)):
                if re.search(r"(?<![\w])" + re.escape(row.ticker) + r"(?![\w])", content, re.I) or (
                    row.name and row.name in content
                ):
                    instruments.append(f"{row.market}:{row.ticker.upper()}")
    data["instrument_ticker"] = ticker
    data["instrument_market"] = market
    if name:
        data["instrument_name"] = name
    occurred = _date(
        data.get("date")
        or data.get("acted_at")
        or data.get("published_at")
        or data.get("report_date")
        or data.get("created_at")
        or data.get("started_at")
        or data.get("updated_at"),
        now,
    )
    if operation in ("update", "delete"):
        occurred = now
    # Imported historical mutable records cannot prove when this version was known.
    # Use import time conservatively, never leak hindsight into an as_of query.
    known = now
    quality = "imported" if backfill else "recorded"
    actor = actor or (
        "agent"
        if source in ("analysis", "recommendation")
        else "system"
        if source in ("run", "news", "financial")
        else data.get("role", "user")
        if source == "message"
        else "user"
    )
    title = f"{source} #{obj.id} · {ticker or data.get('job_id') or ''} · {data.get('action') or data.get('status') or operation}"
    labels = {
        "feedback": "用户反馈 拒绝 忽略 接受",
        "discipline": "交易纪律 规则",
        "transaction": "交易 买入 卖出",
        "analysis": "分析 报告 复盘",
        "watchlist": "关注 观察",
    }
    render_data = dict(data)
    # The run is a status record; report text has a canonical analysis source.
    if source == "run" and any(r["source_type"] == "analysis" for r in relations):
        render_data.pop("details", None)
    body = (
        labels.get(source, source)
        + "\n\n"
        + "\n\n".join(
            f"{key}: {json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else value}"
            for key, value in render_data.items()
            if value is not None
        )
    )
    # Raw snapshot retains exact values, including the duplicate run output.

    if previous:
        body += "\nPrevious values / 变更前：\n" + json.dumps(
            previous, ensure_ascii=False, default=str
        )
    # Legacy run/session rows have no durable join. Collapse exact duplicate
    # report text during retrieval without inventing an invocation relationship.
    fingerprint = (
        (data.get("summary") or data.get("details")) if source in ("analysis", "run") else None
    )
    return MemoryDocument(
        source_type=source,
        source_id=obj.id,
        operation=operation,
        actor=actor,
        title=title,
        body=body,
        snapshot=data,
        previous=previous,
        instruments=sorted(set(instruments)),
        relations=relations,
        occurred_at=occurred,
        known_at=known,
        time_quality=quality,
        content_hash=hashlib.sha256((fingerprint or body).strip().encode()).hexdigest(),
    )


def _capture(session, flush_context):
    if session.info.get("skip_memory_capture"):
        return
    conn = session.connection()
    # after_flush: inserted IDs and server defaults are available; histories remain.
    for group, operation in (
        (session.new, "create"),
        (session.dirty, "update"),
        (session.deleted, "delete"),
    ):
        for obj in list(group):
            if getattr(obj, "__tablename__", "") not in SOURCE_TYPES:
                continue
            if operation == "update" and not session.is_modified(obj, include_collections=False):
                continue
            previous = {}
            if operation == "update":
                for attr in inspect(obj).mapper.column_attrs:
                    history = inspect(obj).attrs[attr.key].history
                    if history.has_changes() and history.deleted:
                        previous[attr.key] = scalar(history.deleted[0])
            doc = build_document(
                conn, obj, operation, previous or None, session.info.get("memory_actor")
            )
            if doc:
                session.add(doc)


def install_capture():
    global _INSTALLED
    if not _INSTALLED:
        event.listen(Session, "after_flush", _capture)
        _INSTALLED = True
