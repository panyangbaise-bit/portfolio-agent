# Portfolio Agent（投资组合助手）

基于 AI 的个人投资组合管理助手，支持工具调用、自主分析和跨市场持仓跟踪。

## 概览

Portfolio Agent 用于跨市场跟踪个人持仓，并提供数据驱动的仓位管理建议。助手能够监控市场新闻、按需查询金融数据，并生成带有完整推理依据的投资建议。

## 功能

- **多市场持仓**：支持美股、A 股、港股、加密货币，以及核心—卫星仓位策略
- **AI 分析**：通过 LangChain `ChatOpenAI` 使用 DeepSeek 的 OpenAI 兼容 API；由 LangGraph 驱动 ReAct 工具调用循环
- **价格快照**：先显示本地缓存的价格，后台刷新实时行情；成本价会作为首次快照兜底
- **定时分析**：4 个盘后任务和每小时新闻轮询；运行结果记录为完成、跳过或失败
- **决策审计**：SQLite 保存会话、工具调用、建议和用户操作
- **双语界面**：可从侧边栏切换中文或英文

## 覆盖市场

- 🇺🇸 美股与 ETF
- 🇨🇳 A 股
- 🇭🇰 港股
- 🪙 加密货币

## 投资策略

采用核心—卫星（Core-Satellite）混合策略：

- **核心仓**（长期）：关注宏观分析、行业趋势、基本面与长期走势
- **卫星仓**（短期）：关注技术指标、资金流、市场情绪与事件催化

## 技术栈

| 层级 | 技术 |
|---|---|
| UI | Streamlit |
| Agent | LangGraph + DeepSeek |
| 数据 | yfinance、akshare、pycoingecko、WallStreetCN |
| 数据库 | SQLite（SQLAlchemy ORM） |
| 调度 | APScheduler |
| 通知 | Telegram Bot |
| 语言 | Python 3.9+ |

## 项目结构

```text
portfolio-agent/
├── app/            # Streamlit 仪表盘
├── agent/          # AI Agent 引擎
├── adapters/       # 市场数据适配器
├── scheduler/      # 定时任务管理
├── notifier/       # Telegram 通知
├── db/             # 数据模型与查询
└── docs/           # 设计文档
```

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env
# 在 .env 中配置 DEEPSEEK_API_KEY
./run.sh
```

应用默认运行在 http://localhost:8501。

## 验证

```bash
PYTHONPATH=. python3 -m pytest tests -v
```

## 设计文档

完整设计请见 [docs/superpowers/specs/2026-07-18-portfolio-agent-design.md](docs/superpowers/specs/2026-07-18-portfolio-agent-design.md)。
