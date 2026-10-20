"""Reuse fresh successful market results within one user turn only."""

import json
import time

from agent.research import current_turn

TTLS = {"get_price": 60, "get_kline": 300, "get_financials": 300}


def cached_result(messages, name, args, now=None):
    if name not in TTLS:
        return None
    now = time.time() if now is None else now
    messages = current_turn(messages)
    calls = {c["id"]: c for m in messages for c in getattr(m, "tool_calls", [])}
    for message in reversed(messages):
        if getattr(message, "name", None) != name or getattr(message, "type", None) != "tool":
            continue
        executed_at = message.additional_kwargs.get("executed_at")
        if executed_at is None or now - executed_at > TTLS[name]:
            continue
        call = calls.get(message.tool_call_id)
        if not call:
            continue
        try:
            payload = json.loads(message.content)
        except (ValueError, TypeError):
            continue
        if not payload or (isinstance(payload, dict) and payload.get("error")):
            continue
        if call["args"] == args:
            # Do not cache a partially failed batch.
            if (
                isinstance(payload, dict)
                and payload.get("batch")
                and any(
                    not v or (isinstance(v, dict) and v.get("error"))
                    for v in payload.get("results", {}).values()
                )
            ):
                continue
            return {"content": message.content, "executed_at": executed_at}
        # A subsequent single-security request can reuse a completed batch.
        if not isinstance(payload, dict) or not payload.get("batch"):
            continue
        ticker = args.get("ticker", "").strip().upper()
        old_args = call["args"]
        tickers = [t.strip().upper() for t in old_args.get("ticker", "").split(",")]
        markets = [m.strip().upper() for m in old_args.get("market", "").split(",")]
        if ticker not in tickers or not markets or "," in args.get("market", ""):
            continue
        if markets[min(tickers.index(ticker), len(markets) - 1)] != args.get("market", "").upper():
            continue
        if name == "get_kline" and args.get("period", "3mo") != old_args.get("period", "3mo"):
            continue
        item = payload.get("results", {}).get(ticker)
        if item and not (isinstance(item, dict) and item.get("error")):
            return {"content": json.dumps(item, ensure_ascii=False), "executed_at": executed_at}
    return None
