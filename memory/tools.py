"""Memory tools share one retrieval implementation with the UI."""
from typing import Optional
from langchain.tools import tool
from db.repository import get_session
from memory import retrieval


def _call(fn, **kwargs):
    try:
        with get_session() as db:
            return fn(db, **kwargs)
    except ValueError as exc:
        return {"status": "invalid_request", "message": str(exc)}
    except Exception as exc:
        return {"status": "error", "message": "Memory unavailable", "error_type": type(exc).__name__}


@tool
def search_memory(query: str, instruments: Optional[list[str]] = None,
                  source_types: Optional[list[str]] = None, start_at: Optional[str] = None,
                  end_at: Optional[str] = None, as_of: Optional[str] = None, limit: int = 10) -> dict:
    """检索投资记忆：历史建议、用户拒绝理由、分析、操作、对话、纪律和新闻。

    instruments 接受 US:AAPL、CN:020357、代码或完整名称。source_types:
    recommendation, feedback, analysis, run, transaction, holding, watchlist,
    discipline, message, news, financial。时间用 ISO 格式；无时区按 APP_TIMEZONE。
    as_of 限制当时可知信息，复盘时必须传递给后续读取。返回 M编号可引用的证据。
    结果是相关片段而非全量记录，不能据此计算总次数或收益。
    """
    return _call(retrieval.search, query=query, instruments=instruments, source_types=source_types,
                 start_at=start_at, end_at=end_at, as_of=as_of, limit=limit)


@tool
def read_memory(evidence_id: str, as_of: Optional[str] = None, offset: int = 0,
                include_relations: bool = True) -> dict:
    """读取 M123 等证据原文与关联建议/反馈。长文沿 next_offset 继续读取。

    as_of 必须与之前的历史查询一致，关联证据也受此限制。
    evidence_id=current_discipline 读取当前有效交易纪律，仅用于当前决策。
    """
    if evidence_id == "current_discipline":
        if as_of:
            return {"status": "invalid_request", "message": "Use historical discipline evidence with as_of"}
        def current(db):
            from db.repository import get_trading_discipline
            memo = get_trading_discipline(db)
            return {"status": "ok", "content": memo.content if memo else "", "source": "trading_discipline:1"}
        return _call(current)
    return _call(retrieval.read, evidence_id=evidence_id, as_of=as_of, offset=offset, include_relations=include_relations)


@tool
def get_instrument_timeline(instrument: str, start_at: Optional[str] = None,
                            end_at: Optional[str] = None, as_of: Optional[str] = None,
                            cursor: int = 0, limit: int = 30,
                            source_types: Optional[list[str]] = None) -> dict:
    """分页列出某标的的完整记忆记录（包括变更版本），按入库顺序排列。

    instrument 接受市场:代码、代码或完整名称。沿 next_cursor 读取直到为空。
    每条包含业务发生时间和可获知时间。版本记录数不等于交易次数。
    """
    return _call(retrieval.timeline, instrument=instrument, start_at=start_at,
                 end_at=end_at, as_of=as_of, cursor=cursor, limit=limit, source_types=source_types)
