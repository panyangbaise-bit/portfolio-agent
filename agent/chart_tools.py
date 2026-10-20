"""Build immutable chart artifacts from previously observed tool results."""

import json
from datetime import date, datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from langchain.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel, ConfigDict, Field

from agent.kline import finite_number
from db.models import AgentSession, AnalysisChart
from db.repository import get_session


class ChartAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str = Field(description="数据中的日期 YYYY-MM-DD")
    price: float = Field(gt=0, allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=160)


class ChartLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["support", "resistance", "trend"]
    start_date: str
    end_date: str
    start_price: float = Field(gt=0, allow_inf_nan=False)
    end_price: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
        description="水平支撑/阻力线可省略，自动等于 start_price；趋势线必填",
    )
    text: str = Field(min_length=1, max_length=100)


def build_chart_payload(state, source_tool_call_id, ticker, title, annotations, lines):
    """Resolve an exact get_kline call; the LLM never supplies the price series."""
    ticker = ticker.strip().upper()
    calls = {
        call["id"]: call
        for message in state.get("messages", [])
        for call in (getattr(message, "tool_calls", None) or [])
    }
    if not source_tool_call_id:
        # Some model providers do not expose call IDs as readable content.
        # Resolve the latest completed query containing this ticker instead.
        completed = {getattr(m, "tool_call_id", None) for m in state.get("messages", [])}
        source_tool_call_id = next(
            (
                call_id
                for call_id, candidate in reversed(list(calls.items()))
                if candidate.get("name") == "get_kline"
                and call_id in completed
                and ticker
                in [
                    t.strip().upper()
                    for t in candidate.get("args", {}).get("ticker", "").split(",")
                ]
            ),
            "",
        )
    call = calls.get(source_tool_call_id)
    if not call or call.get("name") != "get_kline":
        raise ValueError("source_tool_call_id 必须引用本轮已完成的 get_kline 调用")
    args = call["args"]
    tickers = [t.strip().upper() for t in args["ticker"].split(",") if t.strip()]
    markets = [m.strip().upper() for m in args["market"].split(",") if m.strip()]
    if ticker not in tickers or not markets:
        raise ValueError("标的不在该 K 线查询中")
    market = markets[min(tickers.index(ticker), len(markets) - 1)]
    message = next(
        (
            m
            for m in reversed(state.get("messages", []))
            if getattr(m, "tool_call_id", None) == source_tool_call_id
        ),
        None,
    )
    if message is None:
        raise ValueError("先完成 get_kline，再调用 annotate_kline")
    data = json.loads(message.content)
    if isinstance(data, dict) and data.get("batch"):
        data = data.get("results", {}).get(ticker)
    if not isinstance(data, list) or not data or len(data) > 2000:
        raise ValueError("K 线数据为空、失败或超过 2000 根，请缩短周期")
    dates = set()
    for bar in data:
        date.fromisoformat(bar["date"])
        if bar["date"] in dates:
            raise ValueError("K 线日期重复，无法确定标注位置")
        dates.add(bar["date"])
        keys = ("price",) if bar.get("series_kind") == "price" else ("open", "high", "low", "close")
        if any(finite_number(bar.get(k)) is None or float(bar[k]) <= 0 for k in keys):
            raise ValueError("K 线含无效价格，无法绘图")
        if len(keys) == 4 and not (
            bar["low"]
            <= min(bar["open"], bar["close"])
            <= max(bar["open"], bar["close"])
            <= bar["high"]
        ):
            raise ValueError("K 线高低价顺序无效")
    notes = [ChartAnnotation.model_validate(a).model_dump() for a in annotations]
    segments = [ChartLine.model_validate(line).model_dump() for line in lines]
    if len(notes) > 12 or len(segments) > 8:
        raise ValueError("每张图最多 12 个标注、8 条线")
    for note in notes:
        if note["date"] not in dates:
            raise ValueError("标注日期必须存在于行情快照中")
    for line in segments:
        if line["end_price"] is None:
            if line["kind"] == "trend":
                raise ValueError("趋势线必须提供 end_price")
            line["end_price"] = line["start_price"]
        if line["start_date"] not in dates or line["end_date"] not in dates:
            raise ValueError("划线端点日期必须存在于行情快照中")
        if line["start_date"] >= line["end_date"]:
            raise ValueError("划线结束日期必须晚于开始日期")
        if line["kind"] != "trend" and line["start_price"] != line["end_price"]:
            raise ValueError("支撑/阻力线两端价格必须相同")
    return {
        "version": 1,
        "ticker": ticker,
        "market": market,
        "period": args.get("period", "3mo"),
        "title": title or ticker,
        "source_tool_call_id": source_tool_call_id,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "bars": sorted(data, key=lambda b: b["date"]),
        "annotations": notes,
        "lines": segments,
    }


@tool
def annotate_kline(
    ticker: str,
    state: Annotated[dict, InjectedState],
    source_tool_call_id: str = "",
    title: str = "",
    annotations: list[ChartAnnotation] | None = None,
    lines: list[ChartLine] | None = None,
) -> dict:
    """将已查询的 K 线快照加上说明/支撑阻力/趋势线，供报告页面展示与下载 PNG。

    先完成 get_kline，再传其中一个 ticker；默认使用该标的最近一次已完成查询。
    可选 source_tool_call_id 精确指定一次查询。无需重复传行情。
    annotations: [{date, price, text}]，最多12项；lines: [{kind, start_date,
    end_date, start_price, end_price, text}]，最多8项，kind 为 support/resistance/trend。
    日期必须来自该查询，水平线只需 start_price，可省略 end_price；趋势线必须提供两端价格。
    只标注有数据依据的历史结构，不作目标价预测。
    返回 markdown 后，将其原样放入最终回复所需位置；图片数据已持久化，不需复制。
    """
    try:
        if len(title) > 160:
            raise ValueError("图表标题最多 160 字")
        session_id = state.get("session_id")
        payload = build_chart_payload(
            state,
            source_tool_call_id,
            ticker,
            title,
            annotations or [],
            lines or [],
        )
        with get_session() as db:
            if not session_id or db.get(AgentSession, session_id) is None:
                raise ValueError("缺少有效会话，无法保存图表")
            chart_id = uuid4().hex
            db.add(AnalysisChart(id=chart_id, session_id=session_id, payload=payload))
            db.commit()
        return {
            "status": "saved",
            "chart_id": chart_id,
            "markdown": f'```kline\n{{"chart_id":"{chart_id}"}}\n```',
            "message": "将 markdown 原样插入最终报告，并保留文字结论供通知渠道阅读。",
        }
    except (ValueError, TypeError, KeyError) as exc:
        return {"error": str(exc)}
