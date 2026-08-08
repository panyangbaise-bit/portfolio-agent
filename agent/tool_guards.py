"""Tool-call timeout and identical-call loop guard for the agent graph."""

import json
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import ToolMessage

# stdlib ThreadPoolExecutor drops contextvars → LangSmith tool runs become
# orphan top-level traces. ContextThreadPoolExecutor keeps the parent run.
try:
    from langsmith.utils import ContextThreadPoolExecutor as _PoolExecutor
except ImportError:  # pragma: no cover
    from concurrent.futures import ThreadPoolExecutor as _PoolExecutor

from config import config


def tool_call_fingerprint(name: str, args: Any) -> str:
    """Stable identity for (tool name, params) duplicate detection."""
    if not isinstance(args, dict):
        args = {"value": args}
    canonical = json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)
    return f"{name}:{canonical}"


def count_fingerprint_in_messages(messages: list, fingerprint: str) -> int:
    """Count prior AI tool_calls matching fingerprint (executed or requested)."""
    count = 0
    for msg in messages or []:
        for tc in getattr(msg, "tool_calls", None) or []:
            if isinstance(tc, dict):
                name = tc.get("name", "unknown")
                args = tc.get("args") or {}
            else:
                name = getattr(tc, "name", None) or "unknown"
                args = getattr(tc, "args", None) or {}
            if tool_call_fingerprint(name, args) == fingerprint:
                count += 1
    return count


def _tool_call_parts(tc: Any) -> Tuple[str, dict, Optional[str]]:
    if isinstance(tc, dict):
        args = tc.get("args") or {}
        if not isinstance(args, dict):
            args = {"value": args}
        return tc.get("name", "unknown"), args, tc.get("id")
    args = getattr(tc, "args", None) or {}
    if not isinstance(args, dict):
        args = {"value": args}
    return (
        getattr(tc, "name", None) or "unknown",
        args,
        getattr(tc, "id", None),
    )


def _prepare_tool_args(tool_name: str, args: dict, state: dict) -> dict:
    """Copy args and inject graph state for InjectedState tools."""
    prepared = dict(args)
    if tool_name == "save_recommendation":
        prepared["session_id"] = state.get("session_id") or 0
    return prepared


def _serialize_tool_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except TypeError:
        return str(result)


def invoke_tool_with_timeout(tool: Any, args: dict, timeout: float) -> Any:
    """Run ``tool.invoke(args)`` with a wall-clock timeout."""
    with _PoolExecutor(max_workers=1) as pool:
        future = pool.submit(tool.invoke, args)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeout:
            return {
                "error": "timeout",
                "message": f"Tool timed out after {timeout:.0f}s",
            }


def execute_tool_calls(
    state: dict,
    tools: list,
    *,
    timeout: Optional[float] = None,
    max_identical: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute the latest AI tool_calls with timeout + identical-call halt.

    Returns ``{"messages": [ToolMessage, ...], "tool_loop_halted": bool}``.
    On the Nth identical (name, params) call (default N=3), that call is not
    executed and ``tool_loop_halted`` is set so the graph can END.
    """
    timeout = float(
        config.TOOL_CALL_TIMEOUT if timeout is None else timeout
    )
    max_identical = int(
        config.TOOL_IDENTICAL_CALL_LIMIT if max_identical is None else max_identical
    )

    messages = list(state.get("messages") or [])
    ai_msg = None
    ai_index = -1
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if getattr(msg, "tool_calls", None):
            ai_msg = msg
            ai_index = i
            break
    if ai_msg is None:
        return {"messages": [], "tool_loop_halted": False}

    history = messages[:ai_index]
    tool_map = {t.name: t for t in tools}
    out_messages: List[ToolMessage] = []
    halted = False
    batch_counts: Dict[str, int] = {}

    for tc in ai_msg.tool_calls:
        name, args, tc_id = _tool_call_parts(tc)
        fp = tool_call_fingerprint(name, args)
        prior = count_fingerprint_in_messages(history, fp) + batch_counts.get(fp, 0)
        attempt = prior + 1
        batch_counts[fp] = batch_counts.get(fp, 0) + 1

        if attempt >= max_identical:
            halted = True
            payload = {
                "error": "identical_tool_loop",
                "message": (
                    f"Identical tool call limit ({max_identical}) reached for "
                    f"{name} with the same parameters. Agent loop halted."
                ),
                "tool": name,
                "params": args,
                "attempt": attempt,
            }
            out_messages.append(
                ToolMessage(
                    content=_serialize_tool_result(payload),
                    tool_call_id=tc_id or "",
                    name=name,
                )
            )
            continue

        tool = tool_map.get(name)
        if tool is None:
            out_messages.append(
                ToolMessage(
                    content=_serialize_tool_result(
                        {"error": "unknown_tool", "message": f"Unknown tool: {name}"}
                    ),
                    tool_call_id=tc_id or "",
                    name=name,
                )
            )
            continue

        prepared = _prepare_tool_args(name, args, state)
        result = invoke_tool_with_timeout(tool, prepared, timeout)
        out_messages.append(
            ToolMessage(
                content=_serialize_tool_result(result),
                tool_call_id=tc_id or "",
                name=name,
            )
        )

    return {"messages": out_messages, "tool_loop_halted": halted}
