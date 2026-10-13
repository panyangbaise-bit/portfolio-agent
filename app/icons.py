"""Line-icon markup. Shapes live in app/styles/icons.css."""

import html

import streamlit as st


def icon(name: str) -> str:
    return f'<i class="pa-icon pa-icon-{name}" aria-hidden="true"></i>'


def heading(text: str, name: str, level: int = 3) -> None:
    st.markdown(
        f'<h{level} class="pa-heading">{icon(name)}<span>{html.escape(text)}</span></h{level}>',
        unsafe_allow_html=True,
    )


def meta(name: str, text: str) -> None:
    st.markdown(
        f'<p class="pa-meta">{icon(name)}<span>{html.escape(text)}</span></p>',
        unsafe_allow_html=True,
    )
