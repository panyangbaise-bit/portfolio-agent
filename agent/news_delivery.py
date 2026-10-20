"""Explicit news delivery decisions and durable event deduplication."""

import hashlib
import html
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated

from langchain.tools import tool
from langgraph.prebuilt import InjectedState

from agent.research import canonical_news_url
from db.models import AgentSession


class NewsReport(str):
    """Keep the report's string API while carrying a separate delivery decision."""

    def __new__(cls, text, decision=None):
        result = super().__new__(cls, text)
        result.decision = decision or {
            "status": "missing",
            "notify": False,
            "reason": "未提供有效通知决策",
        }
        return result


def event_key(item):
    identity = {k: item.get(k) for k in ("title", "summary", "published_at", "related_ticker")}
    for field in ("title", "summary"):
        identity[field] = " ".join(
            html.unescape(re.sub(r"<[^>]*>", "", str(identity[field] or ""))).split()
        )
    identity["url"] = canonical_news_url(item.get("url"))
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def portfolio_signature(holdings):
    rows = sorted((h.market, h.ticker, h.shares, h.cost_basis, h.position_type) for h in holdings)
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def unseen_news(db, items, signature):
    """Only successful recent analyses count; changed holdings invalidate the cache.

    Coverage gaps always remain eligible: absence is not a verified fact, and
    outages must be retried rather than becoming cached 'no news' results.
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    sessions = (
        db.query(AgentSession)
        .filter(
            AgentSession.job_id == "hourly_news",
            AgentSession.status == "completed",
            AgentSession.started_at >= cutoff,
        )
        .order_by(AgentSession.id.desc())
        .limit(48)
        .all()
    )
    seen = set()
    for session in sessions:
        snapshot = session.news_snapshot or {}
        if snapshot.get("processed") and snapshot.get("portfolio_signature") == signature:
            seen.update(snapshot.get("event_keys", []))
    return [
        item for item in items if item.get("category") == "coverage" or event_key(item) not in seen
    ]


@tool
def set_news_notification(
    notify: bool, reason: str, source_ids: list[str], state: Annotated[dict, InjectedState]
) -> dict:
    """新闻任务结束前记录是否值得通知，不直接发消息，也不保存投资建议。

    无新影响/重复观点用 notify=false；新重要风险、催化或需要用户决策才用 true。
    true 必须提供支持变化的本轮 citation 来源ID（不带 [[cite:]]）和具体原因。
    随后仍输出简短文字报告供保存；禁止以报告非空作为通知理由。
    """
    if state.get("triggered_by") != "event":
        return {"error": "not_news_task"}
    if not reason.strip():
        return {"error": "missing_reason"}
    sources = state.get("citation_sources") or {}
    if notify and (not source_ids or any(source not in sources for source in source_ids)):
        return {"error": "missing_evidence", "message": "通知需引用本轮已取得的来源ID"}
    return {
        "status": "recorded",
        "notify": notify,
        "reason": reason.strip()[:1000],
        "source_ids": source_ids,
    }
