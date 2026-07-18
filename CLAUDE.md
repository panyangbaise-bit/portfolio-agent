# Portfolio Agent — CLAUDE.md

AI-powered personal portfolio management agent for US/CN/HK/Crypto holdings. The Streamlit dashboard uses a LangGraph ReAct loop, LangChain tools, and DeepSeek through the OpenAI-compatible `ChatOpenAI` client.

## Commands

```bash
# Install
pip install -r requirements.txt

# Run (requires .env with DEEPSEEK_API_KEY)
./run.sh                       # → http://localhost:8501

# Test
PYTHONPATH=. python3 -m pytest tests -v

# Manual job trigger test (triggers all 5 scheduled jobs via threading)
PYTHONPATH=. python3 tests/test_manual_trigger_all_jobs.py
```

## Environment

Copy `.env.example` to `.env`:

| Variable | Required | Default |
|---|---|---|
| `DEEPSEEK_API_KEY` | **Yes** | — |
| `DEEPSEEK_BASE_URL` | No | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | No | `deepseek-chat` |
| `TELEGRAM_BOT_TOKEN` | No | — (notifications disabled) |
| `TELEGRAM_CHAT_ID` | No | — |

## Architecture

```
adapters/     Market data adapters (MarketAdapter ABC → yfinance/akshare/CoinGecko/WallStreetCN)
agent/        LangGraph ReAct loop, system prompt, LangChain tools, session tracking
app/          Streamlit dashboard (main.py + components/ + views/)
app/i18n.py   English / Chinese UI strings, selected through sidebar locale control
app/styles/   Cyberpunk theme CSS + inject_cyberpunk_theme()
app/views/    Page bodies loaded by sidebar radio (must NOT be named pages/ — Streamlit auto-tabs)
db/           SQLAlchemy 2.0 models (10 tables) + repository + additive migration system
scheduler/    APScheduler — 4 after-market jobs + hourly news poll
notifier/     Telegram Bot
config.py     Central config from env vars
tests/        pytest coverage for theme, i18n, price fallback, and job-run persistence
```

**Agent flow:** Market adapter → LangChain tool → LangGraph agent → recommendation/session → SQLite → Dashboard.

**Key design:** `agent/graph.py` binds `agent.tools.ALL_TOOLS` to `langchain_openai.ChatOpenAI`, configured with `DEEPSEEK_BASE_URL` and `DEEPSEEK_MODEL`. All agent decisions (trigger → tool calls → recommendation → user action) are in DB.

## Gotchas

### Python 3.9 — no `X | None` syntax

Use `Optional[X]` from `typing`, never `X | None`. Check before commit:
```bash
grep -rn "->.*| None" --include="*.py" .
```

### Database — never delete portfolio.db

Schema changes go through `db/migrate.py` (ALTER TABLE), not table drops. `rm portfolio.db` destroys user data. The migration runner fires automatically at startup in `app/main.py`.

### HK ticker format → yfinance

HK data now uses **yfinance** (akshare East Money API is unreliable). Ticker conversion: `02026.HK` → strip `.HK` → strip leading zeros → `2026.HK` (yfinance format). See `HKMarketAdapter._to_yf_ticker()`.

### CN fund detection

6-digit codes starting with `0` route to `ak.fund_open_fund_info_em` (NAV-based). Stock codes (6/0/3 prefix) try `stock_zh_a_spot_em` first. See `CNMarketAdapter._is_fund()`.

### Price snapshots and live fetching

`app/components/price_fetcher.py` uses `@st.cache_data(ttl=60)`. Dashboard first renders `price_cache`; missing values are persisted from cost basis, so Price / P&L / Mkt Value survive restart and are never blank. A 1-second fragment refreshes holdings concurrently with a 2-second deadline; successful live values replace that day's fallback snapshot.

### CoinGecko timeout

Crypto adapter sets `cg.session.timeout = 10`. The dashboard-wide concurrent fetch deadline is 2 seconds, so a slow provider cannot block the first visible portfolio snapshot.

### Agent sessions store job metadata

`agent_sessions` has `job_id`, `market`, and `summary` (via migrations `v2*`). Dashboard **Job Analysis History** reads these via `list_analysis_runs()`. Older rows may have null `job_id`/`market` until new runs complete.

### Scheduler outcomes are persisted

`job_runs` records every actual scheduler invocation as `completed`, `skipped`, or `failed`. This distinguishes an empty news poll or no-holdings skip from a job that has not reached its cron time. Cron jobs permit a five-minute startup/restart misfire grace period.

### Localization

Use `app.i18n.t()` for user-visible UI strings and `enum_label()` for persisted enums (actions, markets, statuses). `st.session_state["locale"]` is `en` or `zh`; agent-generated reasoning and user-entered names are not translated.

### Ask Agent is a popover

Dashboard Ask Agent uses `st.popover` (requires streamlit>=1.33). It does not sit in a right column — holdings are full width. Theme CSS is re-injected every Streamlit rerun from `app/main.py` via `inject_cyberpunk_theme()`.

### Do not name view folder `pages/`

Streamlit auto-discovers `pages/` next to the entry script and shows top/sidebar multipage tabs (`main`, `dashboard`, …). Custom navigation already lives in the sidebar radio — keep view modules under `app/views/`.

### Theme CSS injection

Do **not** inject theme CSS with `st.markdown` (strips `<style>`) or bare `st.html` (reserves a huge empty layout slot). Use `inject_cyberpunk_theme()` in `app/styles/theme.py`: a height-0 `components.html` iframe writes a `<style>` tag into `window.parent.document.head` and hides its own host node.

### Manual job triggers

Dashboard **Scheduled Jobs** table has "▶ Run Now" buttons that call `scheduler.cron.trigger_job(job_id)`. Each job runs in a `threading.Thread` daemon thread. Status is tracked in `_manual_runs` dict — the Streamlit UI polls this to show running/completed/failed state. `clear_manual_run_status()` resets the button after the user acknowledges the result.

### Telegram chat ID discovery

`notifier/telegram.py` has `discover_chat_id()` which calls `getUpdates` to find the most recent chat ID. This requires Telegram API to be reachable (blocked from mainland China without a proxy). Fallback: set `TELEGRAM_CHAT_ID` manually in `.env`.

## Maintenance Rule

**After any major change** (new feature, schema change, adapter added, behavior modified), update this CLAUDE.md to reflect the new state. At minimum check:
- Commands still work
- Architecture section is accurate
- Gotchas include any new quirks discovered during implementation
- Environment variables are up to date
