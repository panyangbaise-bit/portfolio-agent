"""LangChain tool definitions for the portfolio agent.

Each tool wraps an adapter method or DB query, presenting a clean
interface to the LLM. The agent does not know about adapters, markets,
or databases — it just calls these functions.
"""

from typing import Annotated, Any, Callable, List, Optional, TypeVar

from langchain.tools import tool
from langgraph.prebuilt import InjectedState

try:
    from langsmith.utils import ContextThreadPoolExecutor as _PoolExecutor
except ImportError:  # pragma: no cover
    from concurrent.futures import ThreadPoolExecutor as _PoolExecutor

from db.repository import (
    get_session, get_open_holdings, get_all_holdings, get_holding_by_ticker,
    create_recommendation, get_recommendation_history as db_get_rec_history,
    get_recent_transactions, list_transactions, find_similar_recommendation,
    upsert_price,
)
from adapters.base import registry as adapter_registry
from adapters.brave_search import brave_search
from adapters.news import news_adapter
from adapters.safe import error_payload
from agent.kline import enrich_kline

T = TypeVar("T")
R = TypeVar("R")

# Cap workers so a large batch (e.g. fund constituents) does not stampede providers.
_BATCH_MAX_WORKERS = 12


def _map_parallel(items: List[T], fn: Callable[[T], R], max_workers: int = _BATCH_MAX_WORKERS) -> List[R]:
    """Run ``fn`` over ``items`` concurrently; preserve input order in results."""
    if not items:
        return []
    if len(items) == 1:
        return [fn(items[0])]
    workers = min(max_workers, len(items))
    with _PoolExecutor(max_workers=workers) as executor:
        return list(executor.map(fn, items))


def _safe_invoke(fn: Callable[[], R], empty: Optional[R] = None, **extra) -> Any:
    """Never let a provider/DB exception escape a LangChain tool."""
    try:
        return fn()
    except Exception as exc:
        if empty is not None:
            return empty
        return error_payload(exc, **extra)


def _notify_recommendation(recommendation) -> None:
    """Deliver a saved pending recommendation without disrupting agent work."""
    try:
        from notifier.telegram import send_recommendation
        send_recommendation(recommendation)
    except Exception:
        # A notification outage must not turn a successfully saved
        # recommendation into an agent-tool failure.
        pass


# ── Portfolio Tools ───────────────────────────────────────

@tool
def get_portfolio() -> list[dict]:
    """获取当前所有持仓列表（市值与权重均按人民币折算，与 Dashboard 一致）。

    Returns:
        list[dict]: 持仓列表，每项含 ticker, market, shares, cost_basis, currency,
        current_price, market_value（原币）, market_value_cny, pnl_pct, weight_pct（按 CNY）
    """
    return _safe_invoke(_get_portfolio_inner)


def _get_portfolio_inner() -> list:
    from app.fx import currency_for_market, get_cny_rates

    session = get_session()
    try:
        holdings = get_open_holdings(session)
        markets = tuple(sorted({h.market.upper() for h in holdings}))
        cny_rates = get_cny_rates(markets)

        priced = []
        missing_fx = []
        for h in holdings:
            market = h.market.upper()
            rate = cny_rates.get(market)
            if rate is None:
                missing_fx.append(market)
                continue
            priced.append((h, market, rate))

        def _fetch_price(item):
            h, _market, _rate = item
            try:
                adapter = adapter_registry.get(h.market)
                price_data = adapter.get_price(h.ticker)
                if not isinstance(price_data, dict) or price_data.get("error"):
                    return h.cost_basis
                return price_data.get("price", 0) or 0
            except Exception:
                return h.cost_basis

        prices = _map_parallel(priced, _fetch_price)

        total_value_cny = 0.0
        values = []
        for (h, market, rate), current_price in zip(priced, prices):
            market_value = h.shares * current_price
            market_value_cny = market_value * rate
            total_value_cny += market_value_cny
            pnl_pct = ((current_price - h.cost_basis) / h.cost_basis * 100) if h.cost_basis else 0
            values.append({
                "ticker": h.ticker,
                "market": h.market,
                "shares": h.shares,
                "cost_basis": h.cost_basis,
                "currency": currency_for_market(market),
                "current_price": round(current_price, 4) if market == "CN" else round(current_price, 2),
                "position_type": h.position_type,
                "pnl_pct": round(pnl_pct, 2),
                "market_value": round(market_value, 2),
                "market_value_cny": round(market_value_cny, 2),
                "fx_rate_to_cny": rate,
                "holding_id": h.id,
            })

        if missing_fx:
            return {
                "error": (
                    "无法获取汇率，无法计算人民币仓位权重: "
                    + ", ".join(sorted(set(missing_fx)))
                ),
                "holdings": values,
            }

        for v in values:
            v["weight_pct"] = (
                round(v["market_value_cny"] / total_value_cny * 100, 2)
                if total_value_cny > 0
                else 0
            )

        return values
    finally:
        session.close()


@tool
def get_return_summary() -> dict:
    """获取组合总收益（人民币），含已清仓已实现盈亏和未平仓浮动。

    总收益以本工具为准。get_portfolio 的 pnl_pct 是券商残馀成本浮动，
    分批卖出后会把已实现利润摊进成本，且清仓后不再出现。

    Returns:
        dict: market_value_cny, invested_cny, realized_pnl_cny, unrealized_pnl_cny,
        total_pnl_cny, total_pnl_pct, positions（每仓已实现/浮动/合计）
    """
    return _safe_invoke(_get_return_summary_inner)


def _get_return_summary_inner() -> dict:
    from app.fx import get_cny_rates
    from app.components.portfolio_valuation import calculate_portfolio_totals

    session = get_session()
    try:
        holdings = get_all_holdings(session)
        transactions = list_transactions(session)
        markets = tuple(sorted({h.market.upper() for h in holdings}))
        cny_rates = get_cny_rates(markets)
        open_holdings = [h for h in holdings if (h.status or "open") != "closed" and h.shares]

        def _fetch_price(holding):
            try:
                adapter = adapter_registry.get(holding.market)
                price_data = adapter.get_price(holding.ticker)
                if not isinstance(price_data, dict) or price_data.get("error"):
                    return holding.cost_basis
                return price_data.get("price", 0) or holding.cost_basis
            except Exception:
                return holding.cost_basis

        fetched = _map_parallel(open_holdings, _fetch_price)
        prices = {
            (holding.market, holding.ticker): price
            for holding, price in zip(open_holdings, fetched)
        }
        totals = calculate_portfolio_totals(holdings, prices, cny_rates, transactions)
    finally:
        session.close()

    if totals is None:
        return {"error": "无法获取汇率，无法计算人民币总收益"}
    return {
        "market_value_cny": round(totals["market_value"], 2),
        "invested_cny": round(totals["cost"], 2),
        "realized_pnl_cny": round(totals["realized_pnl"], 2),
        "unrealized_pnl_cny": round(totals["unrealized_pnl"], 2),
        "total_pnl_cny": round(totals["pnl"], 2),
        "total_pnl_pct": round(totals["pnl_pct"], 2),
        "positions": totals["positions"],
    }


@tool
def get_holding(ticker: str) -> dict:
    """获取单个标的的持仓详情。

    Args:
        ticker: 标的代码，如 AAPL, 600519, 0700.HK, BTC

    Returns:
        dict: 持仓详情，含 ticker, market, shares, cost_basis, position_type, current_price, pnl_pct
    """
    def _run():
        session = get_session()
        try:
            return _get_holding_inner(session, ticker)
        finally:
            session.close()

    return _safe_invoke(_run, ticker=ticker)

def _get_holding_inner(session, ticker: str) -> dict:
    h = get_holding_by_ticker(session, ticker.upper())
    if not h:
        return {"error": f"未找到标的: {ticker}"}
    try:
        adapter = adapter_registry.get(h.market)
        price_data = adapter.get_price(h.ticker)
        if not isinstance(price_data, dict) or price_data.get("error"):
            current_price = h.cost_basis
        else:
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
    """获取标的价格与涨跌。支持单个和批量查询。

    单个: get_price(ticker="AAPL", market="US")
    同市场批量: get_price(ticker="AAPL,TSLA", market="US")
    跨市场批量: get_price(ticker="AAPL,600519", market="US,CN")

    A 股场外基金/ETF联接（如 020357）返回的是单位净值（quote_type=nav, lag=T+1），
    change_pct 是相对上一净值日，不是今日盘中涨跌；请看 nav_date。

    Args:
        ticker: 单个标的代码，或多个逗号分隔
        market: 市场代码，多标的时可逗号分隔与ticker一一对应

    Returns:
        单个时 {ticker, price, change_pct, ...}；基金另含 nav_date / quote_type / lag
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
        return _safe_invoke(lambda: ad.get_price(tickers[0]), ticker=tickers[0])

    def _one(t: str):
        ad = adapters.get(t)
        if ad is None:
            return t, {"error": f"unknown market for {t}"}
        try:
            return t, ad.get_price(t)
        except Exception as e:
            return t, {"error": str(e)}

    return {"batch": True, "results": dict(_map_parallel(tickers, _one))}


@tool
def get_kline(ticker: str, market: str, period: str = "3mo") -> list[dict] | dict:
    """获取历史K线数据。支持单个和批量查询。

    单个: get_kline(ticker="AAPL", market="US", period="3mo")
    同市场批量: get_kline(ticker="AAPL,TSLA", market="US")
    跨市场批量: get_kline(ticker="AAPL,600519", market="US,CN")

    每根含 volume、volume_ma5/10/20（含当日）、volume_ratio5（当日量/前5根均量，
    非盘中量比）、volume_change_pct（较前一根量变化%）。不足窗口/缺失/零分母返回 null。
    volume_unit: lot=手、share=股、usd=美元；volume_kind 区分成交量与滚动24小时成交额。
    series_kind=nav 为净值线，price 为价格采样线，不可当作 OHLC；不跨市场比较原始量。
    period 是回溯范围，日频数据。要在报告中画图，随后调用 annotate_kline(ticker=...)。
    """
    tickers = [t.strip().upper() for t in str(ticker).split(",") if t.strip()]
    if not tickers:
        return {"error": "no valid tickers"}
    adapters, _ = _resolve_adapters_for_batch(tickers, market)
    if len(tickers) == 1:
        ad = adapters.get(tickers[0])
        if ad is None:
            return {"error": f"no adapter for market: {market}"}
        item_market = next(m.strip() for m in market.split(",") if m.strip())
        return _safe_invoke(lambda: enrich_kline(ad.get_kline(tickers[0], period), item_market), empty=[])

    def _one(t: str):
        ad = adapters.get(t)
        if ad is None:
            return t, []
        try:
            markets = [m.strip().upper() for m in market.split(",") if m.strip()]
            item_market = markets[min(tickers.index(t), len(markets) - 1)]
            return t, enrich_kline(ad.get_kline(t, period), item_market)
        except Exception:
            return t, []

    return {"batch": True, "results": dict(_map_parallel(tickers, _one))}


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
        return _safe_invoke(lambda: ad.get_financials(tickers[0]), ticker=tickers[0])

    def _one(t: str):
        ad = adapters.get(t)
        if ad is None:
            return t, {"error": f"unknown market for {t}"}
        try:
            return t, ad.get_financials(t)
        except Exception as e:
            return t, {"error": str(e)}

    return {"batch": True, "results": dict(_map_parallel(tickers, _one))}


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
    try:
        adapter = adapter_registry.get("CN")
    except Exception as exc:
        return error_payload(exc, ticker=ticker)
    if not hasattr(adapter, "get_fund_info"):
        return {"ticker": ticker, "error": "CN adapter does not support get_fund_info"}
    return _safe_invoke(
        lambda: adapter.get_fund_info(ticker, top_constituents=top_constituents),
        ticker=ticker,
    )


@tool
def get_market_snapshot(market: str) -> dict:
    """获取市场大盘指数概览。支持单个和批量查询。

    单个: get_market_snapshot(market="US")
    批量: get_market_snapshot(market="US,CN,HK")

    Args:
        market: 市场代码 — US (S&P 500), CN (上证指数), HK (恒生指数), CRYPTO (总市值)
                多个用逗号分隔

    Returns:
        单个时: {index_name, current, change_pct, ...}
        多个时: {"batch": true, "results": {market: {...}, ...}}
    """
    markets = [m.strip().upper() for m in str(market).split(",") if m.strip()]
    if not markets:
        return {"error": "no valid markets"}
    if len(markets) == 1:
        return _safe_invoke(
            lambda: adapter_registry.get(markets[0]).get_market_snapshot(),
            market=markets[0],
        )

    def _one(mk: str):
        try:
            return mk, adapter_registry.get(mk).get_market_snapshot()
        except ValueError:
            return mk, {"error": f"no adapter for market: {mk}"}
        except Exception as e:
            return mk, {"error": str(e)}

    return {"batch": True, "results": dict(_map_parallel(markets, _one))}


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

    def _run():
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

    return _safe_invoke(_run, empty=[])


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

    def _run():
        return _add_to_watchlist_inner(
            ticker, market, name, watch_reason,
            target_price_low, target_price_high, priority,
        )

    return _safe_invoke(_run, ticker=ticker)


def _add_to_watchlist_inner(
    ticker, market, name, watch_reason, target_price_low, target_price_high, priority,
):
    from db.repository import create_watchlist_item, get_watchlist_by_ticker
    session = get_session()
    session.info["memory_actor"] = "agent"
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

    def _run():
        session = get_session()
        session.info["memory_actor"] = "agent"
        try:
            item = get_watchlist_by_ticker(session, ticker)
            if not item:
                return {"status": "not_found", "ticker": ticker, "message": "该标的不在监察表中"}
            delete_watchlist_item(session, item.id)
            return {"status": "removed", "ticker": item.ticker}
        finally:
            session.close()

    return _safe_invoke(_run, ticker=ticker)


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
        results = _safe_invoke(
            lambda: news_adapter.search_ticker_news(tickers[0], days),
            empty=[],
        )
        if isinstance(results, dict) and results.get("error"):
            return {"ticker": tickers[0], "results": [], **results}
        return {"ticker": tickers[0], "results": results}

    def _one(t: str):
        try:
            return t, news_adapter.search_ticker_news(t, days)
        except Exception as e:
            return t, {"error": str(e)}

    return {"batch": True, "results": dict(_map_parallel(tickers, _one))}


@tool
def get_market_headlines() -> list[dict]:
    """获取最新的市场头条和要闻。

    Returns:
        list[dict]: 新闻列表，每项含 title, url, summary, published_at, author
    """
    headlines = _safe_invoke(lambda: news_adapter.get_headlines(10), empty=[])
    latest = _safe_invoke(lambda: news_adapter.get_latest_news(10), empty=[])
    if not isinstance(headlines, list):
        headlines = []
    if not isinstance(latest, list):
        latest = []
    seen = set()
    merged = []
    for item in headlines + latest:
        key = item.get("title", "")
        if key and key not in seen:
            seen.add(key)
            merged.append(item)
    return merged[:15]


@tool
def web_search(query: str, count: int = 5, days: int = 7) -> dict:
    """用 Brave 搜索公开网页。只在华尔街见闻没有相关新闻时作为补充。

    先调用 search_ticker_news（中文关键词）和 get_market_headlines。
    仅当见闻结果为空，或标题/摘要与标的、事件明显无关时，再调用本工具。
    不要把它当作查新闻的第一步，也不要为每个持仓都搜一遍。

    Args:
        query: 搜索词，例如「英伟达 财报」或「腾讯 回购」
        count: 返回条数，1-10，默认 5
        days: 时间窗口。1=过去一天，7=过去一周，31=过去一月；0 表示不限时间。默认 7

    Returns:
        dict: query, source=brave, results[{title, url, description, age}]
    """
    return _safe_invoke(
        lambda: brave_search.search(query, count=count, days=days),
        query=(query or "").strip()[:400],
        source="brave",
    )


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
    def _run():
        return _get_recommendation_history_inner(ticker, limit)

    return _safe_invoke(_run, empty=[])


def _get_recommendation_history_inner(ticker, limit):
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
                "user_feedback": {"action": r.user_action.action, "reason": r.user_action.notes,
                                  "acted_at": r.user_action.acted_at.isoformat()} if r.user_action else None,
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
    def _run():
        return _get_trade_history_inner(days)

    return _safe_invoke(_run, empty=[])


def _get_trade_history_inner(days):
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
    recommendations: Optional[list] = None,
    session_id: Annotated[int, InjectedState("session_id")] = 0,
) -> dict:
    """保存投资建议。支持单个和批量模式。

    降噪规则（工具会强制执行）：
    - 日常 hold + urgency=low：不落库。
    - 同标的已有相同 action 的 pending，或近 7 天内相同 action+urgency：跳过。
    保存前请先 get_recommendation_history 对照近期结论。

    Args:
        ticker: 标的代码（单条模式，传空则在 recommendations 中批量）
        action: 建议操作（单条模式）
        reasoning: 建议理由（单条模式；写入 recommendations.reasoning，非模型 thinking）
        confidence: 置信度（单条模式）
        urgency: 紧迫度（单条/批量共用）
        recommendations: 批量建议列表，每条为 {ticker, action, reasoning, confidence, urgency}

    Returns:
        dict: 单条时 status=saved|skipped_routine|skipped_unchanged
              批量时 {"batch": true, "results": [{status, ...}, ...], "total": N, "saved": N}
    """
    # session_id is InjectedState from LangGraph — never trust the LLM to pass it.
    # ── Batch mode ──
    if recommendations and isinstance(recommendations, list) and len(recommendations) > 0:
        if not session_id:
            return {
                "batch": True,
                "results": [],
                "total": 0,
                "saved": 0,
                "status": "error",
                "message": "session_id missing — cannot save recommendation",
            }
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
                _notify_recommendation(rec)
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

    if not session_id:
        return {
            "status": "error",
            "ticker": (ticker or "").upper(),
            "message": "session_id missing — cannot save recommendation",
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
        _notify_recommendation(rec)
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

@tool
def query_portfolio_ledger(
    operation: str, ticker: Optional[str] = None, market: Optional[str] = None,
    start_date: Optional[str] = None, end_date: Optional[str] = None,
    action: Optional[str] = None, status: Optional[str] = None,
    limit: int = 25, offset: int = 0,
) -> dict:
    """只读查询账本。operation 为 holdings 或 transactions，无需行情请求。

    holdings 默认查询未平仓，可传 status=open/closed/all。
    transactions 可按 ticker、market、action=buy/sell、start_date/end_date
    (YYYY-MM-DD，含首尾 UTC 日) 筛选。返回币种、成本/成交价和分页 next_offset；
    这些不是实时市值或总收益。失败返回 error，不能当成没有记录。
    """
    from a2a.queries import read_query
    params = {"ticker": ticker, "market": market, "limit": limit, "offset": offset}
    if operation == "holdings":
        params["status"] = status
    else:
        params.update(start_date=start_date, end_date=end_date, action=action)
    return _safe_invoke(lambda: read_query(operation, params))

from memory.tools import search_memory, read_memory, get_instrument_timeline
from agent.chart_tools import annotate_kline

ALL_TOOLS = [
    query_portfolio_ledger,
    search_memory, read_memory, get_instrument_timeline,
    get_portfolio,
    get_return_summary,
    get_holding,
    get_price,
    get_kline,
    annotate_kline,
    get_financials,
    get_fund_info,
    get_market_snapshot,
    search_ticker_news,
    get_market_headlines,
    web_search,
    get_recommendation_history,
    get_trade_history,
    save_recommendation,
    get_watchlist,
    add_to_watchlist,
    remove_from_watchlist,
]
