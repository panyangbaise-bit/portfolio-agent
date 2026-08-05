"""UI smoke tests for floating Ask Agent chat."""

from contextlib import nullcontext
from pathlib import Path

from app.components import ask_agent_chat


class _StatusCM:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def write(self, *args, **kwargs):
        return None

    def update(self, *args, **kwargs):
        return None


class FakeSt:
    def __init__(self):
        self.session_state = {}
        self.buttons = []
        self.chat_messages = []
        self.forms = []
        self.warnings = []

    def markdown(self, *args, **kwargs):
        return None

    def caption(self, *args, **kwargs):
        return None

    def button(self, label, **kwargs):
        self.buttons.append((label, kwargs.get("key")))
        return False

    def columns(self, *args, **kwargs):
        n = args[0] if args else [1, 1]
        count = len(n) if isinstance(n, (list, tuple)) else int(n)
        return [nullcontext() for _ in range(count)]

    def chat_message(self, role):
        self.chat_messages.append(role)
        return nullcontext()

    def form(self, name, **kwargs):
        self.forms.append(name)
        return nullcontext()

    def text_area(self, *args, **kwargs):
        return ""

    def form_submit_button(self, *args, **kwargs):
        return False

    def warning(self, msg):
        self.warnings.append(msg)

    def status(self, *args, **kwargs):
        return _StatusCM()

    def write_stream(self, gen):
        list(gen())

    def rerun(self):
        return None


def test_closed_shows_fab_only(monkeypatch):
    st = FakeSt()
    st.session_state["ask_agent_open"] = False
    monkeypatch.setattr(ask_agent_chat, "st", st)
    monkeypatch.setattr(ask_agent_chat, "t", lambda k, **kw: k)
    ask_agent_chat.render_ask_agent_chat()
    keys = [k for _, k in st.buttons]
    assert "ask_agent_fab" in keys
    assert "ask_agent_close" not in keys
    assert "ask_agent_form" not in st.forms


def test_open_shows_panel_controls(monkeypatch):
    st = FakeSt()
    st.session_state.update({
        "ask_agent_open": True,
        "ask_agent_messages": [{"role": "user", "content": "hi"}],
    })
    monkeypatch.setattr(ask_agent_chat, "st", st)
    monkeypatch.setattr(ask_agent_chat, "t", lambda k, **kw: k)
    ask_agent_chat.render_ask_agent_chat()
    keys = [k for _, k in st.buttons]
    assert "ask_agent_close" in keys
    assert "ask_agent_new" in keys
    assert "user" in st.chat_messages
    assert "ask_agent_form" in st.forms


def test_dashboard_has_no_inline_ask_agent():
    text = Path("app/views/dashboard.py").read_text(encoding="utf-8")
    assert "ask_agent_run" not in text
    assert "st.popover" not in text
    assert "run_ad_hoc_query_stream" not in text


def test_history_for_stream_strips_pending_user_turn():
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ans"},
        {"role": "user", "content": "follow"},
    ]
    hist = ask_agent_chat._history_for_stream(messages, "follow")
    assert hist == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ans"},
    ]
