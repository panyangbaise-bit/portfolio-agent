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

def _resolve_adapters_for_batch(tickers: list[str], market: str):
    """Resolve adapter per ticker when market may be comma-separated."""
    markets = [m.strip() for m in str(market).split(",") if m.strip()]
    if not markets:
        return {}, tickers
    if len(markets) == 1:
        try:
            return {t: adapter_registry.get(markets[0]) for t in tickers}, tickers
        except ValueError:
            pass
    pairs = []
    mappers = {}
    for i, t in enumerate(tickers):
        mk = markets[i] if i < len(markets) else markets[-1]
        try:
            mappers[t] = adapter_registry.get(mk)
            pairs.append((t, mk))
        except ValueError:
            pairs.append((t, None))
    return mappers, tickers


@tool
def get_price(ticker: str, market: str) -> dict:
    """获取标的价格和日内变动。支持单个和批量查询。

    单个: get_price(ticker="AAPL", market="US")
    同市场批量: get_price(ticker="AAPL,TSLA", market="US")
    跨市场批量: get_price(ticker="AAPL,600519", market="US,CN")

    Args:
        ticker: 单个标的代码，或多个逗号分隔
        market: 市场代码，多标的时可逗号分隔与ticker一一对应

    Returns:
        单个时 {ticker, price, ...}
        多个时 {"batch": true, "results": {ticker: {price, ...}, ...}}
    """
    tickers = [t.strip().upper() for t in str(ticker).split(",") if t.strip()]
    if not tickers:
        return {"error": "no valid tickers"}
    adapters, _ = _resolve_adapters_for_batch(tickers, market)
    if len(tickers) == 1:
        ad = adapters.get(tickers[0])
        if ad is None:
            return {"error": f"no adapter for market: {market}"}
        return ad.get_price(tickers[0])
    results = {}
    for t in tickers:
        ad = adapters.get(t)
        if ad is None:
            results[t] = {"error": f"unknown market for {t}"}
            continue
        try:
            results[t] = ad.get_price(t)
        except Exception as e:
            results[t] = {"error": str(e)}
    return {"batch": True, "results": results}


@tool
def get_kline(ticker: str, market: str, period: str = "3mo") -> list[dict]:
    """获取历史K线数据。支持单个和批量查询。

    单个: get_kline(ticker="AAPL", market="US", period="3mo")
    同市场批量: get_kline(ticker="AAPL,TSLA", market="US")
    跨市场批量: get_kline(ticker="AAPL,600519", market="US,CN")
    """
    tickers = [t.strip().upper() for t in str(ticker).split(",") if t.strip()]
    if not tickers:
        return {"error": "no valid tickers"}
    adapters, _ = _resolve_adapters_for_batch(tickers, market)
    if len(tickers) == 1:
        ad = adapters.get(tickers[0])
        if ad is None:
            return {"error": f"no adapter for market: {market}"}
        return ad.get_kline(tickers[0], period)
    results = {}
    for t in tickers:
        ad = adapters.get(t)
        if ad is None:
            results[t] = []
            continue
        try:
            results[t] = ad.get_kline(t, period)
        except Exception:
            results[t] = []
    return {"batch": True, "results": results}


@tool
def get_financials(ticker: str, market: str) -> dict:
    """获取财报基本面数据。支持单个和批量查询。

    单个: get_financials(ticker="AAPL", market="US")
    同市场批量: get_financials(ticker="AAPL,TSLA", market="US")
    跨市场批量: get_financials(ticker="AAPL,600519", market="US,CN")
    """
    tickers = [t.strip().upper() for t in str(ticker).split(",") if t.strip()]
    if not tickers:
        return {"error": "no valid tickers"}
    adapters, _ = _resolve_adapters_for_batch(tickers, market)
    if len(tickers) == 1:
        ad = adapters.get(tickers[0])
        if ad is None:
            return {"error": f"no adapter for market: {market}"}
        return ad.get_financials(tickers[0])
    results = {}
    for t in tickers:
        ad = adapters.get(t)
        if ad is None:
            results[t] = {"error": f"unknown market for {t}"}
            continue
        try:
            results[t] = ad.get_financials(t)
        except Exception as e:
            results[t] = {"error": str(e)}
    return {"batch": True, "results": results}


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

# ── Watchlist Tools ───────────────────────────────────────

@tool
def get_watchlist(status: Optional[str] = None) -> list[dict]:
    """获取监察表（Watchlist）中的所有标的。监察表是用户感兴趣的待建仓标的列表，
    用户在等待合适的建仓时机。

    Args:
        status: 可选过滤 — watching（观察中）, monitoring（密切监控）, converted（已建仓）

    Returns:
        list[dict]: 监察表项列表，每项含 id, ticker, name, market, watch_reason,
                    target_price_low, target_price_high, status, priority, created_at
    """
    from db.repository import get_watchlist_items
    session = get_session()
    try:
        items = get_watchlist_items(session, status=status)
        return [
            {
                "id": item.id,
                "ticker": item.ticker,
                "name": item.name,
                "market": item.market,
                "watch_reason": item.watch_reason,
                "target_price_low": item.target_price_low,
                "target_price_high": item.target_price_high,
                "status": item.status,
                "priority": item.priority,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in items
        ]
    finally:
        session.close()


@tool
def add_to_watchlist(
    ticker: str,
    market: str,
    name: Optional[str] = None,
    watch_reason: Optional[str] = None,
    target_price_low: Optional[float] = None,
    target_price_high: Optional[float] = None,
    priority: str = "medium",
) -> dict:
    """将标的加入监察表。当用户表示对某个标的感兴趣但不想立即建仓时使用。

    Args:
        ticker: 标的代码
        market: 市场 — US, CN, HK, CRYPTO
        name: 显示名称（可选）
        watch_reason: 关注理由
        target_price_low: 目标建仓价位下限
        target_price_high: 目标建仓价位上限
        priority: 优先级 — high, medium, low

    Returns:
        dict: status=added, ticker, id
    """
    from db.repository import create_watchlist_item, get_watchlist_by_ticker
    session = get_session()
    try:
        existing = get_watchlist_by_ticker(session, ticker)
        if existing:
            return {
                "status": "already_exists",
                "ticker": existing.ticker,
                "id": existing.id,
                "message": f"{ticker} 已在监察表中（状态: {existing.status}）",
            }
        item = create_watchlist_item(
            session,
            ticker=ticker,
            market=market,
            name=name,
            watch_reason=watch_reason,
            target_price_low=target_price_low,
            target_price_high=target_price_high,
            priority=priority,
        )
        return {"status": "added", "ticker": item.ticker, "id": item.id}
    finally:
        session.close()


@tool
def remove_from_watchlist(ticker: str) -> dict:
    """从监察表中移除标的。

    Args:
        ticker: 标的代码

    Returns:
        dict: status=removed | not_found
    """
    from db.repository import get_watchlist_by_ticker, delete_watchlist_item
    session = get_session()
    try:
        item = get_watchlist_by_ticker(session, ticker)
        if not item:
            return {"status": "not_found", "ticker": ticker, "message": "该标的不在监察表中"}
        delete_watchlist_item(session, item.id)
        return {"status": "removed", "ticker": item.ticker}
    finally:
        session.close()


# ── News Tools (continued) ────────────────────────────────

@tool
def search_ticker_news(ticker: str, days: int = 7) -> dict:
    """搜索与一个或多个标的相关的最近新闻。支持批量模式。

    底层为中文财经媒体搜索：优先传入中文关键词（公司中文名/常用称谓），
    英文 ticker 或纯数字代码通常搜不到结果。

    推荐: search_ticker_news(ticker="苹果", days=7)
    批量: search_ticker_news(ticker="苹果,特斯拉,英伟达", days=1)
    避免: search_ticker_news(ticker="AAPL")  — 英文代码常返回空

    Args:
        ticker: 搜索关键词（优先中文名），或多个逗号分隔（批量）
        days: 搜索最近几天的新闻，默认7天

    Returns:
        单个时: {"ticker": str, "results": list[dict]}
        多个时: {"batch": true, "results": {ticker: list[dict], ...}}
    """
    # Preserve original casing for CJK keywords; only normalize ASCII tokens.
    tickers = []
    for t in str(ticker).split(","):
        t = t.strip()
        if not t:
            continue
        tickers.append(t.upper() if t.isascii() else t)
    if not tickers:
        return {"error": "no valid tickers"}

    if len(tickers) == 1:
        results = news_adapter.search_ticker_news(tickers[0], days)
        return {"ticker": tickers[0], "results": results}

    result_map = {}
    for t in tickers:
        try:
            result_map[t] = news_adapter.search_ticker_news(t, days)
        except Exception as e:
            result_map[t] = {"error": str(e)}
    return {"batch": True, "results": result_map}


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
    ticker: str = "",
    action: str = "",
    reasoning: str = "",
    confidence: float = 0.0,
    urgency: str = "low",
    session_id: int = 0,
    recommendations: Optional[list] = None,
) -> dict:
    """保存投资建议。支持单个和批量模式。

    降噪规则（工具会强制执行）：
    - 日常 hold + urgency=low：不落库。
    - 同标的已有相同 action 的 pending，或近 7 天内相同 action+urgency：跳过。
    保存前请先 get_recommendation_history 对照近期结论。

    Args:
        ticker: 标的代码（单条模式，传空则在 recommendations 中批量）
        action: 建议操作（单条模式）
        reasoning: 推理链条（单条模式）
        confidence: 置信度（单条模式）
        urgency: 紧迫度（单条/批量共用）
        session_id: agent会话ID（自动传入）
        recommendations: 批量建议列表，每条为 {ticker, action, reasoning, confidence, urgency}

    Returns:
        dict: 单条时 status=saved|skipped_routine|skipped_unchanged
              批量时 {"batch": true, "results": [{status, ...}, ...], "total": N, "saved": N}
    """
    # ── Batch mode ──
    if recommendations and isinstance(recommendations, list) and len(recommendations) > 0:
        db_session = get_session()
        try:
            results = []
            saved_count = 0
            for rec_item in recommendations:
                r_ticker = (rec_item.get("ticker") or "").strip().upper()
                r_action = (rec_item.get("action") or "").strip().lower()
                r_reasoning = rec_item.get("reasoning") or ""
                r_confidence = float(rec_item.get("confidence") or 0)
                r_urgency = (rec_item.get("urgency") or "low").strip().lower()

                if r_action == "hold" and r_urgency == "low":
                    results.append({"ticker": r_ticker, "status": "skipped_routine",
                                    "message": "日常 hold 不写入"})
                    continue

                similar = find_similar_recommendation(
                    db_session, ticker=r_ticker, action=r_action, urgency=r_urgency,
                )
                if similar is not None:
                    results.append({"ticker": r_ticker, "status": "skipped_unchanged",
                                    "existing_id": similar.id})
                    continue

                rec = create_recommendation(
                    db_session, session_id=session_id,
                    ticker=r_ticker, action=r_action, reasoning=r_reasoning,
                    confidence=r_confidence, urgency=r_urgency,
                )
                saved_count += 1
                results.append({"ticker": rec.ticker, "status": "saved",
                                "recommendation_id": rec.id, "action": rec.action})
            return {"batch": True, "results": results, "total": len(results), "saved": saved_count}
        finally:
            db_session.close()

    # ── Single mode (backward compatible) ──
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
    get_watchlist,
    add_to_watchlist,
    remove_from_watchlist,
]
