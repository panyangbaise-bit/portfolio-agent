# Portfolio Agent

[中文文档](README_CN.md)

AI-powered personal portfolio management for US, China A-share, Hong Kong, and crypto holdings. It combines a Streamlit dashboard, a LangGraph tool-calling agent, live market adapters, scheduled analysis, and a durable decision audit trail.

## Features

- **Multi-market holdings** — US / CN / HK / crypto positions with core-satellite allocation
- **AI analysis** — LangGraph ReAct loop uses DeepSeek through LangChain's OpenAI-compatible `ChatOpenAI` client
- **Live-price resilience** — Dashboard renders saved price snapshots immediately, then refreshes live prices without blocking the page
- **Scheduled analysis** — Four after-market jobs plus hourly news polling, with persisted `completed` / `skipped` / `failed` run logs
- **Decision audit trail** — Agent sessions, tool calls, recommendations, and user actions are retained in SQLite
- **Bilingual UI** — Switch between English and Chinese from the sidebar

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Streamlit 1.33+ |
| Agent orchestration | LangGraph + LangChain |
| LLM client | `langchain-openai` `ChatOpenAI` → DeepSeek OpenAI-compatible API |
| Market data | yfinance, akshare, pycoingecko, WallStreetCN |
| Persistence | SQLite + SQLAlchemy 2.0 |
| Scheduler | APScheduler |
| Notifications | Telegram Bot (optional) |
| Runtime | Python 3.9+ |

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env
# Set DEEPSEEK_API_KEY in .env
./run.sh
```

Open http://localhost:8501.

## Configuration

| Variable | Required | Default |
|---|---:|---|
| `DEEPSEEK_API_KEY` | Yes | — |
| `DEEPSEEK_BASE_URL` | No | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | No | `deepseek-chat` |
| `TELEGRAM_BOT_TOKEN` | No | notifications disabled |
| `TELEGRAM_CHAT_ID` | No | notifications disabled |

## Validation

```bash
PYTHONPATH=. python3 -m pytest tests -v
```

## Project Structure

```text
portfolio-agent/
├── adapters/       # Normalized US / CN / HK / crypto / news data adapters
├── agent/          # LangGraph graph, prompts, tools, and session management
├── app/            # Streamlit entry point, views, components, i18n, and styles
├── db/             # SQLAlchemy models, repository, and additive migrations
├── scheduler/      # APScheduler registration and job implementations
├── notifier/       # Optional Telegram notifications
├── tests/          # Theme, pricing, i18n, and scheduler-run tests
└── docs/           # Design specs and implementation plans
```

## Data Flow

```text
Market adapter → LangChain tool → LangGraph agent → recommendation/session
                                              ↓
                    SQLite ← dashboard price snapshots / scheduler job logs
```

## Design Documents

- [Original design](docs/superpowers/specs/2026-07-18-portfolio-agent-design.md)
- [Cyberpunk dashboard design](docs/superpowers/specs/2026-07-18-cyberpunk-ui-design.md)
