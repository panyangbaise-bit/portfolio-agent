"""Global LangSmith-style floating Ask Agent chat (FAB + panel)."""

from typing import List

import streamlit as st

from app.i18n import t


def _ensure_state() -> None:
    st.session_state.setdefault("ask_agent_open", False)
    st.session_state.setdefault("ask_agent_messages", [])
    st.session_state.setdefault("ask_agent_pending", None)
    st.session_state.setdefault("ask_agent_busy", False)


def _clear_thread() -> None:
    st.session_state["ask_agent_messages"] = []
    st.session_state["ask_agent_pending"] = None
    st.session_state["ask_agent_busy"] = False


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
    tokens = []
    status_lines = []
    final_text = ""
    errored = False

    if show_ui:
        with st.chat_message("assistant"):
            with st.status(t("ask_agent.streaming"), expanded=True) as status_box:

                def _token_gen():
                    nonlocal final_text, errored
                    for event in run_ad_hoc_query_stream(pending, history=history):
                        etype = event.get("type")
                        text = event.get("text") or ""
                        if etype == "status":
                            status_box.write(text)
                            status_lines.append(text)
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
        for event in run_ad_hoc_query_stream(pending, history=history):
            etype = event.get("type")
            text = event.get("text") or ""
            if etype == "token":
                tokens.append(text)
            elif etype == "error":
                errored = True
                final_text = f"{t('ask_agent.error')} {text}"
                break
            elif etype == "done":
                final_text = text or "".join(tokens)

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
    busy = bool(st.session_state.get("ask_agent_busy"))
    pending = st.session_state.get("ask_agent_pending")
    messages = list(st.session_state.get("ask_agent_messages") or [])

    # CSS hook — parent vertical block is position:fixed via cyberpunk.css
    st.markdown(
        '<div class="pa-ask-agent-root" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )

    if not open_panel:
        if st.button("✦", key="ask_agent_fab", help=t("ask_agent.open"), type="primary"):
            st.session_state["ask_agent_open"] = True
            st.rerun()
        # Collapse hides UI; if a run is in flight, still drain so it can finish.
        if pending:
            _finish_pending(pending, messages, show_ui=False)
        return

    st.markdown(
        '<div class="pa-ask-agent-panel" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )

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

    if pending:
        _finish_pending(pending, messages, show_ui=True)

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
                st.session_state["ask_agent_messages"] = messages + [
                    {"role": "user", "content": text}
                ]
                st.session_state["ask_agent_pending"] = text
                st.session_state["ask_agent_busy"] = True
                st.session_state["ask_agent_open"] = True
                st.rerun()
