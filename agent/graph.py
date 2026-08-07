"""LangGraph state graph for the portfolio agent.

Defines the ReAct-style agent loop:
  agent_node (LLM reasoning + tool selection)
    → tools_node (execute tool + persist tool calls)
    → agent_node (continue reasoning with tool result)
    → END

Uses DeepSeek API via ChatOpenAI (OpenAI-compatible interface).
"""

from typing import Annotated, Any, Optional

from typing_extensions import NotRequired, TypedDict
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

from agent.llm import build_deepseek_llm
from agent.system_prompt import SYSTEM_PROMPT
from agent.tool_guards import execute_tool_calls
from agent.tools import ALL_TOOLS
from app.timeutil import format_now_for_agent
from config import config
from db.repository import get_session, log_tool_call

# Extreme safety cap only — normal tool results are stored in full.
_RESULT_MAX_CHARS = 100_000


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    session_id: int
    triggered_by: str
    extra_context: str
    tool_loop_halted: NotRequired[bool]
    # Count of tool-enabled LLM rounds completed in this invoke.
    agent_rounds: NotRequired[int]


def _truncate_result(text: Any) -> Optional[str]:
    """Keep full tool output; truncate only pathological oversized payloads."""
    if text is None:
        return None
    s = text if isinstance(text, str) else str(text)
    if len(s) <= _RESULT_MAX_CHARS:
        return s
    return s[:_RESULT_MAX_CHARS] + "…[truncated]"


def _tool_call_parts(tc: Any):
    """Normalize LangChain tool_call dict/object into name, args, id."""
    if isinstance(tc, dict):
        return tc.get("name", "unknown"), tc.get("args") or {}, tc.get("id")
    return (
        getattr(tc, "name", None) or "unknown",
        getattr(tc, "args", None) or {},
        getattr(tc, "id", None),
    )


def _persist_tool_calls(state: AgentState, tool_messages: list) -> None:
    """Write tool name/args/result for the latest AI tool_calls into DB."""
    session_id = state.get("session_id")
    if not session_id:
        return

    ai_msg = None
    for msg in reversed(state.get("messages") or []):
        if getattr(msg, "tool_calls", None):
            ai_msg = msg
            break
    if ai_msg is None:
        return

    by_id = {}
    for tm in tool_messages:
        tid = getattr(tm, "tool_call_id", None)
        if tid:
            by_id[tid] = tm

    db = get_session()
    try:
        for tc in ai_msg.tool_calls:
            name, args, tc_id = _tool_call_parts(tc)
            if not isinstance(args, dict):
                args = {"value": args}
            tm = by_id.get(tc_id) if tc_id else None
            content = getattr(tm, "content", "") if tm else ""
            log_tool_call(
                db,
                session_id,
                name,
                params=args,
                result_summary=_truncate_result(content),
            )
    finally:
        db.close()


def _with_system_prompt(state: AgentState, messages: list) -> list:
    has_system = any(isinstance(m, SystemMessage) for m in messages)
    if has_system:
        return list(messages)
    prompt = SYSTEM_PROMPT
    extra = state.get("extra_context", "")
    if extra:
        prompt = prompt + "\n\n" + extra
    prompt = prompt + "\n\n" + format_now_for_agent()
    return [SystemMessage(content=prompt)] + list(messages)


def build_agent_graph() -> StateGraph:
    """Build and compile the LangGraph agent graph with DeepSeek thinking mode."""

    llm = build_deepseek_llm()
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    def agent_node(state: AgentState) -> dict:
        """Agent reasoning node. Calls the LLM with tools bound."""
        if state.get("tool_loop_halted"):
            # Identical-call / round guard already closed the loop.
            return {
                "messages": [
                    AIMessage(
                        content=(
                            "Agent loop halted (identical tool call or round limit). "
                            "Stopping without further tool calls."
                        )
                    )
                ]
            }

        rounds = int(state.get("agent_rounds") or 0)
        max_rounds = int(config.AGENT_MAX_ROUNDS)
        messages = _with_system_prompt(state, state["messages"])

        # After AGENT_MAX_ROUNDS tool-enabled LLM calls, allow one final
        # synthesis without tools so the last tool results are not dropped.
        if rounds >= max_rounds:
            response = llm.invoke(messages)
            return {
                "messages": [response],
                "tool_loop_halted": True,
            }

        response = llm_with_tools.invoke(messages)
        return {"messages": [response], "agent_rounds": rounds + 1}

    def tools_node(state: AgentState) -> dict:
        """Execute tools with timeout + loop guard, then persist call logs."""
        result = execute_tool_calls(state, ALL_TOOLS)
        tool_messages = result.get("messages") or []
        _persist_tool_calls(state, tool_messages)
        out = {"messages": tool_messages}
        if result.get("tool_loop_halted"):
            out["tool_loop_halted"] = True
        return out

    def should_continue(state: AgentState) -> str:
        """Decide whether to call tools or end."""
        if state.get("tool_loop_halted"):
            return "end"
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "end"

    # Build graph
    workflow = StateGraph(AgentState)

    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tools_node)

    workflow.set_entry_point("agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "end": END},
    )
    # Halted runs short-circuit in agent_node (closing AIMessage, no LLM).
    workflow.add_edge("tools", "agent")

    return workflow.compile()


# Singleton — compiled at import time
agent_graph = build_agent_graph()
