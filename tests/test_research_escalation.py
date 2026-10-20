import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.research import news_identity, select_news, verification_plan


def empty_search(query="多邻国,纳斯达克", results=None):
    return [
        HumanMessage(content="分析"),
        AIMessage(
            content="",
            tool_calls=[
                {"id": "news", "name": "search_ticker_news", "args": {"ticker": query, "days": 3}}
            ],
        ),
        ToolMessage(
            name="search_ticker_news",
            tool_call_id="news",
            content=json.dumps(
                {"batch": True, "results": results or {"多邻国": [], "纳斯达克": []}}
            ),
        ),
    ]


def test_empty_search_escalates_once_per_identity_and_budget():
    messages = empty_search(results={"多邻国": [], "DUOLINGO": [], "纳斯达克": []})
    plan = verification_plan(messages)
    assert len(plan) == 2
    assert "Duolingo" in plan[0]["query"]
    assert "-site:wallstreetcn.com" in plan[0]["query"]
    messages += [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": str(i),
                    "name": "web_search",
                    "args": {k: v for k, v in p.items() if k != "reason"},
                }
                for i, p in enumerate(plan)
            ],
        )
    ]
    assert verification_plan(messages) == []


def test_previous_turn_search_does_not_satisfy_current_coverage():
    old = AIMessage(
        content="",
        tool_calls=[{"id": "old", "name": "web_search", "args": {"query": "Duolingo DUOL"}}],
    )
    assert verification_plan([old] + empty_search())


def test_headlines_cannot_displace_holding_news():
    articles = [{"title": str(i), "category": "headline"} for i in range(30)]
    articles += [{"title": "earnings", "category": "ticker", "related_ticker": "DUOL"}]
    assert select_news(articles)[0]["title"] == "earnings"
    assert news_identity("DUOL")[1] == "多邻国"


def test_graph_executes_fallback_before_accepting_a_final_answer(monkeypatch):
    from agent import graph

    called = []

    class FakeLLM:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            assert any(getattr(m, "name", "") == "web_search" for m in messages)
            return AIMessage(content="仍有待核实，不能断言无负面新闻。")

    def execute(state, tools):
        calls = state["messages"][-1].tool_calls
        called.extend(c["name"] for c in calls)
        return {
            "messages": [
                ToolMessage(
                    name=c["name"],
                    tool_call_id=c["id"],
                    content=json.dumps({"results": [], "error": "not_configured"}),
                )
                for c in calls
            ]
        }

    monkeypatch.setattr(graph, "build_deepseek_llm", FakeLLM)
    monkeypatch.setattr(graph, "execute_tool_calls", execute)
    monkeypatch.setattr(graph, "_persist_tool_calls", lambda *args: None)
    result = graph.build_agent_graph().invoke({"messages": empty_search(), "session_id": 1})
    assert called == ["web_search", "web_search"]
    assert "不能断言" in result["messages"][-1].content
