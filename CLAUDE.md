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

# Manual job trigger test (triggers all 6 scheduled jobs via threading)
PYTHONPATH=. python3 tests/test_manual_trigger_all_jobs.py

# One-shot deploy on Ubuntu (venv + systemd)
# sudo ./deploy/setup-server.sh
```

## Environment

Copy `.env.example` to `.env`:

| Variable | Required | Default |
|---|---|---|
| `DEEPSEEK_API_KEY` | **Yes** | — |
| `DEEPSEEK_BASE_URL` | No | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | No | `deepseek-v4-pro` |
| `DEEPSEEK_MAX_TOKENS` | No | `65536` |
| `DEEPSEEK_REASONING_EFFORT` | No | `max` (`high` / `max`) |
| `DEEPSEEK_THINKING` | No | `true` (thinking mode) |
| `APP_TIMEZONE` | No | `Asia/Shanghai` (Beijing; UI display) |
| `AUTH_ENABLED` | No | `false` (set `true` before public deploy) |
| `AUTH_PASSWORD` | If auth on | — (server-side only) |
| `AUTH_MAX_FAILURES` | No | `3` then IP blacklisted |
| `TELEGRAM_BOT_TOKEN` | No | — (notifications disabled) |
| `TELEGRAM_CHAT_ID` | No | — |

## Architecture

```
adapters/     Market data adapters (MarketAdapter ABC → yfinance/akshare/CoinGecko/WallStreetCN)
agent/        LangGraph ReAct loop, system prompt, LangChain tools, session tracking
app/          Streamlit dashboard (main.py + components/ + views/)
app/i18n.py   English / Chinese UI strings, selected through top-banner EN/CN toggle
app/styles/   Cyberpunk theme CSS + inject_cyberpunk_theme() / inject_locale_toggle()
app/views/    Page bodies loaded by sidebar radio (must NOT be named pages/ — Streamlit auto-tabs). Nav: Dashboard → Holdings → Recommendations → Jobs → History
deploy/       One-shot Ubuntu server install (`setup-server.sh` + systemd unit)
db/           SQLAlchemy 2.0 models (10 tables) + repository + additive migration system
scheduler/    APScheduler — 4 after-market jobs + hourly news poll + monthly trade review
notifier/     Telegram Bot
config.py     Central config from env vars
tests/        pytest coverage for theme, i18n, price fallback, job-run persistence, trades, and agent session detail
```

**Agent flow:** Market adapter → LangChain tool → LangGraph agent → recommendation/session → SQLite → Dashboard.

**Key design:** `agent/graph.py` binds `agent.tools.ALL_TOOLS` to `agent.llm.DeepSeekChatOpenAI` (DeepSeek `deepseek-v4-pro` with thinking mode + `reasoning_effort=max`). The wrapper preserves `reasoning_content` across tool-call rounds (required by DeepSeek thinking mode). Every new agent turn appends a trailing `## 当前时间` block via `format_now_for_agent()` (`APP_TIMEZONE`). All agent decisions (trigger → tool calls → recommendation → user action) are in DB.

### DeepSeek thinking mode

Thinking is enabled via `extra_body={"thinking": {"type": "enabled"}}` and `reasoning_effort` ([docs](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode)). Temperature is ignored in thinking mode. Tool rounds must echo `reasoning_content` — handled in `agent/llm.py`.

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

### CN fund / ETF detail (`get_fund_info`)

Agent tool `get_fund_info` (CN only) returns overview via `fund_overview_em` (tracked index, fees, company), asset mix via `fund_individual_detail_hold_xq`, and approximate constituents from the tracked CSI index (`index_stock_cons_csindex`) after name→code resolution in `adapters/cn_index_map.py`. ETF联接 (e.g. `020357`) are tagged `fund_kind=etf_feeder`; constituents are index proxies, not季报持股明细. Extend the map when a new tracked index cannot be resolved.

### Price snapshots and live fetching

`app/components/price_fetcher.py` uses `@st.cache_data(ttl=60)`. Dashboard first renders `price_cache`; missing values are persisted from cost basis, so Price / P&L / Mkt Value survive restart and are never blank. A 1-second fragment refreshes holdings concurrently with a 2-second deadline; successful live values replace that day's fallback snapshot.

### CoinGecko timeout

Crypto adapter sets `cg.session.timeout = 10`. The dashboard-wide concurrent fetch deadline is 2 seconds, so a slow provider cannot block the first visible portfolio snapshot.

### Agent sessions store job metadata

`agent_sessions` has `job_id`, `market`, and `summary` (via migrations `v2*`). **Jobs** page shows **Job Runtime Log** via `list_job_runs()`, plus **Agent Session Detail** (summary, recommendation `reasoning`, tool-call timeline) via `list_analysis_runs()` / `get_agent_session_detail()`. Tool calls are persisted by the logging `tools` node in `agent/graph.py` into `agent_tool_calls` (full params/results, 100k-char safety cap). Older `agent_sessions` rows may have null `job_id`/`market` or empty tool logs until new runs complete.

### Recommendation noise reduction

Jobs are **not** required to emit clickable recommendations every run. Prompt asks the agent to call `get_recommendation_history` first and default to text-only analysis. `save_recommendation` enforces: skip routine `hold`+`low`; skip if same ticker already has pending same `action`, or a same `action`+`urgency` within 7 days (`find_similar_recommendation`). Skips return `skipped_routine` / `skipped_unchanged` without creating rows.

### Scheduler outcomes are persisted

`job_runs` records every actual scheduler invocation as `completed`, `skipped`, or `failed`. This distinguishes an empty news poll or no-holdings skip from a job that has not reached its cron time. Cron jobs permit a five-minute startup/restart misfire grace period.

### Localization

Use `app.i18n.t()` for user-visible UI strings and `enum_label()` for persisted enums (actions, markets, statuses). `st.session_state["locale"]` is `en` or `zh` (toggled by the top-banner EN/CN button); agent-generated reasoning and user-entered names are not translated. Sidebar nav keys are stable (`dashboard`/`holdings`/`recommendations`/`jobs`/`history`) so switching language does not reset the current page.

### Ask Agent is a popover

Dashboard Ask Agent uses `st.popover` (requires streamlit>=1.33). It does not sit in a right column — holdings are full width. Theme CSS is re-injected every Streamlit rerun from `app/main.py` via `inject_cyberpunk_theme()`.

### Do not name view folder `pages/`

Streamlit auto-discovers `pages/` next to the entry script and shows top/sidebar multipage tabs (`main`, `dashboard`, …). Custom navigation already lives in the sidebar radio — keep view modules under `app/views/`.

### Theme CSS injection

Do **not** inject theme CSS with `st.markdown` (strips `<style>`) or bare `st.html` (reserves a huge empty layout slot). Use `inject_cyberpunk_theme()` in `app/styles/theme.py`: a height-0 `components.html` iframe writes a `<style>` tag into `window.parent.document.head` and hides its own host node.

### Manual job triggers

**Jobs** page **Scheduled Jobs** table has a last-column "▶ Run Now" button per row that calls `scheduler.cron.trigger_job(job_id)`. Each job runs in a `threading.Thread` daemon thread. Status is tracked in `_manual_runs` dict — the Streamlit UI polls this to show running/completed/failed state. `clear_manual_run_status()` resets the button after the user acknowledges the result. Below the runtime log, **Agent Session Detail** lets you filter by job and inspect each session's summary, recommendation reasoning, and tool calls.

### Localization toggle

Language is toggled by a fixed **EN** / **CN** button in the top-right banner (`inject_locale_toggle` in `app/styles/theme.py`). Clicking sets `?locale=en|zh` and reloads; `app/main.py` syncs that into `st.session_state["locale"]`.

### Hide Streamlit Deploy / settings menu

[`.streamlit/config.toml`](.streamlit/config.toml) sets `client.toolbarMode = "minimal"`. Theme CSS also force-hides Deploy and the ⋮ main menu so they stay gone on localhost. Restart Streamlit after changing `config.toml`.

### Display timezone

DB timestamps are UTC. UI/logs convert via `app.timeutil.format_display_time()` using `APP_TIMEZONE` (default `Asia/Shanghai` / Beijing). This fixes the apparent −8h offset when viewing job run times in China. Agent prompts also receive wall-clock via `format_now_for_agent()` appended at the end of the system message.

### Holdings buy/sell ledger

Holdings page **Buy / Sell** panel calls `apply_trade()`: buys use weighted-average cost; sells use broker-style residual cost `(shares×cost − sell_shares×sell_price) / remaining` (selling at a loss raises remaining cost — matches common CN/HK brokers). Full exit sets `shares=0` and `status=closed` (row kept so transaction history survives). Dashboard / `get_portfolio` / news poll use `get_open_holdings()` only. Accepting a recommendation does **not** auto-apply a trade.

### Hourly news poll

`hourly_news` fetches **ticker news + WallStreetCN headlines/latest**, then asks the agent to assess both holding-specific and macro/headline impact on the portfolio (`poll_news_for_portfolio` in `agent/core.py`).

### Monthly trade review

`monthly_trade_review` runs on the 1st at 21:00 Asia/Shanghai. It loads recent `transactions` and asks the agent to review timing/discipline (`run_trade_review_analysis`). No trades in the window → `job_runs` status `skipped` (no LLM call).

### Telegram chat ID discovery

`notifier/telegram.py` has `discover_chat_id()` which calls `getUpdates` to find the most recent chat ID. This requires Telegram API to be reachable (blocked from mainland China without a proxy). Fallback: set `TELEGRAM_CHAT_ID` manually in `.env`.

### Telegram welcome is process-once

`send_welcome()` must NOT key off `st.session_state` — Streamlit page refresh clears session state and would spam Telegram. Bootstrap uses a process-level lock in `app/main.py` plus `_welcome_sent` in `notifier/telegram.py`, so the “已启动” message fires only when the server process first starts.

### Public password gate

Before exposing the app on the public internet, set `AUTH_ENABLED=true` and `AUTH_PASSWORD=...` in `.env`. `app.auth.require_auth()` runs in `app/main.py` before any page UI. Wrong password increments a per-IP counter; at `AUTH_MAX_FAILURES` (default 3) the IP is written to `data/ip_blacklist.json` (gitignored) and blocked immediately. Unban by removing the IP from that file and restarting if needed.

### Server deploy

On Ubuntu, use `sudo ./deploy/setup-server.sh` from a git checkout (or let it clone into `/opt/portfolio-agent`). The script installs a venv, writes a systemd unit from `deploy/portfolio-agent.service`, and starts `portfolio-agent` on port `8501`. Edit `.env` after first install, then `systemctl restart portfolio-agent`.

## Maintenance Rule

**After any major change** (new feature, schema change, adapter added, behavior modified), update this CLAUDE.md to reflect the new state. At minimum check:
- Commands still work
- Architecture section is accurate
- Gotchas include any new quirks discovered during implementation
- Environment variables are up to date
