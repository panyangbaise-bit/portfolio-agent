# Cyberpunk UI + Collapsible Ask Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse Ask Agent into a header popover and apply a global cyberpunk theme across the Streamlit app without changing agent/DB logic.

**Architecture:** Theme CSS lives in `app/styles/cyberpunk.css` and is injected every Streamlit run via `inject_cyberpunk_theme()` in `app/styles/theme.py`, called from `app/main.py`. Dashboard drops the 3/2 column split; Ask Agent moves into `st.popover` on the title row so holdings use full width.

**Tech Stack:** Streamlit ≥1.33 (`st.popover`), custom CSS, Google Fonts (Orbitron + Share Tech Mono), existing `run_ad_hoc_query`.

**Spec:** `docs/superpowers/specs/2026-07-18-cyberpunk-ui-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `app/styles/__init__.py` | Package marker |
| `app/styles/cyberpunk.css` | Neon dark theme tokens + Streamlit selectors |
| `app/styles/theme.py` | Load CSS/fonts; `inject_cyberpunk_theme()`; safe missing-file handling |
| `app/main.py` | Call inject after `set_page_config`; sidebar brand polish |
| `app/pages/dashboard.py` | Header + popover Ask Agent; full-width holdings |
| `app/components/kpi_cards.py` | Title/label polish only (no calc changes) |
| `app/components/holdings_table.py` | Header polish only |
| `requirements.txt` | Bump streamlit floor |
| `CLAUDE.md` | Document theme + popover |
| `tests/test_theme.py` | Unit test CSS load / missing file |

---

### Task 1: Bump Streamlit + theme package skeleton

**Files:**
- Modify: `requirements.txt`
- Create: `app/styles/__init__.py`
- Create: `app/styles/theme.py` (minimal stubs)
- Create: `tests/test_theme.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_theme.py`:

```python
from pathlib import Path

from app.styles.theme import load_cyberpunk_css, build_theme_markdown


def test_load_cyberpunk_css_returns_nonempty_when_file_exists(tmp_path, monkeypatch):
    css_file = tmp_path / "cyberpunk.css"
    css_file.write_text(":root { --cp-cyan: #00f0ff; }", encoding="utf-8")
    monkeypatch.setattr("app.styles.theme.CSS_PATH", css_file)
    assert "--cp-cyan" in load_cyberpunk_css()


def test_load_cyberpunk_css_returns_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("app.styles.theme.CSS_PATH", tmp_path / "missing.css")
    assert load_cyberpunk_css() == ""


def test_build_theme_markdown_includes_style_and_fonts():
    md = build_theme_markdown(":root{--cp-bg:#05050a;}")
    assert "<style>" in md
    assert "--cp-bg" in md
    assert "fonts.googleapis.com" in md
    assert "Orbitron" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_theme.py -v`

Expected: FAIL (module/functions not defined, or pytest missing — if pytest missing, `pip install pytest` first)

- [ ] **Step 3: Minimal implementation stubs + requirements**

`requirements.txt` — change first dependency line:

```
streamlit>=1.33.0
```

`app/styles/__init__.py` — empty file.

`app/styles/theme.py`:

```python
"""Cyberpunk theme loader for Streamlit."""

from pathlib import Path

CSS_PATH = Path(__file__).parent / "cyberpunk.css"

FONT_LINK = (
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Orbitron:wght@500;700&family=Share+Tech+Mono&display=swap" '
    'rel="stylesheet">'
)


def load_cyberpunk_css():
    # type: () -> str
    if not CSS_PATH.is_file():
        return ""
    return CSS_PATH.read_text(encoding="utf-8")


def build_theme_markdown(css):
    # type: (str) -> str
    return FONT_LINK + f"<style>{css}</style>"


def inject_cyberpunk_theme():
    # type: () -> None
    import streamlit as st
    import logging

    css = load_cyberpunk_css()
    if not css:
        logging.getLogger(__name__).warning("cyberpunk.css missing; theme skipped")
        return
    st.markdown(build_theme_markdown(css), unsafe_allow_html=True)
```

Create placeholder CSS so later tasks fill it (empty `:root{}` is enough for Task 1):

`app/styles/cyberpunk.css`:

```css
:root {
  --cp-bg: #05050a;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_theme.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt app/styles/__init__.py app/styles/theme.py app/styles/cyberpunk.css tests/test_theme.py
git commit -m "feat: add cyberpunk theme loader and bump streamlit for popover"
```

---

### Task 2: Full cyberpunk.css

**Files:**
- Modify: `app/styles/cyberpunk.css`

- [ ] **Step 1: Replace CSS with full theme**

Write the complete contents of `app/styles/cyberpunk.css`:

```css
:root {
  --cp-bg: #05050a;
  --cp-surface: #0c0c14;
  --cp-border: #1e1e2e;
  --cp-cyan: #00f0ff;
  --cp-magenta: #ff2d6a;
  --cp-amber: #ffb000;
  --cp-text: #e8e8f0;
  --cp-muted: #8a8a9a;
}

html, body, [data-testid="stAppViewContainer"] {
  background-color: var(--cp-bg) !important;
  color: var(--cp-text);
  font-family: "Share Tech Mono", ui-monospace, monospace;
}

[data-testid="stAppViewContainer"] {
  background-image:
    linear-gradient(rgba(0, 240, 255, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 240, 255, 0.03) 1px, transparent 1px);
  background-size: 48px 48px;
}

[data-testid="stHeader"] {
  background: transparent !important;
}

[data-testid="stSidebar"] {
  background-color: var(--cp-surface) !important;
  border-right: 1px solid var(--cp-cyan);
  box-shadow: 4px 0 24px rgba(0, 240, 255, 0.12);
}

[data-testid="stSidebar"] * {
  font-family: "Share Tech Mono", ui-monospace, monospace;
}

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
  font-family: "Orbitron", sans-serif !important;
  color: var(--cp-cyan) !important;
  text-shadow: 0 0 8px rgba(0, 240, 255, 0.45);
}

h1, h2, h3, [data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {
  font-family: "Orbitron", sans-serif !important;
  letter-spacing: 0.04em;
}

h1 {
  color: var(--cp-cyan) !important;
  text-shadow: 0 0 12px rgba(0, 240, 255, 0.35);
}

[data-testid="stMetric"] {
  background: var(--cp-surface);
  border: 1px solid var(--cp-cyan);
  border-radius: 4px;
  padding: 0.75rem 1rem;
  box-shadow: 0 0 12px rgba(0, 240, 255, 0.15), inset 0 0 20px rgba(0, 240, 255, 0.03);
}

[data-testid="stMetricLabel"] {
  color: var(--cp-muted) !important;
  font-family: "Share Tech Mono", ui-monospace, monospace !important;
}

[data-testid="stMetricValue"] {
  color: var(--cp-text) !important;
  font-family: "Orbitron", sans-serif !important;
}

div[data-testid="stButton"] > button[kind="primary"],
button[data-testid="baseButton-primary"] {
  background: var(--cp-magenta) !important;
  border: 1px solid var(--cp-magenta) !important;
  color: #fff !important;
  font-family: "Orbitron", sans-serif !important;
  box-shadow: 0 0 14px rgba(255, 45, 106, 0.45);
}

div[data-testid="stButton"] > button[kind="primary"]:hover,
button[data-testid="baseButton-primary"]:hover {
  box-shadow: 0 0 22px rgba(255, 45, 106, 0.75), 0 0 8px rgba(0, 240, 255, 0.35);
  border-color: var(--cp-cyan) !important;
}

div[data-testid="stButton"] > button,
button[data-testid="baseButton-secondary"] {
  border: 1px solid var(--cp-cyan) !important;
  color: var(--cp-cyan) !important;
  background: transparent !important;
  font-family: "Share Tech Mono", ui-monospace, monospace !important;
}

hr, [data-testid="stDecorator"] {
  border-color: transparent !important;
}

hr {
  height: 1px !important;
  background: linear-gradient(90deg, transparent, var(--cp-cyan), var(--cp-magenta), transparent) !important;
  border: none !important;
}

[data-testid="stDataFrame"],
[data-testid="stTable"] {
  border: 1px solid var(--cp-border);
  box-shadow: 0 0 10px rgba(0, 240, 255, 0.08);
}

[data-testid="stPopoverButton"] button,
button[kind="secondary"] {
  border: 1px solid var(--cp-cyan) !important;
  color: var(--cp-cyan) !important;
  background: rgba(0, 240, 255, 0.06) !important;
  font-family: "Orbitron", sans-serif !important;
  box-shadow: 0 0 10px rgba(0, 240, 255, 0.25);
}

textarea, [data-testid="stTextArea"] textarea,
[data-testid="stTextInput"] input,
[data-baseweb="select"] {
  background-color: var(--cp-surface) !important;
  color: var(--cp-text) !important;
  border-color: var(--cp-border) !important;
}

.stAlert {
  border-left: 3px solid var(--cp-cyan);
}
```

- [ ] **Step 2: Re-run theme unit tests**

Run: `python -m pytest tests/test_theme.py -v`

Expected: PASS (CSS file still present and loadable)

- [ ] **Step 3: Commit**

```bash
git add app/styles/cyberpunk.css
git commit -m "feat: add full cyberpunk Streamlit stylesheet"
```

---

### Task 3: Wire theme into main.py

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Inject theme after page config**

In `app/main.py`, immediately after `st.set_page_config(...)`, add:

```python
from app.styles.theme import inject_cyberpunk_theme

inject_cyberpunk_theme()
```

Update sidebar brand (drop emoji from title text if present; keep nav labels with emoji):

```python
st.sidebar.title("Portfolio Agent")
st.sidebar.caption("NEURAL LINK // INVESTMENT OS")
```

Keep `page_icon` in `set_page_config` as-is (or `"⚡"`). Keep the pages dict keys with emoji for scanability.

Full relevant block should look like:

```python
st.set_page_config(
    page_title="Portfolio Agent",
    page_icon="⚡",
    layout="wide",
)

from app.styles.theme import inject_cyberpunk_theme
inject_cyberpunk_theme()
```

(Import may sit with other imports at top if preferred — either is fine as long as inject runs after `set_page_config` and on every rerun.)

- [ ] **Step 2: Smoke-check import**

Run: `python -c "from app.styles.theme import inject_cyberpunk_theme, load_cyberpunk_css; assert load_cyberpunk_css()"`

Expected: no exception; assert passes

- [ ] **Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat: inject cyberpunk theme on Streamlit startup"
```

---

### Task 4: Collapsible Ask Agent on Dashboard

**Files:**
- Modify: `app/pages/dashboard.py`

- [ ] **Step 1: Replace layout with header popover + full-width holdings**

Replace the entire contents of `app/pages/dashboard.py` with:

```python
"""Main dashboard — KPI overview, holdings, recommendations, ask-agent."""

import streamlit as st
from app.components.kpi_cards import render_kpi_cards
from app.components.holdings_table import render_holdings_table
from app.components.recommendation_card import render_recommendations

hdr_l, hdr_r = st.columns([5, 1])
with hdr_l:
    st.title("Portfolio Dashboard")
    st.caption("AI-powered investment portfolio management // ONLINE")
with hdr_r:
    st.write("")  # vertical align popover with title
    with st.popover("Ask Agent"):
        user_question = st.text_area(
            "Question",
            placeholder="e.g., 现在该加仓什么？科技股风险大吗？",
            label_visibility="collapsed",
            key="ask_agent_question",
        )
        if st.button("Send to Agent", type="primary", key="ask_agent_send"):
            if user_question:
                with st.spinner("Agent is thinking..."):
                    from agent.core import run_ad_hoc_query
                    response = run_ad_hoc_query(user_question)
                    st.success("Agent response:")
                    st.write(response)
            else:
                st.warning("Please enter a question.")

render_kpi_cards()
st.divider()
render_holdings_table()
st.divider()
render_recommendations()
```

- [ ] **Step 2: Syntax check**

Run: `python -m py_compile app/pages/dashboard.py`

Expected: exit 0

- [ ] **Step 3: Commit**

```bash
git add app/pages/dashboard.py
git commit -m "feat: move Ask Agent into popover; full-width holdings"
```

---

### Task 5: Component polish (KPI + holdings headers)

**Files:**
- Modify: `app/components/holdings_table.py`
- Modify: `app/pages/holdings.py` (title only)
- Modify: `app/pages/history.py` (title only)

- [ ] **Step 1: Holdings table headers**

In `app/components/holdings_table.py`, change subheaders to:

```python
st.subheader("Core Holdings")
# ...
st.subheader("Satellite Holdings")
```

Keep the Type column emoji values (`🔵 Core` / `🟠 Satellite`) unchanged.

- [ ] **Step 2: Page titles**

In `app/pages/holdings.py`:

```python
st.title("Holdings Management")
```

In `app/pages/history.py`:

```python
st.title("Decision History")
```

Do not change form logic or history rendering.

- [ ] **Step 3: Commit**

```bash
git add app/components/holdings_table.py app/pages/holdings.py app/pages/history.py
git commit -m "style: cyberpunk page titles; keep holdings type emoji"
```

---

### Task 6: CLAUDE.md + manual verification

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

In Architecture section, note styles:

```
app/styles/ Cyberpunk theme CSS + inject_cyberpunk_theme()
```

Add Gotcha:

```
### Ask Agent is a popover

Dashboard Ask Agent uses `st.popover` (requires streamlit>=1.33). It does not sit in a right column — holdings are full width. Theme CSS is re-injected every Streamlit rerun from `app/main.py`.
```

Ensure Environment/Commands still accurate; `streamlit` floor is ≥1.33.0.

- [ ] **Step 2: Install + run app**

```bash
pip install -r requirements.txt
./run.sh
```

Manual checklist (http://localhost:8501):

1. Holdings tables span full main width with Ask Agent closed
2. Click Ask Agent → popover opens with textarea + Send
3. Empty send → warning; non-empty → spinner/response (API key required)
4. KPI cards have cyan neon borders; background grid visible
5. Sidebar shows cyan accent; Holdings + History pages inherit theme

- [ ] **Step 3: Python 3.9 syntax guard**

Run: `grep -rn "->.*| None" --include="*.py" app/styles app/pages app/main.py || true`

Expected: no matches in new/changed files

- [ ] **Step 4: Final commit**

```bash
git add CLAUDE.md
git commit -m "docs: note cyberpunk theme and Ask Agent popover"
```

---

## Spec Coverage Checklist

| Spec requirement | Task |
|---|---|
| `st.popover` Ask Agent | Task 4 |
| Full-width holdings | Task 4 |
| `cyberpunk.css` tokens + visual rules | Task 2 |
| `theme.py` inject + missing CSS warning | Task 1, 3 |
| Inject from `main.py` | Task 3 |
| Fonts Orbitron / Share Tech Mono | Task 1–2 |
| `streamlit>=1.33.0` | Task 1 |
| KPI/sidebar/button neon styling | Task 2 |
| Page title polish | Task 4–5 |
| Keep Core/Satellite emoji | Task 5 |
| CLAUDE.md update | Task 6 |
| Manual test checklist | Task 6 |
| No agent/DB changes | All tasks (verified by file list) |
