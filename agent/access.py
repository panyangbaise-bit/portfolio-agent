"""Explicit allowlist for external portfolio queries."""

READ_ONLY_TOOLS = frozenset(
    {
        "search_memory",
        "read_memory",
        "get_instrument_timeline",
        "get_portfolio",
        "get_return_summary",
        "get_holding",
        "get_price",
        "get_kline",
        "get_financials",
        "get_fund_info",
        "get_market_snapshot",
        "search_ticker_news",
        "get_market_headlines",
        "web_search",
        "get_recommendation_history",
        "get_trade_history",
        "get_watchlist",
        "query_portfolio_ledger",
    }
)

EXTERNAL_QUERY_CONTEXT = """
## 当前任务：外部 agent / ChatGPT 的只读查询
优先准确回答用户的问题。这是只读访问，不得新增/修改持仓、交易、关注列表或建议。
仅问持仓或成交记录时，优先 query_portfolio_ledger，只查询相关数据，不执行例行盘后检查或额外新闻搜索。
交易按 ticker、market、日期筛选，包含已清仓标的，注意分页；有 next_offset 时不能把当前页当成全部结果。
账本成本不是当前价格，原币金额不能跨币种相加。收益/实时仓位分析才使用行情和收益工具。
get_trade_history 查询失败时不得宣称没有交易；使用 query_portfolio_ledger 核实。
不下单，不代用户执行建议；可以解释已记录的持仓、成交、收益和历史分析。
"""
