# Portfolio Agent（投资组合助手）

[English](README.md)

基于 AI 的个人投资组合管理助手：Streamlit 仪表盘、DeepSeek 思考模式 Agent、多市场数据、定时分析与 Telegram 通知。

## 界面展示

### 仪表盘

总市值 / 盈亏、核心与卫星持仓、Ask Agent。

![仪表盘](docs/screenshots/dashboard.png)

### 建议

带置信度、紧急度与完整推理的仓位建议，可接受或忽略。

![建议](docs/screenshots/recommendations.png)

### 任务

盘后 / 新闻定时任务、立即运行、运行日志（默认北京时间）。

![任务](docs/screenshots/jobs.png)

### Telegram

任务完成后推送分析结果。

![Telegram 通知](docs/screenshots/telegram.png)

## 功能

- **多市场持仓**：美股 / A 股 / 港股 / 加密货币，核心—卫星策略
- **深度思考 Agent**：默认 `deepseek-v4-pro` + 思考模式（`reasoning_effort=max`）
- **价格快照**：先显示缓存，再后台刷新实时行情
- **定时分析**：盘后任务 + 每小时新闻（持仓相关 + 头条宏观）
- **决策审计**：会话、工具调用、建议与操作落库 SQLite
- **双语界面**：右上角 EN / CN 切换
- **Telegram**：可选启动与分析通知

## 使用方法

1. **安装与配置**
   ```bash
   pip install -r requirements.txt
   cp .env.example .env
   # 必填：DEEPSEEK_API_KEY
   # 可选：TELEGRAM_BOT_TOKEN、TELEGRAM_CHAT_ID、APP_TIMEZONE=Asia/Shanghai
   # 公网部署前：AUTH_ENABLED=true 与 AUTH_PASSWORD=你的密码
   ```

2. **启动**
   ```bash
   ./run.sh
   ```
   浏览器打开 http://localhost:8501。

3. **添加持仓** — 进入 **持仓**，按市场添加核心仓 / 卫星仓。

4. **查看组合** — **仪表盘** 看总市值、盈亏与持仓表；用 **Ask Agent** 提问。

5. **处理建议** — **建议** 页接受或忽略；完整记录在 **历史**。

6. **运行分析** — **任务** 页可查看下次执行时间，或点 **立即运行**；结果在运行日志与会话详情中查看，配置 Telegram 后会推送到手机。

## 快速开始（简版）

```bash
pip install -r requirements.txt
cp .env.example .env
# 在 .env 中配置 DEEPSEEK_API_KEY
./run.sh
```

## 验证

```bash
PYTHONPATH=. python3 -m pytest tests -v
```

## 设计文档

完整设计请见 [docs/superpowers/specs/2026-07-18-portfolio-agent-design.md](docs/superpowers/specs/2026-07-18-portfolio-agent-design.md)。
