"""Ask Agent stream events for progressive dashboard output."""

from langchain_core.messages import AIMessage, ToolMessage

from agent.core import run_ad_hoc_query_stream


def test_run_ad_hoc_query_stream_emits_status_tokens_done(monkeypatch):
    events = []

    class FakeSession:
        session_id = 7

        def start(self):
            return None

        def finish(self, summary=""):
            events.append(("finish", summary))

        def fail(self, summary=""):
            events.append(("fail", summary))

    def fake_stream(state, stream_mode=None):
        yield (
            "updates",
            {
                "agent": {
                    "messages": [
                        AIMessage(
                            content="",
                            tool_calls=[{
                                "name": "get_portfolio",
                                "args": {},
                                "id": "c1",
                            }],
                        )
                    ]
                }
            },
        )
        yield (
            "updates",
            {
                "tools": {
                    "messages": [
                        ToolMessage(content="[]", tool_call_id="c1", name="get_portfolio")
                    ]
                }
            },
        )
        yield (
            "updates",
            {"agent": {"messages": [AIMessage(content="组合健康，半导体约 23%。")]}},
        )

    monkeypatch.setattr(
        "agent.core.AgentSessionManager",
        lambda **kwargs: FakeSession(),
    )
    monkeypatch.setattr("agent.core.agent_graph.stream", fake_stream)
    monkeypatch.setattr("agent.core.config.AGENT_RUN_TIMEOUT", 30)

    out = list(run_ad_hoc_query_stream("仓位权重如何？"))
    types = [e["type"] for e in out]
    assert "status" in types
    assert "token" in types
    assert types[-1] == "done"
    assert "23%" in out[-1]["text"]
    assert events[0][0] == "finish"


def test_run_ad_hoc_query_stream_includes_history_in_state(monkeypatch):
    captured = {}

    class FakeSession:
        session_id = 9

        def start(self):
            return None

        def finish(self, summary=""):
            return None

        def fail(self, summary=""):
            return None

    def fake_stream(state, stream_mode=None):
        captured["messages"] = state["messages"]
        yield ("updates", {"agent": {"messages": [AIMessage(content="ok")]}})

    monkeypatch.setattr(
        "agent.core.AgentSessionManager",
        lambda **kwargs: FakeSession(),
    )
    monkeypatch.setattr("agent.core.agent_graph.stream", fake_stream)
    monkeypatch.setattr("agent.core.config.AGENT_RUN_TIMEOUT", 30)

    list(
        run_ad_hoc_query_stream(
            "那港股呢？",
            history=[
                {"role": "user", "content": "美股偏重吗？"},
                {"role": "assistant", "content": "QQQ 约 40%。"},
            ],
        )
    )
    from langchain_core.messages import HumanMessage

    msgs = captured["messages"]
    assert isinstance(msgs[0], HumanMessage) and "美股" in msgs[0].content
    assert isinstance(msgs[1], AIMessage) and "40%" in msgs[1].content
    assert isinstance(msgs[2], HumanMessage) and "港股" in msgs[2].content
