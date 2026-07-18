# Cyberpunk UI + Collapsible Ask Agent — Design Spec

**Date:** 2026-07-18  
**Status:** Approved (conversation) — pending user review of this written spec  
**Scope:** Streamlit dashboard visual redesign + Ask Agent layout change only

## Goal

1. Make Ask Agent collapsible so it does not permanently consume main-layout width.
2. Restyle the Streamlit app with a cohesive cyberpunk aesthetic across all pages.

## Non-Goals

- No framework migration (stay on Streamlit)
- No floating FAB / custom HTML drawer overlay
- No chat history persistence or multi-turn conversation UI
- No changes to agent logic, adapters, DB schema, or scheduler

## Decisions

| Topic | Decision |
|---|---|
| Ask Agent UX | `st.popover` on Dashboard title row |
| Theme delivery | Global CSS injected once from `app/main.py` |
| Visual direction | Dark cyberpunk: near-black + neon cyan + magenta |
| Typography | Orbitron (display) + Share Tech Mono (body) via Google Fonts |
| Streamlit version | Bump to `streamlit>=1.33.0` (required for `st.popover`) |

## Ask Agent Interaction

### Current (remove)

Dashboard uses `st.columns([3, 2])`: holdings left, Ask Agent right. Chat permanently takes ~40% width.

### Target

```
[ Portfolio Dashboard          ]  [ Ask Agent ▾ ]  ← popover trigger
[ KPI row — full width                          ]
[ Core Holdings — full width                    ]
[ Satellite Holdings — full width               ]
[ Recommendations                               ]
```

- Trigger label: `Ask Agent` (neon-styled via CSS targeting the popover button)
- Popover contents (unchanged behavior):
  - `st.text_area` with Chinese placeholder
  - Primary `Send to Agent` button
  - Spinner → `run_ad_hoc_query` → show response / warning if empty
- Default state: closed — zero horizontal layout cost
- Holdings render at full container width

### Placement detail

Use a two-column header on Dashboard:

```python
hdr_l, hdr_r = st.columns([5, 1])
with hdr_l:
    st.title(...)
    st.caption(...)
with hdr_r:
    with st.popover("Ask Agent"):
        # chat UI
```

Exact column ratios may be tuned for readability; intent is title left, compact trigger right.

## Cyberpunk Theme

### Files

| File | Role |
|---|---|
| `app/styles/cyberpunk.css` | Theme stylesheet |
| `app/styles/theme.py` | `inject_cyberpunk_theme()` — read CSS + font link, inject via `st.markdown` |
| `app/main.py` | Call `inject_cyberpunk_theme()` after `st.set_page_config` |
| `app/pages/dashboard.py` | Popover layout + title tweaks |
| `app/components/kpi_cards.py` | Optional class wrappers / label polish (no logic change) |
| `app/components/holdings_table.py` | Optional header polish (no logic change) |
| `requirements.txt` | `streamlit>=1.33.0` |
| `CLAUDE.md` | Note UI theme + Ask Agent popover |

### Color tokens

```css
--cp-bg: #05050a;
--cp-surface: #0c0c14;
--cp-border: #1e1e2e;
--cp-cyan: #00f0ff;
--cp-magenta: #ff2d6a;
--cp-amber: #ffb000;
--cp-text: #e8e8f0;
--cp-muted: #8a8a9a;
```

### Visual rules

- App background: near-black with subtle CSS grid (repeating linear gradients)
- Sidebar: darker surface, cyan left accent / neon nav highlight on active feel via radio styling
- Primary buttons: magenta background, cyan/magenta glow on hover
- Metrics (KPI): surface cards with 1px cyan border + soft box-shadow glow
- Dataframes: dark surface, cyan header accents where Streamlit theming allows
- Dividers: thin cyan/magenta gradient lines instead of flat grey
- Keep emoji in holdings type labels (Core/Satellite) and sidebar nav for scanability; page titles may drop emoji in favor of Orbitron text

### Fonts

```html
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
```

- Titles / sidebar brand: Orbitron
- Body / captions / tables: Share Tech Mono (or Streamlit body with Mono on metrics)

Offline fallback: system monospace if Google Fonts unavailable.

### Injection pattern

```python
def inject_cyberpunk_theme():
    css_path = Path(__file__).parent / "styles" / "cyberpunk.css"
    css = css_path.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    # fonts link similarly
```

Inject on every run of `main.py` (Streamlit reruns clear custom HTML; re-inject is required).

## Page Impact

| Page | Change |
|---|---|
| Dashboard | Layout + theme |
| Holdings | Theme only (forms/buttons inherit) |
| History | Theme only |
| Sidebar | Brand caption + theme |

## Error Handling

- Empty Ask Agent question: keep existing `st.warning`
- Agent failure: surface existing exception behavior (no new error UX in this work)
- Missing CSS file: log and skip inject (app remains usable)

## Testing

Manual checklist after `./run.sh`:

1. Dashboard holdings use full width when Ask Agent closed
2. Popover opens, send question, response appears inside popover
3. KPI / tables / sidebar show neon borders and dark cyberpunk palette
4. Holdings and History pages inherit the same theme
5. No Python 3.9 `X | None` regressions introduced

## Implementation Notes

- Prefer targeting Streamlit structural classes carefully; keep selectors resilient (`[data-testid="stMetric"]`, etc.)
- Do not delete `portfolio.db` or touch migrations
- After implementation, update `CLAUDE.md` Gotchas/Architecture for theme + popover
