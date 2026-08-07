"""Agent max-round guard forces a final no-tools synthesis."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent import graph as graph_mod


def test_agent_node_force_final_after_max_rounds(monkeypatch):
    calls = {"with_tools": 0, "plain": 0}

    class FakeBound:
        def invoke(self, messages):
            calls["with_tools"] += 1
            return AIMessage(
                content="",
                tool_calls=[{
                    "name": "get_portfolio",
                    "args": {},
                    "id": f"t{calls['with_tools']}",
                    "type": "tool_call",
                }],
            )

    class FakeLLM:
        def bind_tools(self, tools):
            return FakeBound()

        def invoke(self, messages):
            calls["plain"] += 1
            return AIMessage(content="forced final")

    def instant_tools(state, tools, **kwargs):
        ai = None
        for msg in reversed(state.get("messages") or []):
            if getattr(msg, "tool_calls", None):
                ai = msg
                break
        tc = ai.tool_calls[0]
        tc_id = tc["id"] if isinstance(tc, dict) else tc.id
        return {
            "messages": [
                ToolMessage(content="{}", tool_call_id=tc_id, name="get_portfolio")
            ],
            "tool_loop_halted": False,
        }

    monkeypatch.setattr(graph_mod, "build_deepseek_llm", lambda: FakeLLM())
    monkeypatch.setattr(graph_mod, "execute_tool_calls", instant_tools)
    monkeypatch.setattr(graph_mod, "_persist_tool_calls", lambda *a, **k: None)
    monkeypatch.setattr(graph_mod.config, "AGENT_MAX_ROUNDS", 2)

    g = graph_mod.build_agent_graph()
    out = g.invoke({
        "messages": [HumanMessage(content="hi")],
        "session_id": 1,
        "triggered_by": "manual",
        "extra_context": "",
    })

    assert calls["with_tools"] == 2
    assert calls["plain"] == 1
    assert out["messages"][-1].content == "forced final"
    assert out.get("tool_loop_halted") is True
