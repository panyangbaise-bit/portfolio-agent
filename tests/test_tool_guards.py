"""Tool-call timeout and identical-parameter loop guard."""

import json
import time

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from agent.tool_guards import (
    count_fingerprint_in_messages,
    execute_tool_calls,
    invoke_tool_with_timeout,
    tool_call_fingerprint,
)


@tool
def slow_echo(text: str = "") -> dict:
    """Sleep then echo — used for timeout tests."""
    time.sleep(2.0)
    return {"text": text}


@tool
def fast_echo(text: str = "") -> dict:
    """Echo immediately."""
    return {"text": text}


def test_fingerprint_stable_for_same_params():
    a = tool_call_fingerprint("get_price", {"ticker": "AAPL", "market": "US"})
    b = tool_call_fingerprint("get_price", {"market": "US", "ticker": "AAPL"})
    c = tool_call_fingerprint("get_price", {"ticker": "MSFT", "market": "US"})
    assert a == b
    assert a != c


def test_count_fingerprint_in_messages():
    fp = tool_call_fingerprint("get_price", {"ticker": "AAPL"})
    msgs = [
        AIMessage(
            content="",
            tool_calls=[{
                "name": "get_price",
                "args": {"ticker": "AAPL"},
                "id": "1",
                "type": "tool_call",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "get_price",
                "args": {"ticker": "AAPL"},
                "id": "2",
                "type": "tool_call",
            }],
        ),
    ]
    assert count_fingerprint_in_messages(msgs, fp) == 2


def test_invoke_tool_with_timeout_returns_error_payload():
    result = invoke_tool_with_timeout(slow_echo, {"text": "x"}, timeout=0.1)
    assert result["error"] == "timeout"
    assert "0s" in result["message"] or "timed out" in result["message"].lower()


def test_invoke_tool_with_timeout_does_not_block_on_shutdown():
    """Regression: executor __exit__(wait=True) used to wait out the full tool."""
    started = time.monotonic()
    result = invoke_tool_with_timeout(slow_echo, {"text": "x"}, timeout=0.15)
    elapsed = time.monotonic() - started
    assert result["error"] == "timeout"
    # slow_echo sleeps 2s; must return near the timeout, not after the sleep.
    assert elapsed < 1.0


def test_execute_tool_calls_runs_tool():
    state = {
        "messages": [
            HumanMessage(content="hi"),
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "fast_echo",
                    "args": {"text": "ok"},
                    "id": "c1",
                    "type": "tool_call",
                }],
            ),
        ],
        "session_id": 1,
    }
    out = execute_tool_calls(state, [fast_echo], timeout=5, max_identical=3)
    assert out["tool_loop_halted"] is False
    assert len(out["messages"]) == 1
    payload = json.loads(out["messages"][0].content)
    assert payload["text"] == "ok"


def test_identical_call_halts_on_third_attempt():
    prior = [
        AIMessage(
            content="",
            tool_calls=[{
                "name": "fast_echo",
                "args": {"text": "loop"},
                "id": "a",
                "type": "tool_call",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "fast_echo",
                "args": {"text": "loop"},
                "id": "b",
                "type": "tool_call",
            }],
        ),
    ]
    state = {
        "messages": prior + [
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "fast_echo",
                    "args": {"text": "loop"},
                    "id": "c",
                    "type": "tool_call",
                }],
            ),
        ],
        "session_id": 1,
    }
    out = execute_tool_calls(state, [fast_echo], timeout=5, max_identical=3)
    assert out["tool_loop_halted"] is True
    payload = json.loads(out["messages"][0].content)
    assert payload["error"] == "identical_tool_loop"
    assert payload["attempt"] == 3


def test_identical_calls_in_same_batch_halt_third():
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "fast_echo",
                        "args": {"text": "x"},
                        "id": "1",
                        "type": "tool_call",
                    },
                    {
                        "name": "fast_echo",
                        "args": {"text": "x"},
                        "id": "2",
                        "type": "tool_call",
                    },
                    {
                        "name": "fast_echo",
                        "args": {"text": "x"},
                        "id": "3",
                        "type": "tool_call",
                    },
                ],
            ),
        ],
        "session_id": 1,
    }
    out = execute_tool_calls(state, [fast_echo], timeout=5, max_identical=3)
    assert out["tool_loop_halted"] is True
    assert len(out["messages"]) == 3
    bodies = [json.loads(m.content) for m in out["messages"]]
    assert bodies[0]["text"] == "x"
    assert bodies[1]["text"] == "x"
    assert bodies[2]["error"] == "identical_tool_loop"
