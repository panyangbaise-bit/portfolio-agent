"""Agent session management — tracks each agent activation and its tool calls."""

from typing import Optional

from db.repository import (
    get_session,
    create_agent_session,
    end_agent_session,
    log_tool_call,
    reopen_agent_session,
)


class AgentSessionManager:
    """Wraps a DB agent session. Records tool calls transparently."""

    def __init__(
        self,
        triggered_by: str,
        news_snapshot: Optional[dict] = None,
        job_id: Optional[str] = None,
        market: Optional[str] = None,
    ):
        self.triggered_by = triggered_by
        self.news_snapshot = news_snapshot
        self.job_id = job_id
        self.market = market
        self.session_id: Optional[int] = None
        self._tool_call_count = 0
        self._resumed = False

    def start(self) -> int:
        db = get_session()
        try:
            s = create_agent_session(
                db,
                self.triggered_by,
                self.news_snapshot,
                job_id=self.job_id,
                market=self.market,
            )
            self.session_id = s.id
            self._resumed = False
            return self.session_id
        finally:
            db.close()

    def resume(self, session_id: int) -> int:
        """Continue an Ask Agent chat thread on an existing DB session.

        Falls back to ``start()`` if the row is missing or failed.
        """
        db = get_session()
        try:
            s = reopen_agent_session(db, session_id)
            if s is None:
                return self.start()
            self.session_id = s.id
            self._resumed = True
            return self.session_id
        finally:
            db.close()

    def start_or_resume(self, session_id: Optional[int] = None) -> int:
        if session_id:
            return self.resume(session_id)
        return self.start()

    def record_tool_call(self, tool_name: str, params: dict = None, result_summary: str = None):
        if not self.session_id:
            return
        self._tool_call_count += 1
        db = get_session()
        try:
            log_tool_call(db, self.session_id, tool_name, params, result_summary)
        finally:
            db.close()

    def finish(self, summary: str = None):
        if self.session_id:
            db = get_session()
            try:
                end_agent_session(
                    db,
                    self.session_id,
                    summary=summary,
                    status="completed",
                    append_summary=self._resumed,
                )
            finally:
                db.close()

    def fail(self, summary: str = None):
        """Mark session failed (timeout / hard error). Survives a late finish()."""
        if self.session_id:
            db = get_session()
            try:
                end_agent_session(
                    db,
                    self.session_id,
                    summary=summary,
                    status="failed",
                    append_summary=self._resumed,
                )
            finally:
                db.close()

    def snapshot_news_for_context(self, news_items: list[dict]) -> str:
        """Format recent news into a context string for the agent prompt."""
        if not news_items:
            return "无最新相关新闻。"
        lines = []
        for item in news_items[:20]:
            title = item.get("title", "")
            summary = item.get("summary", "")
            ts = item.get("published_at", "")
            category = item.get("category") or "news"
            ticker = item.get("related_ticker")
            tag = category
            if ticker:
                tag = f"{category}:{ticker}"
            lines.append(f"- [{tag}] [{ts}] {title}")
            if summary:
                lines.append(f"  摘要: {summary}")
        return "\n".join(lines)
