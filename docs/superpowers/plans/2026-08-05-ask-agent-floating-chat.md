# Ask Agent Floating Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Dashboard popover Ask Agent with a global LangSmith-style floating chat (FAB + multi-turn panel, streaming inside panel only).

**Architecture:** CSS-fixed Streamlit chat UI rendered from `app/main.py` on every page; `run_ad_hoc_query_stream` accepts prior message history for multi-turn; Dashboard body no longer hosts Ask Agent I/O.

**Tech Stack:** Streamlit, LangGraph stream events, existing cyberpunk theme inject, `app.i18n`

**Spec:** `docs/superpowers/specs/2026-08-05-ask-agent-floating-chat-design.md`

---

## File map

| File | Responsibility |
|------|----------------|
| `agent/core.py` | `run_ad_hoc_query_stream(question, history=None)` builds multi-turn messages |
| `app/components/ask_agent_chat.py` | FAB, panel, messages, stream, new chat |
| `app/styles/cyberpunk.css` | Fixed FAB + panel layout |
| `app/styles/theme.py` | No change unless inject helpers needed |
| `app/i18n.py` | New chrome strings EN/CN |
| `app/main.py` | Call `render_ask_agent_chat()` after page exec |
| `app/views/dashboard.py` | Remove popover + body stream |
| `CLAUDE.md` | Update Ask Agent gotcha |
| `tests/test_ask_agent_stream.py` | History → multi-turn state messages |
| `tests/test_ask_agent_chat_ui.py` | Mocked Streamlit open/closed + dashboard cleanup |

---

### Task 1: Multi-turn stream history

**Files:**
- Modify: `agent/core.py`
- Test: `tests/test_ask_agent_stream.py`

- [ ] **Step 1: Write failing test for history**

Add to `tests/test_ask_agent_stream.py`:

```python
def test_run_ad_hoc_query_stream_includes_history_in_state(monkeypatch):
    captured = {}

    class FakeSession:
        session_id = 9
        def start(self): return None
        def finish(self, summary=""): pass
        def fail(self, summary=""): pass

    def fake_stream(state, stream_mode=None):
        captured["messages"] = state["messages"]
        from langchain_core.messages import AIMessage
        yield ("updates", {"agent": {"messages": [AIMessage(content="ok")]}})

    monkeypatch.setattr("agent.core.AgentSessionManager", lambda **kwargs: FakeSession())
    monkeypatch.setattr("agent.core.agent_graph.stream", fake_stream)
    monkeypatch.setattr("agent.core.config.AGENT_RUN_TIMEOUT", 30)

    list(run_ad_hoc_query_stream(
        "那港股呢？",
        history=[
            {"role": "user", "content": "美股偏重吗？"},
            {"role": "assistant", "content": "QQQ 约 40%。"},
        ],
    ))
    from langchain_core.messages import HumanMessage, AIMessage
    msgs = captured["messages"]
    assert isinstance(msgs[0], HumanMessage) and "美股" in msgs[0].content
    assert isinstance(msgs[1], AIMessage) and "40%" in msgs[1].content
    assert isinstance(msgs[2], HumanMessage) and "港股" in msgs[2].content
```

- [ ] **Step 2: Run test — expect FAIL** (history kw unsupported or messages length 1)

`PYTHONPATH=. python3 -m pytest tests/test_ask_agent_stream.py::test_run_ad_hoc_query_stream_includes_history_in_state -v`

- [ ] **Step 3: Implement history in `run_ad_hoc_query_stream`**

```python
def run_ad_hoc_query_stream(
    question: str,
    history: Optional[list] = None,
) -> Iterator[Dict[str, Any]]:
    ...
    prior = []
    for turn in history or []:
        role = (turn.get("role") or "").strip().lower()
        content = turn.get("content") or ""
        if not content:
            continue
        if role == "user":
            prior.append(HumanMessage(content=content))
        elif role == "assistant":
            prior.append(AIMessage(content=content))
    state = {
        "messages": prior + [HumanMessage(content=question)],
        ...
    }
```

Ensure `AIMessage` is imported in `agent/core.py` (already used via AIMessageChunk path — add `AIMessage` to imports if missing).

- [ ] **Step 4: Run both stream tests — PASS**

`PYTHONPATH=. python3 -m pytest tests/test_ask_agent_stream.py -v`

- [ ] **Step 5: Commit**

```bash
git add agent/core.py tests/test_ask_agent_stream.py
git commit -m "feat: pass chat history into Ask Agent stream"
```

---

### Task 2: i18n strings for floating chat

**Files:**
- Modify: `app/i18n.py`

- [ ] **Step 1: Add EN/CN keys**

Replace/extend ask_agent keys:

```python
# EN
"ask_agent.title": "Ask Agent",
"ask_agent.open": "Open Ask Agent",
"ask_agent.close": "Close",
"ask_agent.new_chat": "New chat",
"ask_agent.placeholder": "Ask a follow-up…",
"ask_agent.send": "Send",
"ask_agent.empty": "Please enter a question.",
"ask_agent.streaming": "Agent streaming…",
"ask_agent.error": "Ask Agent failed:",
"ask_agent.done": "Done",
"ask_agent.empty_thread": "Ask about your portfolio, risk, or what to adjust.",

# ZH
"ask_agent.title": "询问助手",
"ask_agent.open": "打开询问助手",
"ask_agent.close": "收起",
"ask_agent.new_chat": "新对话",
"ask_agent.placeholder": "继续追问…",
"ask_agent.send": "发送",
"ask_agent.empty": "请输入问题。",
"ask_agent.streaming": "助手流式输出中…",
"ask_agent.error": "询问助手失败：",
"ask_agent.done": "完成",
"ask_agent.empty_thread": "可以问持仓、风险或调仓建议。",
```

Keep deprecated keys (`popover`, `response`, …) only if still referenced; remove unused after Dashboard cleanup.

- [ ] **Step 2: Commit**

```bash
git add app/i18n.py
git commit -m "feat: i18n for Ask Agent floating chat chrome"
```

---

### Task 3: Floating chat component + CSS

**Files:**
- Create: `app/components/ask_agent_chat.py`
- Modify: `app/styles/cyberpunk.css`
- Test: `tests/test_ask_agent_chat_ui.py`

- [ ] **Step 1: Failing UI smoke tests**

```python
# tests/test_ask_agent_chat_ui.py
from contextlib import nullcontext
from types import SimpleNamespace
from app.components import ask_agent_chat

class FakeSt:
    def __init__(self):
        self.session_state = {}
        self.buttons = []
        self.chat_messages = []
        self.markdowns = []
    def container(self, **kwargs):
        return nullcontext()
    def button(self, label, **kwargs):
        self.buttons.append((label, kwargs.get("key")))
        return False
    def columns(self, *a, **k):
        return [nullcontext(), nullcontext(), nullcontext()]
    def chat_message(self, role):
        self.chat_messages.append(role)
        return nullcontext()
    def markdown(self, *a, **k):
        self.markdowns.append(a[0] if a else "")
    def caption(self, *a, **k): pass
    def text_area(self, *a, **k): return ""
    def text_input(self, *a, **k): return ""
    def warning(self, *a, **k): pass
    def write(self, *a, **k): pass
    def write_stream(self, gen):
        list(gen())
    def status(self, *a, **k):
        return nullcontext()
    def rerun(self): pass
    def divider(self): pass

def test_closed_shows_fab_only(monkeypatch):
    st = FakeSt()
    st.session_state["ask_agent_open"] = False
    monkeypatch.setattr(ask_agent_chat, "st", st)
    monkeypatch.setattr(ask_agent_chat, "t", lambda k, **kw: k)
    ask_agent_chat.render_ask_agent_chat()
    keys = [k for _, k in st.buttons]
    assert "ask_agent_fab" in keys
    assert "ask_agent_close" not in keys

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
```

- [ ] **Step 2: Run — FAIL** (module missing)

- [ ] **Step 3: Implement `ask_agent_chat.py`**

Behavior outline:
- Init defaults: `ask_agent_open=False`, `messages=[]`, `pending=None`, `busy=False`
- Outer wrapper: `st.container` + marker `st.markdown('<div class="pa-ask-agent-root"></div>', unsafe_allow_html=True)` for CSS `:has()`
- If not open: FAB button key `ask_agent_fab` → set open True + rerun
- If open: header row (title, new, close); render messages; if pending, stream inside panel then clear pending; input + send (disabled when busy)

Streaming block mirrors old dashboard logic but writes into panel only; on done append assistant message; on error append/show error and clear busy.

Send: trim text; empty → warning; else append user, set pending+busy, open=True, rerun.

New chat: clear messages/pending/busy (keep open).

- [ ] **Step 4: Add CSS to `cyberpunk.css`**

```css
/* Ask Agent floating chat — fixed bottom-right (LangSmith-style) */
div[data-testid="stVerticalBlock"]:has(.pa-ask-agent-root) {
  position: fixed !important;
  right: 1rem !important;
  bottom: 1rem !important;
  width: min(360px, calc(100vw - 1.5rem)) !important;
  z-index: 999990 !important;
  background: transparent !important;
}
/* when open, expand panel card look on inner block */
.pa-ask-agent-panel {
  /* marker class via markdown inside open panel */
}
```

Tune selectors so closed FAB is a small circle and open panel is ~520px tall max; ensure locale toggle (z-index 1000000) stays clickable above FAB.

- [ ] **Step 5: Tests PASS**

`PYTHONPATH=. python3 -m pytest tests/test_ask_agent_chat_ui.py -v`

- [ ] **Step 6: Commit**

```bash
git add app/components/ask_agent_chat.py app/styles/cyberpunk.css tests/test_ask_agent_chat_ui.py
git commit -m "feat: add floating Ask Agent chat component"
```

---

### Task 4: Wire into main + strip Dashboard

**Files:**
- Modify: `app/main.py`
- Modify: `app/views/dashboard.py`
- Test: extend `tests/test_ask_agent_chat_ui.py` or dashboard smoke

- [ ] **Step 1: Test that dashboard module source no longer contains popover ask flow**

```python
from pathlib import Path
def test_dashboard_has_no_inline_ask_agent():
    text = Path("app/views/dashboard.py").read_text()
    assert "ask_agent_run" not in text
    assert "st.popover" not in text
    assert "run_ad_hoc_query_stream" not in text
```

- [ ] **Step 2: FAIL then clean `dashboard.py`** — title only left column full width; remove hdr columns / popover / stream block

- [ ] **Step 3: `main.py` after `exec` page:**

```python
from app.components.ask_agent_chat import render_ask_agent_chat
render_ask_agent_chat()
```

- [ ] **Step 4: Run related tests PASS**

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/views/dashboard.py tests/test_ask_agent_chat_ui.py
git commit -m "feat: mount global Ask Agent chat; remove dashboard popover"
```

---

### Task 5: Docs + full test suite

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update Ask Agent gotcha** — popover → global floating chat; multi-turn in session_state; streaming in panel only

- [ ] **Step 2: `PYTHONPATH=. python3 -m pytest tests -v`** — all green

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: Ask Agent is a global floating chat"
```

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| FAB open/close | 3 |
| Stream in panel only | 3–4 |
| Multi-turn history | 1, 3 |
| All pages | 4 (`main.py`) |
| Remove dashboard popover/body | 4 |
| i18n | 2 |
| Collapse = hide only | 3 |
| No history persistence | N/A (non-goal) |
| CLAUDE.md | 5 |
| Tests | 1, 3, 4, 5 |
