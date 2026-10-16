"""Agent core orchestrator — ties together session, graph, and tools."""

import time
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Dict, Iterator, Optional

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

try:
    from langsmith.utils import ContextThreadPoolExecutor as _PoolExecutor
except ImportError:  # pragma: no cover
    from concurrent.futures import ThreadPoolExecutor as _PoolExecutor

from agent.graph import agent_graph
from agent.citations import annotate_sources
from agent.session import AgentSessionManager
from agent.system_prompt import (
    AFTER_MARKET_PROMPT_EXTRA,
    EXIT_ANALYSIS_PROMPT_EXTRA,
    NEWS_TRIGGER_PROMPT_EXTRA,
    TRADE_REVIEW_PROMPT_EXTRA,
)
from adapters.news import news_adapter
from config import config
from db.repository import (
    get_all_holdings,
    get_recent_transactions,
    get_session as get_db_session,
    get_transactions_for_holding,
)


_MARKET_JOB_IDS = {
    "US": "us_after_market",
    "CN": "cn_after_market",
    "HK": "hk_after_market",
    "CRYPTO": "crypto_daily",
}


class AgentRunTimeout(TimeoutError):
    """Raised when a LangGraph invoke exceeds AGENT_RUN_TIMEOUT."""


def _invoke_agent(session: AgentSessionManager, state: dict) -> dict:
    """Run the agent graph with an overall wall-clock timeout.

    On timeout the DB session is marked failed and AgentRunTimeout is raised.
    The worker thread is abandoned (shutdown wait=False); DEEPSEEK_TIMEOUT
    should eventually unblock the hung HTTP read.
    """
    timeout = float(config.AGENT_RUN_TIMEOUT)
    executor = _PoolExecutor(max_workers=1)
    try:
        future = executor.submit(agent_graph.invoke, state)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeout:
            msg = f"Agent run timed out after {timeout:.0f}s"
            session.fail(summary=msg)
            raise AgentRunTimeout(msg)
    finally:
        executor.shutdown(wait=False)


def run_after_market_analysis(market: str) -> str:
    """Run the daily post-market analysis for a given market.

    Called by the scheduler after each market closes.
    Returns a summary string for logging/notifications.
    """
    session = AgentSessionManager(
        triggered_by="schedule",
        job_id=_MARKET_JOB_IDS.get(market, "after_market"),
        market=market,
    )
    session.start()

    market_names = {"US": "美股", "CN": "A股", "HK": "港股", "CRYPTO": "加密货币"}
    market_name = market_names.get(market, market)

    context = AFTER_MARKET_PROMPT_EXTRA.format(market=market_name)
    message = HumanMessage(content=f"请对{market_name}市场的持仓进行盘后分析。")

    result = _invoke_agent(session, {
        "messages": [message],
        "session_id": session.session_id,
        "triggered_by": "schedule",
        "extra_context": context,
    })

    last_msg = result["messages"][-1]
    text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
    session.finish(summary=text)
    return text


def run_news_triggered_analysis(news_items: list[dict]) -> Optional[str]:
    """Run analysis triggered by hourly news polling.

    Analyzes both ticker-related news and market headlines for portfolio impact.
    Returns analysis text or None if no news items were provided.
    """
    if not news_items:
        return None

    session = AgentSessionManager(
        triggered_by="event",
        job_id="hourly_news",
        market=None,
        news_snapshot={"count": len(news_items), "sample": news_items[:8]},
    )
    session.start()

    citation_sources = {}
    cited_news = annotate_sources(news_items[:20], citation_sources)
    summary = session.snapshot_news_for_context(cited_news)
    context = NEWS_TRIGGER_PROMPT_EXTRA.format(news_summary=summary)
    message = HumanMessage(
        content=(
            "请查看最新新闻：既要分析持仓相关新闻，也要评估头条/宏观要闻对组合的影响，"
            "并给出有依据的建议。"
        )
    )

    result = _invoke_agent(session, {
        "messages": [message],
        "session_id": session.session_id,
        "triggered_by": "event",
        "extra_context": context,
        "citation_sources": citation_sources,
    })

    last_msg = result["messages"][-1]
    text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
    session.finish(summary=text)
    return text


def compose_monthly_context(payload: dict, days: int = 31) -> Optional[str]:
    """Build the monthly-summary prompt. None when there is nothing to summarize."""
    if not payload.get("holdings") and not payload.get("trade_lines"):
        return None
    trade_lines = payload.get("trade_lines") or []
    trade_summary = "\n".join(trade_lines) if trade_lines else "近窗口无成交。"
    closed_lines = payload.get("closed_lines") or []
    closed_summary = "\n".join(closed_lines) if closed_lines else "本月无清仓。"
    holding_lines = payload.get("holding_lines") or []
    holding_summary = "\n".join(holding_lines) if holding_lines else "无持仓。"
    return TRADE_REVIEW_PROMPT_EXTRA.format(
        days=days,
        return_summary=payload.get("return_summary") or "总收益暂不可用。",
        holding_summary=holding_summary,
        trade_summary=trade_summary,
        closed_summary=closed_summary,
    )


def _load_monthly_inputs(days: int) -> dict:
    """Snapshot holdings, the review window, and the shared return figures."""
    from agent.tools import _get_return_summary_inner

    summary = _get_return_summary_inner()
    db = get_db_session()
    try:
        holdings = get_all_holdings(db)
        recent = get_recent_transactions(db, days=days)
        positions = summary.get("positions") or [] if isinstance(summary, dict) else []
        by_id = {row.get("holding_id"): row for row in positions}
        holding_lines = []
        for holding in holdings:
            holding_lines.append(
                f"- {holding.ticker} {holding.market} {holding.status} "
                f"{holding.position_type} shares={holding.shares}"
            )
        trade_lines = []
        closed_ids = set()
        for txn in recent:
            holding = txn.holding
            ticker = holding.ticker if holding else "?"
            ts = txn.date.strftime("%Y-%m-%d") if txn.date else "—"
            note = f" | {txn.notes}" if txn.notes else ""
            trade_lines.append(
                f"- [{ts}] {ticker} {txn.action} {txn.shares} @ {txn.price}{note}"
            )
            if (
                holding
                and (txn.action or "").lower() == "sell"
                and (holding.status or "") == "closed"
            ):
                closed_ids.add(holding.id)
        closed_lines = []
        for holding_id in sorted(closed_ids):
            row = by_id.get(holding_id) or {}
            closed_lines.append(
                f"- {row.get('ticker', holding_id)} {row.get('market', '')} "
                f"realized {row.get('realized_pnl')} "
                f"(¥{row.get('realized_pnl_cny')})"
            )
        if isinstance(summary, dict) and summary.get("error"):
            return_summary = summary["error"]
        elif isinstance(summary, dict):
            return_summary = (
                f"市值 ¥{summary.get('market_value_cny')}，"
                f"累计买入 ¥{summary.get('invested_cny')}，"
                f"已实现 ¥{summary.get('realized_pnl_cny')}，"
                f"持仓浮动 ¥{summary.get('unrealized_pnl_cny')}，"
                f"总收益 ¥{summary.get('total_pnl_cny')} "
                f"({summary.get('total_pnl_pct')}%)"
            )
        else:
            return_summary = "总收益暂不可用。"
        return {
            "holdings": holding_lines,
            "holding_lines": holding_lines,
            "trade_lines": trade_lines,
            "closed_lines": closed_lines,
            "return_summary": return_summary,
        }
    finally:
        db.close()


def run_trade_review_analysis(days: int = 31) -> Optional[str]:
    """Monthly portfolio summary. Returns None only when there is nothing to review."""
    context = compose_monthly_context(_load_monthly_inputs(days), days=days)
    if context is None:
        return None

    session = AgentSessionManager(
        triggered_by="schedule",
        job_id="monthly_trade_review",
        market=None,
    )
    session.start()

    message = HumanMessage(
        content="请写月度总结：总收益、仓位、本月成交与清仓，以及建议执行情况。没有成交也要评价当前组合。"
    )

    result = _invoke_agent(session, {
        "messages": [message],
        "session_id": session.session_id,
        "triggered_by": "schedule",
        "extra_context": context,
    })

    last_msg = result["messages"][-1]
    text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
    session.finish(summary=text)
    return text


def build_exit_context(
    ticker: str,
    market: str,
    position_type: str,
    ledger: str,
    realized: float,
    currency: str,
    realized_cny,
) -> str:
    """Prompt for a sold-out position. The model is told not to save a recommendation."""
    return EXIT_ANALYSIS_PROMPT_EXTRA.format(
        ticker=ticker,
        market=market,
        position_type=position_type,
        ledger=ledger or "无流水。",
        realized=f"{realized:+.2f}",
        currency=currency,
        realized_cny=realized_cny,
    )


def run_exit_analysis(holding_id: int, txn_id: int) -> str:
    """Review one fully exited holding. Raises if the holding is missing."""
    from app.components.portfolio_valuation import position_pnl
    from app.fx import currency_for_market, get_cny_rates
    from db.models import Holding

    db = get_db_session()
    try:
        holding = db.query(Holding).filter(Holding.id == holding_id).first()
        if not holding:
            raise ValueError(f"Holding not found: {holding_id}")
        txns = get_transactions_for_holding(db, holding.id)
        ticker = holding.ticker
        market = holding.market
        position_type = holding.position_type
        leg = position_pnl(holding, txns, holding.cost_basis)
        lines = []
        for txn in sorted(txns, key=lambda row: row.id or 0):
            ts = txn.date.strftime("%Y-%m-%d") if txn.date else "—"
            note = f" | {txn.notes}" if txn.notes else ""
            lines.append(f"- [{ts}] {txn.action} {txn.shares} @ {txn.price}{note}")
        currency = currency_for_market(market)
        rates = get_cny_rates((market,))
        rate = rates.get(market.upper())
        realized_cny = round(leg["realized"] * rate, 2) if rate is not None else "—"
        context = build_exit_context(
            ticker,
            market,
            position_type,
            "\n".join(lines),
            leg["realized"],
            currency,
            realized_cny,
        )
    finally:
        db.close()

    session = AgentSessionManager(
        triggered_by="event",
        job_id="exit_analysis",
        market=market,
    )
    session.start()
    message = HumanMessage(
        content=f"请复盘 {ticker} 的清仓（成交 #{txn_id}）。只给文字结论，不要 save_recommendation。"
    )
    result = _invoke_agent(session, {
        "messages": [message],
        "session_id": session.session_id,
        "triggered_by": "event",
        "extra_context": context,
    })
    last_msg = result["messages"][-1]
    text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
    session.finish(summary=text)
    return text


def _chunk_text(content: Any) -> str:
    """Normalize LangChain message content to a plain string delta."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content)


def _iter_answer_chunks(text: str, size: int = 48) -> Iterator[str]:
    """Yield answer text in small chunks for Streamlit write_stream UX."""
    if not text:
        return
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _trim_ask_agent_history(history: list, max_turns: int) -> list:
    """Keep the last ``max_turns`` user/assistant pairs for Ask Agent context."""
    if max_turns <= 0 or not history:
        return []
    trimmed = list(history[-(max_turns * 2) :])
    while trimmed and (trimmed[0].get("role") or "").strip().lower() != "user":
        trimmed = trimmed[1:]
    return trimmed


def run_ad_hoc_query_stream(
    question: str,
    history: Optional[list] = None,
    session_id: Optional[int] = None,
    job_id: str = "ask_agent",
    triggered_by: str = "manual",
    read_only: bool = False,
) -> Iterator[Dict[str, Any]]:
    """Stream Ask Agent progress for the floating chat (status + token events).

    Yields dicts:
      {"type": "status", "text": "..."}  — tool / node progress
      {"type": "token", "text": "..."}   — assistant answer deltas
      {"type": "done", "text": "...", "session_id": int}  — final answer
      {"type": "error", "text": "...", "session_id": int?}  — failure / timeout

    ``history`` is prior completed turns as ``{role, content}`` dicts
    (``user`` / ``assistant``). The current ``question`` is appended as a new
    HumanMessage and is not duplicated inside ``history``.

    ``session_id`` reuses an existing ``agent_sessions`` row so multi-turn Ask
    Agent follow-ups appear as one Jobs history record. Omit / None to create.

    Uses LangGraph ``stream_mode=["updates", "messages"]``. DeepSeek thinking
    mode keeps ``agent_node`` on ``invoke``; token events come from message
    chunks when available, otherwise the final agent update is chunked for UI.
    """
    session = AgentSessionManager(triggered_by=triggered_by, job_id=job_id)
    session.start_or_resume(session_id)
    session.record_message("user", question)

    max_turns = int(config.ASK_AGENT_HISTORY_TURNS)
    trimmed = _trim_ask_agent_history(history or [], max_turns)

    prior = []
    for turn in trimmed:
        if not isinstance(turn, dict):
            continue
        role = (turn.get("role") or "").strip().lower()
        content = turn.get("content") or ""
        if not content:
            continue
        if role == "user":
            prior.append(HumanMessage(content=content))
        elif role == "assistant":
            prior.append(AIMessage(content=content))

    from agent.access import EXTERNAL_QUERY_CONTEXT
    state = {
        "messages": prior + [HumanMessage(content=question)],
        "session_id": session.session_id,
        "triggered_by": triggered_by,
        "extra_context": EXTERNAL_QUERY_CONTEXT if read_only else "",
        "read_only": read_only,
    }

    timeout = float(config.AGENT_RUN_TIMEOUT)
    deadline = time.monotonic() + timeout
    final_text = ""
    got_message_stream = False
    sid = session.session_id

    try:
        for mode, chunk in agent_graph.stream(
            state, stream_mode=["updates", "messages"]
        ):
            if time.monotonic() > deadline:
                msg = f"Agent run timed out after {timeout:.0f}s"
                session.fail(summary=f"Q: {question}\nA: {msg}")
                yield {"type": "error", "text": msg, "session_id": sid}
                return

            if mode == "messages":
                msg_chunk, _metadata = chunk
                if not isinstance(msg_chunk, (AIMessageChunk, AIMessage)):
                    continue
                if getattr(msg_chunk, "tool_call_chunks", None) or getattr(
                    msg_chunk, "tool_calls", None
                ):
                    continue
                delta = _chunk_text(getattr(msg_chunk, "content", ""))
                if not delta:
                    continue
                got_message_stream = True
                final_text += delta
                yield {"type": "token", "text": delta}
                continue

            if mode != "updates" or not isinstance(chunk, dict):
                continue

            if "tools" in chunk:
                tool_msgs = (chunk.get("tools") or {}).get("messages") or []
                for tm in tool_msgs:
                    name = getattr(tm, "name", None) or "tool"
                    yield {"type": "status", "text": f"🔧 {name}"}

            if "agent" not in chunk:
                continue
            agent_msgs = (chunk.get("agent") or {}).get("messages") or []
            for msg in agent_msgs:
                tool_calls = getattr(msg, "tool_calls", None) or []
                if tool_calls:
                    names = []
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            names.append(tc.get("name") or "tool")
                        else:
                            names.append(getattr(tc, "name", None) or "tool")
                    yield {"type": "status", "text": "→ " + ", ".join(names)}
                    continue

                content = _chunk_text(getattr(msg, "content", ""))
                if not content:
                    continue
                final_text = content
                if not got_message_stream:
                    for piece in _iter_answer_chunks(content):
                        yield {"type": "token", "text": piece}

        turn_summary = f"Q: {question}\nA: {final_text or '(empty)'}"
        session.finish(summary=turn_summary)
        yield {"type": "done", "text": final_text, "session_id": sid}
    except Exception as exc:
        session.fail(summary=f"Q: {question}\nA: {exc}")
        yield {"type": "error", "text": str(exc), "session_id": sid}


def run_ad_hoc_query(question: str) -> str:
    """Run agent analysis for a user's ad-hoc question from the dashboard.

    Collects the streamed Ask Agent output into a single string (tests / callers
    that do not need progressive UI).
    """
    final = ""
    for event in run_ad_hoc_query_stream(question):
        if event["type"] == "done":
            final = event.get("text") or final
        elif event["type"] == "error":
            text = event.get("text") or "Ask Agent failed"
            if "timed out" in text.lower():
                raise AgentRunTimeout(text)
            raise RuntimeError(text)
    return final


def poll_news_for_portfolio(tickers: list[str]) -> list[dict]:
    """Hourly news poll: ticker news + market headlines / latest wire.

    Args:
        tickers: List of ticker symbols from the portfolio

    Returns:
        Combined list of news articles (category: ticker | headline)
    """
    all_news = []
    seen = set()

    def _add(article: dict, category: str, related_ticker: Optional[str] = None) -> None:
        key = article.get("title", "")
        if not key or key in seen:
            return
        seen.add(key)
        item = dict(article)
        item["category"] = category
        if related_ticker:
            item["related_ticker"] = related_ticker
        all_news.append(item)

    for article in news_adapter.get_headlines(10):
        _add(article, "headline")
    for article in news_adapter.get_latest_news(10):
        _add(article, "headline")

    for ticker in tickers:
        for article in news_adapter.search_ticker_news(ticker, days=1):
            _add(article, "ticker", related_ticker=ticker)

    return all_news
