# Ask Agent Floating Chat — Design

**Date:** 2026-08-05  
**Status:** Approved for implementation planning  
**Reference:** LangSmith project Chat (FAB + floating panel)

## Problem

Ask Agent today uses a Dashboard header `st.popover` for input, then streams the answer in the **main Dashboard body**. That pushes KPI/holdings down, only exists on Dashboard, and is single-turn. We want a LangSmith-style assistant: a floating button that opens/closes a dedicated chat window for input and streaming output.

## Goals

- Floating Ask Agent chat that opens and collapses
- Streaming (tokens + tool status) only inside the chat panel — never in page body
- Multi-turn follow-ups with conversation context in the same thread
- Available on **all** pages (not Dashboard-only)
- Preserve cyberpunk theme and EN/CN i18n
- Collapse hides the panel; streaming still requires the browser tab/page to stay open (Streamlit constraint)

## Non-goals

- Persistent chat History list across browser sessions / DB-backed thread browser (LangSmith History)
- Background completion after navigating away or closing the tab
- Pure HTML/JS iframe chat shell
- Centered `st.dialog` modal as the primary UX
- Changing scheduled-job agent behavior

## Decisions

| Topic | Choice |
|-------|--------|
| Conversation model | Multi-turn thread in `st.session_state` |
| Placement | Global FAB on every page |
| Panel shape | Bottom-right floating card (~360×520), LangSmith-like |
| Collapse while streaming | Hide panel only; stream continues only while page remains open |
| Implementation approach | Streamlit chat widgets + CSS `position: fixed` overlay |

## UX

### Collapsed

- Circular FAB fixed bottom-right (above mobile safe area / locale toggle conflicts checked in CSS)
- Click → open panel (`ask_agent_open = True`)

### Open

- Floating card overlay; does not reflow Dashboard/holdings layout
- Header: title “Ask Agent” / “询问助手”, **New Chat (＋)**, **Close (✕)**
- Body: scrollable messages
  - User bubbles
  - Optional compact tool-status lines during a run
  - Assistant bubbles (streamed)
- Footer: text input + send
- Empty state: v1 ships **without** suggestion chips (YAGNI); can add later

### Removed from Dashboard

- Header-column `st.popover` Ask Agent control
- Body `st.subheader` / `st.status` / `st.write_stream` / last-response expander for Ask Agent

## Architecture

```
app/main.py
  └─ after page view: render_ask_agent_chat()

app/components/ask_agent_chat.py
  ├─ FAB / panel chrome (open, close, new chat)
  ├─ message list (st.chat_message or custom markdown)
  ├─ pending stream consumer (status + write_stream)
  └─ input + send

app/styles (theme CSS inject)
  └─ fixed FAB + panel rules (desktop + mobile)

agent/core.py
  └─ run_ad_hoc_query_stream(question, history=...) → same event types
```

### session_state

| Key | Type | Purpose |
|-----|------|---------|
| `ask_agent_open` | `bool` | Panel visibility |
| `ask_agent_messages` | `list[dict]` | Current thread `{role, content}` (+ optional `statuses`) |
| `ask_agent_pending` | `str \| None` | User text awaiting stream this run |
| `ask_agent_busy` | `bool` | Disable send while streaming |

**New Chat:** clear `ask_agent_messages` / pending; next send starts a new `AgentSessionManager` run (new `agent_sessions` row with `job_id=ask_agent`).

### Multi-turn data flow

1. User sends text → append `{role: user, content}` → set `ask_agent_pending` → `ask_agent_busy=True` → rerun  
2. While pending: inside open panel, call `run_ad_hoc_query_stream(question, history=prior_messages)`  
3. Emit `status` lines into the in-progress assistant area; `token` via `st.write_stream`  
4. On `done`: append assistant message; clear pending/busy  
5. On `error`: show error in panel; clear pending/busy; do not treat as successful assistant turn  
6. Close (✕): `ask_agent_open=False` only  

`history` passed to the agent is prior completed turns (user/assistant text), **excluding** the pending question which is the new `HumanMessage`.

### Agent API change

Extend streaming entrypoint (keep event contract):

```text
run_ad_hoc_query_stream(question: str, history: Optional[list[dict]] = None)
```

- Build LangGraph `messages` as: prior Human/AI pairs from `history`, then current `HumanMessage(question)`
- Still one `AgentSessionManager` per user send (each turn is one DB session / tool log), with full prior chat text in the graph messages for context
- Events unchanged: `status` | `token` | `done` | `error`

## Styling constraints

- Reuse `inject_cyberpunk_theme()` pattern; do **not** inject panel CSS via `st.markdown` (strips `<style>`)
- Avoid covering locale toggle / mobile sidebar expand control
- Panel `z-index` above main content, below any auth gate if relevant
- On narrow screens: panel width up to ~`min(360px, 100vw - 24px)`, height capped so input stays visible

## Error handling

- Empty input → inline warning, no agent call  
- Timeout / exception → panel error text via existing stream `error` event  
- Concurrent send blocked while `ask_agent_busy`  
- All user-visible strings via `app.i18n.t()`  

## Testing

- Unit: `run_ad_hoc_query_stream` with `history` builds multi-turn `messages` (mock graph.stream)  
- Unit: existing status/token/done/error contract still holds  
- UI smoke (mocked `st`): Dashboard no longer mounts old popover/body stream; `render_ask_agent_chat` shows FAB when closed and message chrome when open  
- Manual: open/close on Dashboard + Jobs; follow-up uses context; New Chat clears; stream appears only in panel  

## Acceptance criteria

1. Dashboard top has no Ask Agent stream or popover  
2. Every nav page shows FAB; open/close works  
3. Streaming + tool status render inside the floating panel only  
4. Follow-up questions in the same thread include prior context  
5. New Chat clears the thread  
6. EN/CN strings present for new UI chrome  

## Implementation notes (for plan)

- Prefer extracting chat UI before deleting Dashboard hooks so behavior can be verified  
- CSS selectors must target a stable wrapper (e.g. `st.container` key / data attribute via parent structure); expect one iteration on DOM targeting under Streamlit  
- Update `CLAUDE.md` Ask Agent gotcha: popover → global floating chat  
