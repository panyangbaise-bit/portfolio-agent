# Portfolio Agent

[中文文档](README_CN.md)

An AI portfolio OS for **US / China A-share / Hong Kong / crypto** holdings. A light terminal-style Streamlit dashboard (IBM Plex Mono, black rules on white), a DeepSeek thinking-mode agent (LangGraph + tools), live market adapters, scheduled analysis, and optional Telegram alerts.

Open locally at [http://localhost:8501](http://localhost:8501) after `./run.sh`.

New reports include numbered source citations such as `[1]`: hover for the retrieved title and summary, and click to open the source. Repeated sources reuse their number, and links survive report history and Telegram delivery. Citations use retrieved news and web results; older reports are not retroactively annotated.

## Screenshots

Captured from the running app (`http://127.0.0.1:8501`, English UI).

### Dashboard

CNY-normalized total value and P&L, pending recommendations, risk level, then **core** vs **satellite** holdings with live prices. The black square in the corner is **Ask Agent**.

![Portfolio Dashboard](docs/screenshots/dashboard.png)

### Ask Agent

Global floating chat on every page. Ask about allocation, risk, or what to adjust. Multi-turn follow-ups share one session until **New chat**. Drag the **top-left** handle to resize; the composer grows with the panel.

![Ask Agent](docs/screenshots/ask-agent.png)

### Holdings

Add positions by ticker and market, then **Edit / Delete**, **Buy / Sell** (weighted-average buys, broker-style residual cost on sells), and a full transaction ledger. Closed positions stay in history.

![Holdings](docs/screenshots/holdings.png)

### Watchlist

Track names before you enter. Cards keep a reason and optional target range; edit the reason or delete when you are done.

![Watchlist](docs/screenshots/watchlist.png)

### Recommendations

Pending agent suggestions with confidence, urgency, and reasoning. **Accept** or **Dismiss** here (not in Telegram). Empty state means the agent is monitoring and not spamming routine holds.

![Recommendations](docs/screenshots/recommendations.png)

### Operations

Opens on **Analysis reports**: full reports, recommendations, and tool calls. **Schedules** lists the six recurring jobs and manual runs; **Run history** filters outcomes and opens a row's saved output. Monthly summaries and the news crontab stay collapsed until needed. Times use `APP_TIMEZONE` (default Beijing).

![Operations](docs/screenshots/operations.jpg)

### History

Audit trail of recommendations and your actions — ticker, action, confidence, urgency, status, timestamp, and the saved rationale.

![Decision History](docs/screenshots/history.png)

### Telegram

Optional send-only pushes when analysis finishes (plain text; Accept/Dismiss stay on the dashboard so this process never fights another bot for `getUpdates`).

![Telegram notification](docs/screenshots/telegram.png)

## Features

- **Multi-market book** — US, CN (stocks + OTC funds/ETFs), HK, crypto; core vs satellite
- **CNY portfolio totals** — FX-normalized market value and weights (native $ / HK$ / ¥ kept on cost and last price)
- **DeepSeek thinking agent** — `deepseek-v4-pro`, thinking mode, `reasoning_effort=max`, LangGraph tool loop
- **Ask Agent** — floating multi-turn chat, streaming replies, analysis report per conversation in Operations
- **Live prices with fallbacks** — cache first, background refresh; adapters degrade instead of taking the job down
- **Scheduled analysis** — after-market by venue, WallStreetCN news poll (holdings + headlines), monthly trade review
- **Brave web search** — optional. The agent calls it only when WallStreetCN returns nothing relevant (`BRAVE_SEARCH_API_KEY`)
- **Decision log** — sessions, tool calls, recommendations, and user actions in SQLite
- **Bilingual UI** — **EN / CN** toggle in the top-right banner
- **Optional Telegram** — startup welcome + analysis summaries
- **Public gate** — `AUTH_ENABLED` + password; IPs blacklist after repeated failures

## Pages

| Nav | What you do |
|---|---|
| **Dashboard** | Snapshot KPIs and holdings tables; open Ask Agent |
| **Holdings** | Add / edit / trade / transaction history |
| **Watchlist** | Pre-entry tickers, reason, target range |
| **Recommendations** | Accept or dismiss pending suggestions |
| **Operations** | Analysis reports by default; schedules, Run Now, and run history |
| **History** | Past recommendations and outcomes |

## Deploy on Ubuntu

One-shot install (venv + systemd):

```bash
sudo apt update && sudo apt install -y git
sudo git clone https://github.com/panyangbaise-bit/portfolio-agent.git /opt/portfolio-agent
cd /opt/portfolio-agent
sudo ./deploy/setup-server.sh
sudo nano /opt/portfolio-agent/.env   # DEEPSEEK_API_KEY + AUTH_PASSWORD
sudo systemctl restart portfolio-agent
```

Then open `http://YOUR_SERVER_IP:8501`. Logs: `journalctl -u portfolio-agent -f`.

## How to use

1. **Install & configure (local)**
   ```bash
   pip install -r requirements.txt
   cp .env.example .env
   # Required: DEEPSEEK_API_KEY
   # Optional: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, APP_TIMEZONE=Asia/Shanghai, BRAVE_SEARCH_API_KEY
   ```

2. **Start**
   ```bash
   ./run.sh
   ```
   Open http://localhost:8501.

3. **Add holdings** — **Holdings → Add Position** (US / CN / HK / Crypto, core or satellite). Use **Buy / Sell** for later fills so the ledger stays consistent.

4. **Watch before entry** — **Watchlist** for names you care about but do not hold yet.

5. **Monitor** — **Dashboard** for CNY totals, P&L, and risk. **Ask Agent** (corner button) for ad-hoc questions.

6. **Review suggestions** — **Recommendations** to Accept / Dismiss. Full trail under **History**.

7. **Run analysis** — **Operations** opens on **Analysis reports**. **Schedules** has next-run times and **Run Now**. Output also lands in run history, and in Telegram when configured. News is searched on WallStreetCN first; Brave web search fills a gap only when that search has nothing relevant.

## Configuration

| Variable | Required | Default |
|---|---|---|
| `DEEPSEEK_API_KEY` | **Yes** | — |
| `DEEPSEEK_BASE_URL` | No | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | No | `deepseek-v4-pro` |
| `DEEPSEEK_MAX_TOKENS` | No | `65536` |
| `DEEPSEEK_REASONING_EFFORT` | No | `max` |
| `DEEPSEEK_THINKING` | No | `true` |
| `APP_TIMEZONE` | No | `Asia/Shanghai` |
| `NEWS_CRONTAB` | No | `0 8-22/2 * * *` (also editable in Operations) |
| `BRAVE_SEARCH_API_KEY` | No | web search off; used only when WallStreetCN news has no relevant hit |
| `AUTH_ENABLED` | No | `false` |
| `AUTH_PASSWORD` | If auth on | — |
| `AUTH_MAX_FAILURES` | No | `3` |
| `TELEGRAM_BOT_TOKEN` | No | notifications off |
| `TELEGRAM_CHAT_ID` | No | notifications off |
| `LANGSMITH_API_KEY` | No | tracing off |

Before a public deploy, set `AUTH_ENABLED=true` and a strong `AUTH_PASSWORD`. After `AUTH_MAX_FAILURES` wrong attempts the client IP is written to `data/ip_blacklist.json`.

## Tech stack

| Layer | Technology |
|---|---|
| UI | Streamlit 1.33+ |
| Agent | LangGraph + LangChain tools |
| LLM | `DeepSeekChatOpenAI` → `deepseek-v4-pro` (thinking mode) |
| Market data | yfinance, akshare, CoinGecko, WallStreetCN; Brave web search optional |
| Persistence | SQLite + SQLAlchemy 2.0 |
| Scheduler | APScheduler |
| Notifications | Telegram Bot (send-only, optional) |
| Runtime | Python 3.9+ |

## Validation

```bash
PYTHONPATH=. python3 -m pytest tests -v
```

## Project structure

```text
portfolio-agent/
├── adapters/           # Market data, WallStreetCN news, optional Brave search
├── agent/              # LangGraph graph, prompts, tools, DeepSeek client
├── app/                # Streamlit UI, i18n, theme
├── db/                 # Models, repository, migrations
├── scheduler/          # Cron jobs and manual triggers
├── notifier/           # Telegram
├── docs/screenshots/   # README product shots
├── tests/
└── .streamlit/         # toolbarMode=minimal
```

## Design documents

- [Original design](docs/superpowers/specs/2026-07-18-portfolio-agent-design.md)

### Investment memory

Search historical recommendations, dismissal reasons, analysis reports, trades, conversations and trading rules from the **Memory** page or agent tools. SQLite full-text search works out of the box; optional Qdrant + an external embedding API adds semantic retrieval without loading a model on the server. [Setup, resource limits and historical-time behavior](docs/memory.md).
