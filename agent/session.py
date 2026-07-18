"""Agent session management — tracks each agent activation and its tool calls."""

from datetime import datetime, timezone
from typing import Optional

from db.repository import (
    get_session, create_agent_session, end_agent_session,
    log_tool_call,
)


class AgentSessionManager:
    """Wraps a DB agent session. Records tool calls transparently."""

    def __init__(self, triggered_by: str, news_snapshot: Optional[dict] = None):
        self.triggered_by = triggered_by
        self.news_snapshot = news_snapshot
        self.session_id: Optional[int] = None
        self._tool_call_count = 0

    def start(self) -> int:
        db = get_session()
        try:
            s = create_agent_session(db, self.triggered_by, self.news_snapshot)
            self.session_id = s.id
            return self.session_id
        finally:
            db.close()

    def record_tool_call(self, tool_name: str, params: dict = None, result_summary: str = None):
        if not self.session_id:
            return
        self._tool_call_count += 1
        db = get_session()
        try:
            log_tool_call(db, self.session_id, tool_name, params, result_summary)
        finally:
            db.close()

    def finish(self):
        if self.session_id:
            db = get_session()
            try:
                end_agent_session(db, self.session_id)
            finally:
                db.close()

    def snapshot_news_for_context(self, news_items: list[dict]) -> str:
        """Format recent news into a context string for the agent prompt."""
        if not news_items:
            return "无最新相关新闻。"
        lines = []
        for item in news_items[:10]:
            title = item.get("title", "")
            summary = item.get("summary", "")
            ts = item.get("published_at", "")
            lines.append(f"- [{ts}] {title}")
            if summary:
                lines.append(f"  摘要: {summary}")
        return "\n".join(lines)
