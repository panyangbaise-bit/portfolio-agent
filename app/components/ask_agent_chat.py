"""Global LangSmith-style floating Ask Agent chat (FAB + panel)."""

from typing import List, Optional

import streamlit as st

from app.i18n import t
from app.styles.theme import inject_ask_agent_dock


def _ensure_state() -> None:
    st.session_state.setdefault("ask_agent_open", False)
    st.session_state.setdefault("ask_agent_messages", [])
    st.session_state.setdefault("ask_agent_pending", None)
    st.session_state.setdefault("ask_agent_busy", False)
    st.session_state.setdefault("ask_agent_db_session_id", None)


def _clear_thread() -> None:
    st.session_state["ask_agent_messages"] = []
    st.session_state["ask_agent_pending"] = None
    st.session_state["ask_agent_busy"] = False
    # New chat → new Jobs history row on the next question.
    st.session_state["ask_agent_db_session_id"] = None


def _history_for_stream(messages: List[dict], pending: str) -> List[dict]:
    """Prior completed turns only — exclude the pending user question."""
    history = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content") or ""
        if role not in ("user", "assistant") or not content:
            continue
        history.append({"role": role, "content": content})
    if (
        history
        and history[-1]["role"] == "user"
        and history[-1]["content"] == pending
    ):
        history = history[:-1]
    return history


def _finish_pending(pending: str, messages: List[dict], show_ui: bool) -> None:
    """Run the agent stream for ``pending`` and persist the assistant turn.

    When ``show_ui`` is False (panel collapsed), still drain the stream so the
    page-open run can finish; do not leave tokens in the main page body.
    """
    from agent.core import run_ad_hoc_query_stream

    history = _history_for_stream(messages, pending)
    db_session_id: Optional[int] = st.session_state.get("ask_agent_db_session_id")
    tokens = []
    final_text = ""
    errored = False

    def _consume(event: dict) -> None:
        nonlocal final_text, errored, db_session_id
        etype = event.get("type")
        text = event.get("text") or ""
        sid = event.get("session_id")
        if sid:
            db_session_id = sid
            st.session_state["ask_agent_db_session_id"] = sid
        if etype == "token":
            tokens.append(text)
        elif etype == "error":
            errored = True
            final_text = f"{t('ask_agent.error')} {text}"
        elif etype == "done":
            final_text = text or "".join(tokens)

    if show_ui:
        with st.chat_message("assistant"):
            with st.status(t("ask_agent.streaming"), expanded=True) as status_box:

                def _token_gen():
                    nonlocal final_text, errored
                    for event in run_ad_hoc_query_stream(
                        pending,
                        history=history,
                        session_id=db_session_id,
                    ):
                        etype = event.get("type")
                        text = event.get("text") or ""
                        sid = event.get("session_id")
                        if sid:
                            st.session_state["ask_agent_db_session_id"] = sid
                        if etype == "status":
                            status_box.write(text)
                        elif etype == "token":
                            tokens.append(text)
                            yield text
                        elif etype == "error":
                            errored = True
                            final_text = f"{t('ask_agent.error')} {text}"
                            status_box.update(label=t("ask_agent.error"), state="error")
                            status_box.write(text)
                            return
                        elif etype == "done":
                            final_text = text or "".join(tokens)
                            status_box.update(label=t("ask_agent.done"), state="complete")

                st.write_stream(_token_gen())
    else:
        for event in run_ad_hoc_query_stream(
            pending,
            history=history,
            session_id=db_session_id,
        ):
            _consume(event)
            if errored:
                break

    if not final_text and tokens and not errored:
        final_text = "".join(tokens)

    if final_text:
        st.session_state["ask_agent_messages"] = messages + [
            {"role": "assistant", "content": final_text}
        ]
    st.session_state["ask_agent_pending"] = None
    st.session_state["ask_agent_busy"] = False


def render_ask_agent_chat() -> None:
    """Render fixed FAB / floating chat panel (call from app/main.py every page)."""
    _ensure_state()

    open_panel = bool(st.session_state.get("ask_agent_open"))
    pending = st.session_state.get("ask_agent_pending")
    messages = list(st.session_state.get("ask_agent_messages") or [])

    # CSS/JS hook — dock script pins the leaf host bottom-right.
    st.markdown(
        '<div class="pa-ask-agent-root" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )

    if not open_panel:
        if st.button("✦", key="ask_agent_fab", help=t("ask_agent.open"), type="primary"):
            st.session_state["ask_agent_open"] = True
            st.rerun()
        if pending:
            _finish_pending(pending, messages, show_ui=False)
        inject_ask_agent_dock()
        return

    st.markdown(
        '<div class="pa-ask-agent-panel" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    # Dock before heavy stream widgets so mid-reply mutations keep the float.
    inject_ask_agent_dock()

    busy = bool(st.session_state.get("ask_agent_busy"))

    hdr_l, hdr_mid, hdr_r = st.columns([4, 1, 1])
    with hdr_l:
        st.markdown(f"**{t('ask_agent.title')}**")
    with hdr_mid:
        if st.button("＋", key="ask_agent_new", help=t("ask_agent.new_chat"), disabled=busy):
            _clear_thread()
            st.rerun()
    with hdr_r:
        if st.button("✕", key="ask_agent_close", help=t("ask_agent.close")):
            st.session_state["ask_agent_open"] = False
            st.rerun()

    if not messages and not pending:
        st.caption(t("ask_agent.empty_thread"))

    for msg in messages:
        role = msg.get("role") or "assistant"
        with st.chat_message("user" if role == "user" else "assistant"):
            st.markdown(msg.get("content") or "")

    finished_stream = False
    if pending:
        _finish_pending(pending, messages, show_ui=True)
        finished_stream = True

    # Re-read after stream — stale busy=True would leave the input disabled.
    busy = bool(st.session_state.get("ask_agent_busy"))
    if finished_stream:
        # Refresh so completed messages + enabled input render cleanly in-panel.
        st.rerun()

    with st.form("ask_agent_form", clear_on_submit=True):
        question = st.text_area(
            t("ask_agent.title"),
            placeholder=t("ask_agent.placeholder"),
            label_visibility="collapsed",
            key="ask_agent_input",
            height=80,
            disabled=busy,
        )
        submitted = st.form_submit_button(
            t("ask_agent.send"),
            type="primary",
            disabled=busy,
        )
        if submitted:
            text = (question or "").strip()
            if not text:
                st.warning(t("ask_agent.empty"))
            elif not busy:
                st.session_state["ask_agent_messages"] = list(
                    st.session_state.get("ask_agent_messages") or []
                ) + [{"role": "user", "content": text}]
                st.session_state["ask_agent_pending"] = text
                st.session_state["ask_agent_busy"] = True
                st.session_state["ask_agent_open"] = True
                st.rerun()
