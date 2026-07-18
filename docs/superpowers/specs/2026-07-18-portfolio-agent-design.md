# Portfolio Agent — 设计规格说明书

> 个人 AI 投资组合管理 agent，多市场覆盖，自主推理 + 工具调用，提供仓位管理建议。

**日期：** 2026-07-18  
**状态：** 设计中  
**目标用户：** 个人使用，单用户

---

## 1. 项目概述

### 1.1 核心理念

构建一个 **agent 为中心的**个人投资组合管理系统。用户手动输入持仓后，agent 自主跟踪市场资讯和标的数据，在关键时机提供仓位调整建议。

Agent 不是被动等待 cron 调用的分析模块，而是系统的**中央大脑**——它接收新闻信号，自主判断需要查询什么数据，调用工具获取行情/财报，最终生成带推理链的投资建议。

### 1.2 投资策略

采用"核心 + 卫星"混合策略：

| 仓位类型 | 时间周期 | 分析重点 |
|---|---|---|
| **核心仓 (Core)** | 数月 ~ 数年 | 宏观经济格局、行业景气度、基本面分析（营收/利润率/ROE/护城河）、长期趋势判断 |
| **卫星仓 (Satellite)** | 数天 ~ 数周 | 技术指标（均线/量价/MACD）、资金流向、市场情绪、短期事件催化 |

### 1.3 覆盖市场

- 🇺🇸 美股（股票、ETF）
- 🇨🇳 A股
- 🇭🇰 港股
- 🪙 加密货币

---

## 2. 系统架构

### 2.1 架构图

```
┌─────────────────────────────────────┐
│       📊 Streamlit Dashboard        │
│   持仓概览 · 建议列表 · 风险指标      │
└──────────────┬──────────────────────┘
               ↕
┌──────────────┴──────────────────────┐
│         🧠 Portfolio Agent          │
│   LLM-powered · 自主推理 · Tool-use  │
│                                      │
│   Observe → Reason → Act → Decide   │
└──┬──────────┬──────────┬────────────┘
   ↓          ↓          ↓
┌──────┐ ┌──────┐ ┌──────────┐
│📰 News│ │🔧 Mkt │ │📂 Portf. │
│  Feed │ │ Tools │ │  Store   │
└──┬───┘ └──┬───┘ └────┬─────┘
   ↓        ↓           ↓
┌──────────────────────────────────────┐
│      🗄️ SQLite — All State           │
│  持仓 · 价格缓存 · 新闻 · 建议 · 决策链│
└──────────────────────────────────────┘
```

### 2.2 模块划分

| 模块 | 路径 | 职责 |
|---|---|---|
| `app/` | Streamlit UI | 仪表盘页面、持仓管理、建议展示 |
| `agent/` | Agent 引擎 | 主循环、系统提示词、工具注册、会话管理 |
| `adapters/` | 数据适配器 | 各市场行情+新闻，统一接口 |
| `scheduler/` | 调度器 | cron 任务、市场交易日历、触发逻辑 |
| `notifier/` | 通知 | Telegram Bot 推送 |
| `db/` | 数据层 | ORM 模型、CRUD 操作 |

### 2.3 设计原则

- **适配器模式** — 每个市场/数据源一个 adapter，实现统一 `MarketAdapter` 基类，新增市场不改上层代码
- **SQL 优先** — 所有状态落库，价格、新闻、agent 决策、用户行为全部可追溯
- **agent 自主决策** — agent 根据新闻信号自行判断需要查询哪些数据，不盲目全量拉取
- **工具即接口** — 市场数据对 agent 呈现为纯函数 tool，屏蔽背后数据源差异

---

## 3. 数据模型

### 3.1 表结构

**持仓 & 交易**

| 表 | 关键字段 | 说明 |
|---|---|---|
| `holdings` | id, ticker, market(US/CN/HK/CRYPTO), shares, cost_basis, position_type(core/satellite), created_at, updated_at | 当前持仓快照 |
| `transactions` | id, holding_id, action(buy/sell/adjust), shares, price, date, notes | 交易流水，完整历史 |

**市场数据**

| 表 | 关键字段 | 说明 |
|---|---|---|
| `price_cache` | id, ticker, market, date, open, high, low, close, volume, source | 行情缓存，agent 工具调用结果 |
| `news_articles` | id, ticker(nullable), headline, source, url, published_at, summary, relevance_score | 华尔街见闻新闻 |
| `financial_reports` | id, ticker, market, report_date, report_type(quarterly/annual), revenue, eps, key_metrics(JSON) | 财报核心数据 |

**Agent 决策链**

| 表 | 关键字段 | 说明 |
|---|---|---|
| `agent_sessions` | id, triggered_by(schedule/manual/event), status, news_snapshot(JSON), started_at, ended_at | 每次 agent 激活的会话 |
| `agent_tool_calls` | id, session_id, tool_name, params(JSON), result_summary, called_at | agent 调用工具记录 |
| `recommendations` | id, session_id, ticker, action(buy_add/reduce/hold/watch), reasoning, confidence(0-1), urgency(low/med/high), status(pending/acted/dismissed), created_at | 建议输出，完整推理链 |
| `user_actions` | id, recommendation_id, action(accept/ignore/reject), notes, acted_at | 用户反馈 |

**设计意图：** 从触发新闻 → agent 会话 → 工具调用 → 建议生成 → 用户行为，全链路在 DB 中可追溯。每条建议都知道它为什么被触发、推理过程用了什么数据。

---

## 4. 数据源

| 市场 | 数据源 | 数据类型 | 认证 |
|---|---|---|---|
| 🇺🇸 美股 | yfinance | 价格、K线、财报、分红 | 无需 key |
| 🇨🇳 A股/港股 | akshare | 价格、K线、财报、资金流向 | 无需 key |
| 🪙 Crypto | CoinGecko (pycoingecko) | 价格、市值、交易量、历史 | 免费版无需 key |
| 📰 新闻 | 华尔街见闻 API | 中文财经资讯 | 无需认证 |

**华尔街见闻 API 端点：**
- `information-flow` — 全球要闻流
- `search?query=关键词` — 按标的关键词搜索
- `articles/hot` — 热门文章
- `carousel/information-flow` — 头条轮播

---

## 5. Agent 设计

### 5.1 自主循环

使用 **LangChain / LangGraph** 构建 agent 的 tool-use 循环：

```
1. Wake Up  → Cron 抓取新闻 / 用户提问 / 盘后定时触发
2. Observe  → Agent 接收：新 headlines + 当前 portfolio 状态
3. Reason   → LangGraph ReAct 循环：Agent 推理 → 调用 tools → 获取结果 → 继续推理
4. Act      → Agent 按需调用 tools：get_price, get_kline, get_financials
5. Decide   → 生成：建议 + 推理链 + 置信度 + 紧迫度
6. Persist  → 落库 → 仪表盘更新 → Telegram 推送（如有高优先级建议）
```

LangGraph 负责管理 tool-use 循环的状态机和终止条件，避免无限调用循环。

### 5.2 分析框架（按仓位类型）

**核心仓 (Core) 分析维度：**
- 宏观经济格局 — 利率、通胀、GDP、政策方向
- 行业景气度 — 产业链位置、竞争格局、监管环境
- 基本面 — 营收增长率、利润率趋势、ROE、现金流、护城河评估
- 长期趋势 — 周/月 K 线趋势、估值分位数、机构持仓变化

**卫星仓 (Satellite) 分析维度：**
- 技术指标 — 均线排列、量价关系、MACD/RSI
- 资金流向 — 北向资金/主力资金
- 市场情绪 — 新闻情绪、社交媒体热度
- 短期催化 — 财报预期、产品发布、政策事件

### 5.3 可用工具

```python
# 持仓
get_portfolio() -> list[dict]
get_holding(ticker: str) -> dict

# 行情（内部路由到对应 adapter）
get_price(ticker: str, market: str) -> dict
get_kline(ticker: str, market: str, period: str) -> list[dict]
get_financials(ticker: str, market: str) -> dict
get_market_snapshot(market: str) -> dict

# 新闻
search_ticker_news(ticker: str, days: int) -> list[dict]
get_market_headlines() -> list[dict]

# 建议管理
get_recommendation_history(ticker: str | None, limit: int) -> list[dict]
save_recommendation(ticker, action, reasoning, confidence, urgency) -> dict
```

- `market` 参数统一为 `"US" | "CN" | "HK" | "CRYPTO"`，agent 不需要知道背后数据源
- 所有工具返回结构化 dict/list，降低 agent 理解成本

### 5.4 行为约束

**推理触发：**
- 定时：每个市场每交易日一次盘后分析（核心仓看长期面，卫星仓看短期面）
- 事件：每小时间隔拉取新闻，若命中持仓标的 → 触发即时分析
- 手动：用户在仪表盘提问，随时响应

**输出规范：**
```json
{
  "action": "buy_add | reduce | hold | watch",
  "ticker": "AAPL",
  "position_type": "core | satellite",
  "reasoning": "推理链（2-4句话）",
  "analysis_dimensions": {
    "macro": "...",
    "fundamental": "...",
    "technical": "...",
    "sentiment": "..."
  },
  "confidence": 0.72,
  "urgency": "low | medium | high",
  "time_horizon": "3-6 months",
  "risk_note": "需注意的风险点"
}
```

**禁止事项：**
- ❌ 不预测具体价格点位
- ❌ 不推荐杠杆或衍生品操作
- ❌ 不给无数据支撑的建议
- ❌ 单次建议不超过 3 个标的
- ❌ 不假装知道实时数据 — 必须通过 tool 获取
- ✅ 无异常时输出健康确认（不静默）

### 5.5 工具使用原则

- 先读持仓 → 再读新闻 → 判断是否需要查行情/财报
- 核心仓查长周期 K 线（3mo-1y）+ 财报基本面
- 卫星仓查短周期 K 线（1mo-3mo）+ 技术指标 + 情绪
- 财报季前后，优先查 financials
- 不每次全量拉所有标的数据 — 只拉相关标的

---

## 6. 调度设计

### 6.1 定时任务

| 触发时间 | 任务 | 市场 |
|---|---|---|
| 每天 16:30 EST (07:00 CST 次日) | 美股盘后分析 | 🇺🇸 US |
| 每天 15:30 CST | A股盘后分析 | 🇨🇳 CN |
| 每天 16:30 HKT | 港股盘后分析 | 🇭🇰 HK |
| 每天 21:00 CST | Crypto 每日分析 | 🪙 CRYPTO |
| 每小时整点 | 新闻拉取 + 按需触发 | 全部 |

### 6.2 新闻轮询逻辑

```
每小时 → search_ticker_news(每个持仓标的)
       → Agent 判断新闻是否对持仓有实质影响
       → 有 → 触发深度分析 + Telegram 推送
       → 无 → 静默跳过
```

---

## 7. 仪表盘设计

**主视图：**
- **KPI 卡片行** — 总资产、当日涨跌、待处理建议数、风险等级
- **持仓列表** — ticker、市场、股数、成本价、现价、盈亏%（按仓位类型分组）
- **建议卡片** — agent 最新输出，每条含 action 标签、推理链、置信度、接受/忽略按钮

**侧边栏：**
- 添加/编辑持仓表单（ticker、市场、股数、成本价、core/satellite）
- 向 agent 自由提问的输入框

---

## 8. 通知设计

- **Telegram Bot** — 高优先级建议即时推送
- 推送内容：ticker、action、推理摘要、置信度、仪表盘链接
- 盘后分析无异常时发送简短摘要

---

## 9. 技术栈

| 层 | 技术 |
|---|---|
| UI | Streamlit |
| Agent | LangChain + DeepSeek API (OpenAI-compatible, tool-use agent) |
| 数据 | yfinance, akshare, pycoingecko, 华尔街见闻 API |
| 数据库 | SQLite (SQLAlchemy ORM) |
| 调度 | APScheduler |
| 通知 | python-telegram-bot |
| 语言 | Python 3.11+ |

---

## 10. 项目结构

```
portfolio-agent/
├── app/
│   ├── main.py                  # Streamlit 入口
│   ├── pages/
│   │   ├── dashboard.py         # 主仪表盘
│   │   ├── holdings.py          # 持仓管理
│   │   └── history.py           # 历史建议 & 决策追溯
│   └── components/
│       ├── kpi_cards.py
│       ├── holdings_table.py
│       └── recommendation_card.py
├── agent/
│   ├── core.py                  # LangGraph Agent 主循环
│   ├── graph.py                 # LangGraph 状态图定义
│   ├── system_prompt.py         # 系统提示词模板
│   ├── tools.py                 # 工具注册 & 定义
│   └── session.py               # 会话管理 & 持久化
├── adapters/
│   ├── base.py                  # 抽象基类 MarketAdapter
│   ├── us_market.py             # yfinance
│   ├── cn_market.py             # akshare (A股+港股)
│   ├── crypto.py                # CoinGecko
│   └── news.py                  # 华尔街见闻
├── scheduler/
│   ├── cron.py                  # APScheduler 配置
│   ├── jobs.py                  # 任务定义
│   └── triggers.py              # 交易日历 & 触发逻辑
├── notifier/
│   └── telegram.py              # Telegram Bot
├── db/
│   ├── models.py                # SQLAlchemy 模型
│   ├── schema.sql               # Schema DDL
│   └── repository.py            # CRUD 封装
├── config.py                    # 配置管理
├── requirements.txt
└── README.md
```

---

## 11. 待实现功能（非 MVP）

以下功能暂不在第一版范围内，留作后续迭代：

- 券商 API 自动同步持仓
- 回测引擎（验证 agent 建议的历史表现）
- 多语言支持
- 移动端适配
- 邮件每日摘要报告
