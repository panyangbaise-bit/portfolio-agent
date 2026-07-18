"""LangGraph state graph for the portfolio agent.

Defines the ReAct-style agent loop:
  agent_node (LLM reasoning + tool selection)
    → tool_node (execute tool)
    → agent_node (continue reasoning with tool result)
    → END

Uses DeepSeek API via ChatOpenAI (OpenAI-compatible interface).
"""

from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from config import config
from agent.system_prompt import SYSTEM_PROMPT
from agent.tools import ALL_TOOLS


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    session_id: int
    triggered_by: str
    extra_context: str


def build_agent_graph() -> StateGraph:
    """Build and compile the LangGraph agent graph with DeepSeek."""

    llm = ChatOpenAI(
        model=config.DEEPSEEK_MODEL,
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        temperature=0.3,
        max_tokens=4096,
    )

    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    def agent_node(state: AgentState) -> dict:
        """Agent reasoning node. Calls the LLM with tools bound."""
        messages = state["messages"]

        # Ensure system prompt is first
        has_system = any(isinstance(m, SystemMessage) for m in messages)
        if not has_system:
            prompt = SYSTEM_PROMPT
            extra = state.get("extra_context", "")
            if extra:
                prompt = prompt + "\n\n" + extra
            messages = [SystemMessage(content=prompt)] + list(messages)

        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    tool_node = ToolNode(ALL_TOOLS)

    def should_continue(state: AgentState) -> str:
        """Decide whether to call tools or end."""
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "end"

    # Build graph
    workflow = StateGraph(AgentState)

    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)

    workflow.set_entry_point("agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "end": END},
    )
    workflow.add_edge("tools", "agent")

    return workflow.compile()


# Singleton — compiled at import time
agent_graph = build_agent_graph()
