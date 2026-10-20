"""Compact model-facing views; original tool evidence stays in graph state and DB."""

import json

from agent.kline import finite_number


def summarize_series(rows):
    if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
        return rows
    if not all("date" in r for r in rows):
        return rows
    rows = sorted(rows, key=lambda r: r["date"])
    kind = rows[-1].get("series_kind", "ohlc")
    closes = [finite_number(r.get("close", r.get("price"))) for r in rows]
    columns = ["date", "open", "high", "low", "close", "volume", "volume_ratio5"]
    if kind in {"nav", "price"}:
        columns = ["date", "close" if kind == "nav" else "price"]
    points = {}
    for key, operation in (("high", max), ("low", min), ("volume", max)):
        candidates = [r for r in rows if finite_number(r.get(key)) is not None]
        if candidates and kind == "ohlc":
            points[key] = operation(candidates, key=lambda r: float(r[key]))
    last = rows[-1]
    return {
        "view": "compact",
        "total_bars": len(rows),
        "from": rows[0]["date"],
        "through": last["date"],
        "series_kind": kind,
        "asset_type": last.get("asset_type"),
        "resolved_code": last.get("resolved_code"),
        "volume_unit": last.get("volume_unit"),
        "volume_kind": last.get("volume_kind"),
        "capabilities": {
            "intraday_patterns": kind == "ohlc",
            "volume_analysis": kind == "ohlc" and last.get("volume") is not None,
        },
        "limitations": "净值/采样线不可判定影线、日内反转；无成交量时量能条件为无法判断。"
        if kind != "ohlc"
        else "当日可能未收盘，不可直接用当日成交量判断缩量。",
        "close_ma": {
            str(w): round(sum(closes[-w:]) / w, 4)
            if len(closes) >= w and all(v is not None for v in closes[-w:])
            else None
            for w in (5, 10, 20, 50, 200)
        },
        "latest": last,
        "window_extremes": points,
        "columns": columns,
        "recent_bars": [[r.get(c) for c in columns] for r in rows[-20:]],
        "note": "原始全量序列仍保存在本轮，可直接 annotate_kline；标注日期/数值须来自可见证据。",
    }


def compact_history(rows):
    if not isinstance(rows, list) or len(rows) <= 4:
        return rows
    counts = {}
    selected = []
    feedback = []
    for row in rows:
        if not isinstance(row, dict):
            return rows
        ticker = row.get("ticker")
        if (row.get("user_feedback") or {}).get("reason"):
            feedback.append(
                {"id": row.get("id"), "ticker": ticker, "user_feedback": row["user_feedback"]}
            )
        if counts.get(ticker, 0) < 2 or row.get("status") == "pending":
            selected.append(row)
            counts[ticker] = counts.get(ticker, 0) + 1
    return {
        "view": "latest_per_ticker",
        "results": selected,
        "user_feedback": feedback,
        "returned_count": len(rows),
        "omitted_count": len(rows) - len(selected),
        "note": "旧建议正文已省略；需完整历史请按 ticker 查询或读取对应记忆。用户反馈完整保留。",
    }


def model_messages(messages):
    """Project large tool results without breaking tool-call IDs or stored evidence."""
    result = []
    calls = {c["id"]: c for m in messages for c in getattr(m, "tool_calls", [])}
    for msg in messages:
        name = getattr(msg, "name", None)
        if getattr(msg, "type", None) != "tool" or name not in {
            "get_kline",
            "get_recommendation_history",
        }:
            result.append(msg)
            continue
        try:
            payload = json.loads(msg.content)
        except (ValueError, TypeError):
            result.append(msg)
            continue
        if name == "get_kline":
            if calls.get(msg.tool_call_id, {}).get("args", {}).get("detail") == "full":
                result.append(msg)
                continue
            if isinstance(payload, dict) and payload.get("batch"):
                payload = {
                    **payload,
                    "results": {k: summarize_series(v) for k, v in payload["results"].items()},
                }
            else:
                payload = summarize_series(payload)
        elif not calls.get(msg.tool_call_id, {}).get("args", {}).get("ticker"):
            payload = compact_history(payload)
        result.append(msg.model_copy(update={"content": json.dumps(payload, ensure_ascii=False)}))
    return result
