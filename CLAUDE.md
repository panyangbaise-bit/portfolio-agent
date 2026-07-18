# Portfolio Agent — CLAUDE.md

AI-powered personal portfolio management agent. Multi-market (US/CN/HK/Crypto), autonomous reasoning via LangGraph + DeepSeek, Streamlit dashboard.

## Commands

```bash
# Install
pip install -r requirements.txt

# Run (requires .env with DEEPSEEK_API_KEY)
./run.sh                       # → http://localhost:8501

# Push to GitHub
git push origin main
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
agent/        LangGraph ReAct loop, system prompt, 10 tools, session tracking
app/          Streamlit dashboard (main.py + components/ + pages/)
app/styles/   Cyberpunk theme CSS + inject_cyberpunk_theme()
db/           SQLAlchemy 2.0 models (9 tables) + repository + migration system
scheduler/    APScheduler — 4 after-market jobs + hourly news poll
notifier/     Telegram Bot
config.py     Central config from env vars
```

**Data flow:** Adapter → Tool → LangGraph Agent (DeepSeek) → Recommendation → DB → Dashboard

**Key design:** Agent calls tools autonomously. Tools wrap adapters. Adapters normalize data across markets. All agent decisions (trigger → tool calls → recommendation → user action) are in DB.

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

### Price fetching is cached

`app/components/price_fetcher.py` uses `@st.cache_data(ttl=60)`. Dashboard shows cached prices for 60s before re-fetching. Adapter failures return `None` — UI shows `—`.

### CoinGecko timeout

Crypto adapter sets `cg.session.timeout = 10` to fail fast on DNS issues. Without this, it retries for 30+ seconds and blocks the dashboard.

### Ask Agent is a popover

Dashboard Ask Agent uses `st.popover` (requires streamlit>=1.33). It does not sit in a right column — holdings are full width. Theme CSS is re-injected every Streamlit rerun from `app/main.py` via `inject_cyberpunk_theme()`.

## Maintenance Rule

**After any major change** (new feature, schema change, adapter added, behavior modified), update this CLAUDE.md to reflect the new state. At minimum check:
- Commands still work
- Architecture section is accurate
- Gotchas include any new quirks discovered during implementation
- Environment variables are up to date
