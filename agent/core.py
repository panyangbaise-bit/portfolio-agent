"""Agent core orchestrator — ties together session, graph, and tools."""

from datetime import datetime
from typing import Optional

from langchain_core.messages import HumanMessage

from agent.graph import agent_graph
from agent.session import AgentSessionManager
from agent.system_prompt import (
    AFTER_MARKET_PROMPT_EXTRA,
    NEWS_TRIGGER_PROMPT_EXTRA,
)
from adapters.news import news_adapter


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

    Only activates if news items appear relevant to holdings.
    Returns analysis text or None if no action needed.
    """
    if not news_items:
        return None

    session = AgentSessionManager(
        triggered_by="event",
        job_id="hourly_news",
        market=None,
        news_snapshot={"count": len(news_items), "sample": news_items[:5]},
    )
    session.start()

    summary = session.snapshot_news_for_context(news_items)
    context = NEWS_TRIGGER_PROMPT_EXTRA.format(news_summary=summary)
    message = HumanMessage(content="请查看最新新闻，判断是否有需要关注的持仓标的，并给出分析。")

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
    """Hourly news poll: search for each ticker, return all matching articles.

    Args:
        tickers: List of ticker symbols from the portfolio

    Returns:
        Combined list of news articles found
    """
    all_news = []
    seen = set()
    for ticker in tickers:
        articles = news_adapter.search_ticker_news(ticker, days=1)
        for a in articles:
            key = a.get("title", "")
            if key and key not in seen:
                seen.add(key)
                a["related_ticker"] = ticker
                all_news.append(a)
    return all_news
