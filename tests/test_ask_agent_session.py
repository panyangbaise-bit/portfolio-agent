"""Ask Agent history trim, session reuse, and max-round guard."""

from langchain_core.messages import AIMessage, HumanMessage

from agent.core import _trim_ask_agent_history, run_ad_hoc_query_stream


def test_trim_ask_agent_history_keeps_last_n_pairs():
    history = []
    for i in range(8):
        history.append({"role": "user", "content": f"q{i}"})
        history.append({"role": "assistant", "content": f"a{i}"})
    trimmed = _trim_ask_agent_history(history, max_turns=6)
    assert len(trimmed) == 12
    assert trimmed[0]["content"] == "q2"
    assert trimmed[-1]["content"] == "a7"


def test_trim_ask_agent_history_drops_leading_assistant():
    history = [
        {"role": "assistant", "content": "orphan"},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a"},
    ]
    trimmed = _trim_ask_agent_history(history, max_turns=6)
    assert trimmed[0]["role"] == "user"


def test_run_ad_hoc_reuses_session_id(monkeypatch):
    created = []

    class FakeSession:
        def __init__(self, **kwargs):
            self.session_id = None
            self._resumed = False
            self.summaries = []

        def start_or_resume(self, session_id=None):
            created.append(session_id)
            if session_id:
                self.session_id = session_id
                self._resumed = True
            else:
                self.session_id = 42
                self._resumed = False
            return self.session_id

        def finish(self, summary=""):
            self.summaries.append(summary)

        def fail(self, summary=""):
            pass

    sessions = []

    def factory(**kwargs):
        s = FakeSession(**kwargs)
        sessions.append(s)
        return s

    def fake_stream(state, stream_mode=None):
        yield ("updates", {"agent": {"messages": [AIMessage(content="ans")]}})

    monkeypatch.setattr("agent.core.AgentSessionManager", factory)
    monkeypatch.setattr("agent.core.agent_graph.stream", fake_stream)
    monkeypatch.setattr("agent.core.config.AGENT_RUN_TIMEOUT", 30)
    monkeypatch.setattr("agent.core.config.ASK_AGENT_HISTORY_TURNS", 6)

    out1 = list(run_ad_hoc_query_stream("first"))
    assert out1[-1]["session_id"] == 42
    assert created == [None]

    out2 = list(
        run_ad_hoc_query_stream(
            "follow",
            history=[
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "ans"},
            ],
            session_id=42,
        )
    )
    assert out2[-1]["session_id"] == 42
    assert created == [None, 42]
    assert sessions[1]._resumed is True
    assert sessions[1].summaries[0].startswith("Q: follow")


def test_run_ad_hoc_trims_history_before_state(monkeypatch):
    captured = {}

    class FakeSession:
        session_id = 1

        def start_or_resume(self, session_id=None):
            return 1

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
    monkeypatch.setattr("agent.core.config.ASK_AGENT_HISTORY_TURNS", 1)

    history = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "old-a"},
        {"role": "user", "content": "new"},
        {"role": "assistant", "content": "new-a"},
    ]
    list(run_ad_hoc_query_stream("now?", history=history))
    msgs = captured["messages"]
    assert isinstance(msgs[0], HumanMessage) and msgs[0].content == "new"
    assert isinstance(msgs[1], AIMessage) and msgs[1].content == "new-a"
    assert isinstance(msgs[2], HumanMessage) and msgs[2].content == "now?"
