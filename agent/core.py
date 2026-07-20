"""Agent core orchestrator — ties together session, graph, and tools."""

from typing import Optional

from langchain_core.messages import HumanMessage

from agent.graph import agent_graph
from agent.session import AgentSessionManager
from agent.system_prompt import (
    AFTER_MARKET_PROMPT_EXTRA,
    NEWS_TRIGGER_PROMPT_EXTRA,
    TRADE_REVIEW_PROMPT_EXTRA,
)
from adapters.news import news_adapter
from db.repository import get_recent_transactions, get_session as get_db_session


_MARKET_JOB_IDS = {
    "US": "us_after_market",
    "CN": "cn_after_market",
    "HK": "hk_after_market",
    "CRYPTO": "crypto_daily",
}


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

    result = agent_graph.invoke({
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

    summary = session.snapshot_news_for_context(news_items)
    context = NEWS_TRIGGER_PROMPT_EXTRA.format(news_summary=summary)
    message = HumanMessage(
        content=(
            "请查看最新新闻：既要分析持仓相关新闻，也要评估头条/宏观要闻对组合的影响，"
            "并给出有依据的建议。"
        )
    )

    result = agent_graph.invoke({
        "messages": [message],
        "session_id": session.session_id,
        "triggered_by": "event",
        "extra_context": context,
    })

    last_msg = result["messages"][-1]
    text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
    session.finish(summary=text)
    return text


def run_trade_review_analysis(days: int = 31) -> Optional[str]:
    """Review recent buy/sell operations. Returns None if there are no trades."""
    db = get_db_session()
    try:
        txns = get_recent_transactions(db, days=days)
        if not txns:
            return None
        lines = []
        for txn in txns:
            holding = txn.holding
            ticker = holding.ticker if holding else "?"
            ts = txn.date.strftime("%Y-%m-%d") if txn.date else "—"
            note = f" | {txn.notes}" if txn.notes else ""
            lines.append(
                f"- [{ts}] {ticker} {txn.action} {txn.shares} @ {txn.price}{note}"
            )
        trade_summary = "\n".join(lines)
    finally:
        db.close()

    session = AgentSessionManager(
        triggered_by="schedule",
        job_id="monthly_trade_review",
        market=None,
    )
    session.start()

    context = TRADE_REVIEW_PROMPT_EXTRA.format(
        days=days,
        trade_summary=trade_summary,
    )
    message = HumanMessage(
        content="请复盘近期投资操作日志，评估买卖时机与仓位纪律，必要时给出调整建议。"
    )

    result = agent_graph.invoke({
        "messages": [message],
        "session_id": session.session_id,
        "triggered_by": "schedule",
        "extra_context": context,
    })

    last_msg = result["messages"][-1]
    text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
    session.finish(summary=text)
    return text


def run_ad_hoc_query(question: str) -> str:
    """Run agent analysis for a user's ad-hoc question from the dashboard.

    Args:
        question: The user's free-text question

    Returns:
        Agent's response text
    """
    session = AgentSessionManager(triggered_by="manual", job_id="ask_agent")
    session.start()

    message = HumanMessage(content=question)

    result = agent_graph.invoke({
        "messages": [message],
        "session_id": session.session_id,
        "triggered_by": "manual",
        "extra_context": "",
    })

    last_msg = result["messages"][-1]
    text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
    session.finish(summary=text)
    return text


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
