# Portfolio Agent

AI-powered personal portfolio management agent with autonomous reasoning and tool-calling capabilities.

## Overview

An agent-centric system that tracks your investment portfolio across multiple markets and provides data-driven position management advice. The agent autonomously monitors market news, queries financial data on demand, and generates recommendations with full reasoning chains.

### Markets Covered
- 🇺🇸 US Stocks & ETFs
- 🇨🇳 China A-Shares
- 🇭🇰 Hong Kong Stocks
- 🪙 Cryptocurrency

### Investment Strategy
Core-Satellite hybrid approach:
- **Core positions** (long-term): macro analysis, industry trends, fundamentals, long-term trends
- **Satellite positions** (short-term): technical indicators, capital flows, market sentiment, event catalysts

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Streamlit |
| Agent | Anthropic Claude API (tool-use) |
| Data | yfinance, akshare, pycoingecko, WallStreetCN |
| Database | SQLite (SQLAlchemy ORM) |
| Scheduler | APScheduler |
| Notifications | Telegram Bot |
| Language | Python 3.11+ |

## Project Structure

```
portfolio-agent/
├── app/            # Streamlit dashboard
├── agent/          # AI Agent engine
├── adapters/       # Market data adapters
├── scheduler/      # Cron job management
├── notifier/       # Telegram notifications
├── db/             # Database models & queries
└── docs/           # Design specs & documentation
```

## Getting Started

*Coming soon — implementation in progress.*

## Design Spec

See [docs/superpowers/specs/2026-07-18-portfolio-agent-design.md](docs/superpowers/specs/2026-07-18-portfolio-agent-design.md) for the full design specification.
