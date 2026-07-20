"""LangChain tool definitions for the portfolio agent.

Each tool wraps an adapter method or DB query, presenting a clean
interface to the LLM. The agent does not know about adapters, markets,
or databases — it just calls these functions.
"""

from typing import Optional

from langchain.tools import tool

from db.repository import (
    get_session, get_open_holdings, get_holding_by_ticker,
    create_recommendation, get_recommendation_history as db_get_rec_history,
    get_recent_transactions, find_similar_recommendation, upsert_price,
)
from adapters.base import registry as adapter_registry
from adapters.news import news_adapter


# ── Portfolio Tools ───────────────────────────────────────

@tool
def get_portfolio() -> list[dict]:
    """获取当前所有持仓列表，包括每个标的的代码、市场、股数、成本价和仓位类型。

    Returns:
        list[dict]: 持仓列表，每项含 ticker, market, shares, cost_basis, position_type, pnl_pct, weight_pct
    """
    session = get_session()
    try:
        holdings = get_open_holdings(session)
        total_value = 0.0
        values = []
        for h in holdings:
            try:
                adapter = adapter_registry.get(h.market)
                price_data = adapter.get_price(h.ticker)
                current_price = price_data.get("price", 0) or 0
            except Exception:
                current_price = h.cost_basis
            market_value = h.shares * current_price
            total_value += market_value
            pnl_pct = ((current_price - h.cost_basis) / h.cost_basis * 100) if h.cost_basis else 0
            values.append({
                "ticker": h.ticker,
                "market": h.market,
                "shares": h.shares,
                "cost_basis": h.cost_basis,
                "current_price": round(current_price, 2),
                "position_type": h.position_type,
                "pnl_pct": round(pnl_pct, 2),
                "market_value": round(market_value, 2),
                "holding_id": h.id,
            })

        for v in values:
            v["weight_pct"] = round(v["market_value"] / total_value * 100, 2) if total_value > 0 else 0

        return values
    finally:
        session.close()


@tool
def get_holding(ticker: str) -> dict:
    """获取单个标的的持仓详情。

    Args:
        ticker: 标的代码，如 AAPL, 600519, 0700.HK, BTC

    Returns:
        dict: 持仓详情，含 ticker, market, shares, cost_basis, position_type, current_price, pnl_pct
    """
    session = get_session()
    try:
        h = get_holding_by_ticker(session, ticker.upper())
        if not h:
            return {"error": f"未找到标的: {ticker}"}
        try:
            adapter = adapter_registry.get(h.market)
            price_data = adapter.get_price(h.ticker)
            current_price = price_data.get("price", 0) or 0
        except Exception:
            current_price = h.cost_basis
        pnl_pct = ((current_price - h.cost_basis) / h.cost_basis * 100) if h.cost_basis else 0
        return {
            "ticker": h.ticker,
            "market": h.market,
            "shares": h.shares,
            "cost_basis": h.cost_basis,
            "current_price": round(current_price, 2),
            "position_type": h.position_type,
            "pnl_pct": round(pnl_pct, 2),
            "holding_id": h.id,
        }
    finally:
        session.close()


# ── Market Data Tools ─────────────────────────────────────

@tool
def get_price(ticker: str, market: str) -> dict:
    """获取标的当前价格和日内变动。

    Args:
        ticker: 标的代码
        market: 市场代码 — US, CN, HK, 或 CRYPTO

    Returns:
        dict: 含 ticker, price, currency, change_pct, volume, timestamp
    """
    adapter = adapter_registry.get(market)
    return adapter.get_price(ticker)


@tool
def get_kline(ticker: str, market: str, period: str = "3mo") -> list[dict]:
    """获取标的历史K线数据。

    Args:
        ticker: 标的代码
        market: 市场代码 — US, CN, HK, 或 CRYPTO
        period: 时间周期 — 1mo, 3mo, 6mo, 1y, 5y

    Returns:
        list[dict]: K线数据列表，每项含 date, open, high, low, close, volume
    """
    adapter = adapter_registry.get(market)
    return adapter.get_kline(ticker, period)


@tool
def get_financials(ticker: str, market: str) -> dict:
    """获取标的最近财报数据，包括营收、EPS、PE、ROE等基本面指标。

    Args:
        ticker: 标的代码
        market: 市场代码 — US, CN, HK, 或 CRYPTO

    Returns:
        dict: 含 ticker, report_date, revenue, revenue_growth, eps, pe_ratio, pb_ratio, roe 等
    """
    adapter = adapter_registry.get(market)
    return adapter.get_financials(ticker)


@tool
def get_fund_info(ticker: str, top_constituents: int = 20) -> dict:
    """获取 A 股基金/ETF/联接基金详情：跟踪指数、费率、资产配置与指数成分股。

    适用于 CN 市场场外基金与 ETF 联接（如 020357）。场内股票请用 get_financials。

    Args:
        ticker: 基金代码，如 020357、510300
        top_constituents: 返回跟踪指数成分股数量上限，默认 20

    Returns:
        dict: name, tracked_index, fees, asset_allocation, constituents, notes 等
    """
    adapter = adapter_registry.get("CN")
    if not hasattr(adapter, "get_fund_info"):
        return {"ticker": ticker, "error": "CN adapter does not support get_fund_info"}
    return adapter.get_fund_info(ticker, top_constituents=top_constituents)


@tool
def get_market_snapshot(market: str) -> dict:
    """获取市场大盘指数概览。

    Args:
        market: 市场代码 — US (S&P 500), CN (上证指数), HK (恒生指数), CRYPTO (总市值)

    Returns:
        dict: 含 index_name, current, change_pct 等
    """
    adapter = adapter_registry.get(market)
    return adapter.get_market_snapshot()


# ── News Tools ────────────────────────────────────────────

@tool
def search_ticker_news(ticker: str, days: int = 7) -> list[dict]:
    """搜索与某个标的相关的最近新闻。

    Args:
        ticker: 标的代码
        days: 搜索最近几天的新闻，默认7天

    Returns:
        list[dict]: 新闻列表，每项含 title, url, summary, published_at
    """
    return news_adapter.search_ticker_news(ticker, days)


@tool
def get_market_headlines() -> list[dict]:
    """获取最新的市场头条和要闻。

    Returns:
        list[dict]: 新闻列表，每项含 title, url, summary, published_at, author
    """
    headlines = news_adapter.get_headlines(10)
    latest = news_adapter.get_latest_news(10)
    seen = set()
    merged = []
    for item in headlines + latest:
        key = item.get("title", "")
        if key and key not in seen:
            seen.add(key)
            merged.append(item)
    return merged[:15]


# ── Recommendation Tools ──────────────────────────────────

@tool
def get_recommendation_history(ticker: Optional[str] = None, limit: int = 20) -> list[dict]:
    """查看近期已保存的投资建议（含 pending / acted / dismissed）。

    在调用 save_recommendation 之前应先查看：若同标的已有相同 action 的
    pending 建议，或近期结论未变，则不要再保存，只在回复中做文字分析即可。

    Args:
        ticker: 可选，指定标的代码来过滤
        limit: 返回条数，默认20

    Returns:
        list[dict]: 历史建议列表
    """
    session = get_session()
    try:
        recs = db_get_rec_history(session, ticker=ticker, limit=limit)
        return [
            {
                "id": r.id,
                "ticker": r.ticker,
                "action": r.action,
                "reasoning": r.reasoning,
                "confidence": r.confidence,
                "urgency": r.urgency,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recs
        ]
    finally:
        session.close()


@tool
def get_trade_history(days: int = 30) -> list[dict]:
    """获取近期投资操作（买入/卖出）流水，用于复盘加减仓记录。

    Args:
        days: 回溯天数，默认 30

    Returns:
        list[dict]: 交易列表，含 ticker, action, shares, price, date, notes
    """
    session = get_session()
    try:
        txns = get_recent_transactions(session, days=days)
        rows = []
        for txn in txns:
            holding = txn.holding
            rows.append({
                "ticker": holding.ticker if holding else None,
                "name": holding.name if holding else None,
                "action": txn.action,
                "shares": txn.shares,
                "price": txn.price,
                "date": txn.date.isoformat() if txn.date else None,
                "notes": txn.notes,
            })
        return rows
    finally:
        session.close()


@tool
def save_recommendation(
    ticker: str,
    action: str,
    reasoning: str,
    confidence: float,
    urgency: str = "low",
    session_id: int = 0,
) -> dict:
    """仅在用户需要决策时保存建议（会出现在待处理列表，需 accept/dismiss）。

    降噪规则（工具会强制执行）：
    - 日常 hold + urgency=low：不落库，只在回复里写分析。
    - 同标的已有相同 action 的 pending，或近 7 天内相同 action+urgency：跳过。
    保存前请先 get_recommendation_history 对照近期结论。

    Args:
        ticker: 标的代码
        action: 建议操作 — buy_add, reduce, hold, watch
        reasoning: 推理链条（2-4句话）
        confidence: 置信度 0.0-1.0
        urgency: 紧迫度 — low, medium, high
        session_id: agent会话ID（自动传入，无需手动填写）

    Returns:
        dict: status=saved | skipped_routine | skipped_unchanged
    """
    action_n = (action or "").strip().lower()
    urgency_n = (urgency or "low").strip().lower()

    if action_n == "hold" and urgency_n == "low":
        return {
            "status": "skipped_routine",
            "ticker": (ticker or "").upper(),
            "action": action_n,
            "urgency": urgency_n,
            "message": "日常 hold 不写入待处理建议；请在回复中给出文字分析即可。",
        }

    db_session = get_session()
    try:
        similar = find_similar_recommendation(
            db_session, ticker=ticker, action=action_n, urgency=urgency_n,
        )
        if similar is not None:
            return {
                "status": "skipped_unchanged",
                "ticker": (ticker or "").upper(),
                "action": action_n,
                "urgency": urgency_n,
                "existing_id": similar.id,
                "existing_status": similar.status,
                "message": (
                    "同标的近期已有相同建议，未重复写入。"
                    "请在回复中更新分析文字，勿再 save。"
                ),
            }

        rec = create_recommendation(
            db_session, session_id=session_id,
            ticker=ticker, action=action_n, reasoning=reasoning,
            confidence=confidence, urgency=urgency_n,
        )
        return {
            "status": "saved",
            "recommendation_id": rec.id,
            "ticker": rec.ticker,
            "action": rec.action,
            "urgency": rec.urgency,
        }
    finally:
        db_session.close()


# ── Tool Collection ───────────────────────────────────────

ALL_TOOLS = [
    get_portfolio,
    get_holding,
    get_price,
    get_kline,
    get_financials,
    get_fund_info,
    get_market_snapshot,
    search_ticker_news,
    get_market_headlines,
    get_recommendation_history,
    get_trade_history,
    save_recommendation,
]
