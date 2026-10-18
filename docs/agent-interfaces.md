# A2A、MCP 与 ChatGPT Actions

Portfolio Agent 提供两条访问同一份账本的通道：其他 agent 通过 A2A 查询，ChatGPT Custom GPT 通过 Actions 查询。两者都可读取持仓、成交记录，并发起带上下文的自然语言分析。外部请求只读；模型工具列表和工具执行层都会阻止修改持仓、交易、关注列表和建议。分析会保存会话及工具调用审计，行情查询可能更新缓存。

## 共用 HTTPS 域名：UI + A2A（推荐）

以下以 `https://portfolio.example.com` 为例，请替换为你自己的 HTTPS 域名；UI 与 A2A 共用域名，无需额外 DNS 记录或证书。Caddy 按路径转发：网页到本机 8501，A2A 到本机 8502；A2A 继续使用现有 Bearer token，不依赖网页登录。新增配置文件不代表服务器已经部署。

服务器 `/opt/portfolio-agent/.env` 修改以下字段，保留原来的 `A2A_TOKEN` 和其他配置：

```dotenv
A2A_ENABLED=true
A2A_HOST=127.0.0.1
A2A_PORT=8502
A2A_PUBLIC_URL=https://portfolio.example.com
```

把 [deploy/Caddyfile.portfolio](../deploy/Caddyfile.portfolio) 中的示例域名替换为实际域名后，放到 `/etc/caddy/conf.d/portfolio.caddy`，替换该域名原来的配置。主 `/etc/caddy/Caddyfile` 必须已包含 `import /etc/caddy/conf.d/*.caddy`，同一域名只定义一次。不要使用 `handle_path`，它会剥离 A2A 所需的路径。此配置同时支持 A2A 1.0 和旧版 0.3，不公开 Actions 路由。

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
# 仅在 validate 成功后执行：
sudo systemctl reload caddy
sudo systemctl restart portfolio-agent
curl --fail --show-error https://portfolio.example.com/a2a/v1/.well-known/agent-card.json
curl --silent --show-error -o /dev/null -w '%{http_code}\n' \
  -X POST https://portfolio.example.com/a2a/v1 \
  -H 'Content-Type: application/json' --data '{}'
```

Agent Card 的 `supportedInterfaces[0].url` 应为 `https://portfolio.example.com/a2a/v1`；第二个请求未带 token，应返回 **401**。如果返回 HTML，说明请求仍然转发到 UI。若返回 502，检查 A2A 是否在本机 8502 运行。

HTTPS 验证成功后，在本机项目目录更新桥接器：

```bash
.venv/bin/python deploy/install-a2a-mcp.py --base-url https://portfolio.example.com --codex
node deploy/test-a2a-mcp.mjs
```

重新连接 Codex MCP 或重启客户端，已运行的桥接进程才会加载新地址。此命令启用 `requireHttps`，本机 `.env` 中的 token 保持不变。确认网页和 MCP 查询正常后，删除阿里云防火墙的公网 TCP 8501、8502 放行规则，保留 80、443 以及管理服务器所需的 SSH 规则。应用仍需在服务器内部运行这两个端口。

若需回退，在服务器恢复修改前的 `.env` 和 Caddy 配置，然后重新验证、重载 Caddy 并重启应用；本机桥接器也需恢复匹配的地址。

## 无域名最简部署：UI + A2A

服务器只需运行一条部署命令（首次仍需填写模型密钥；公网 UI 需先按 [Google 登录部署](google-login.md) 配置 HTTPS 和账号授权）：

```bash
sudo ./deploy/setup-server.sh
```

脚本会自动启用 A2A、生成或保留 `A2A_TOKEN`，默认绑定 `127.0.0.1:8502`，保留已有 A2A 地址与端口，不更改 Actions 设置。UI（8501）、A2A（8502）和调度器由同一个 `portfolio-agent` 服务启动、重启与开机自启。无需额外启动 `a2a.serve`。若需跳过自动配置，使用 `sudo SETUP_A2A=0 ./deploy/setup-server.sh`，原有设置继续生效。

**先将本次代码提交并推送到部署分支。** 脚本会同步远端分支并清理服务器本地改动；只有本机尚未推送的修改不会被部署。

### 直接通过服务器 IP + token 连接（无需 SSH 隧道）

两端配置同一个 `A2A_TOKEN` 即可鉴权，不需要域名。HTTP 不加密，token 和查询内容会明文传输；如接受这一点，可按下面配置。

在**服务器** `.env` 设置：

```dotenv
A2A_ENABLED=true
A2A_HOST=0.0.0.0
A2A_PORT=8502
A2A_PUBLIC_URL=http://47.85.190.120:8502
A2A_TOKEN=替换为你的长随机密钥
ACTIONS_ENABLED=false
```

可直接使用部署脚本已经生成的 A2A_TOKEN；不要使用示例占位文本。然后运行 `sudo ./deploy/setup-server.sh`，脚本会保留这些地址和密钥。若代码已部署，只改 `.env`，执行 `sudo systemctl restart portfolio-agent` 即可。

在阿里云轻量服务器防火墙放行 TCP **8502**；如果系统启用了 UFW，也放行该端口。可以把允许来源限定为本机公网 IP。UI 仍通过原来的 8501 端口访问。

在**本机**项目 `.env` 中设置与服务器相同的 `A2A_TOKEN`，然后运行：

```bash
.venv/bin/python deploy/install-a2a-mcp.py --base-url http://47.85.190.120:8502 --allow-http --codex
node deploy/test-a2a-mcp.mjs
```

重新连接 Codex MCP 或重启客户端以加载新配置与 token。若此前配置过 `PORTFOLIO_A2A_TOKEN` 环境变量，需同时更新或移除，因为它优先于 `.env`。MCP 将直接连接服务器，不需要本机 `a2a.serve`，也不需要保持 SSH 连接。不要把 token 填进 URL 或发到聊天。

只填写相同 token 不够：服务器必须监听公网接口、Agent Card 中的 URL 必须是上述公网地址、8502 必须放行。服务器不需要安装 MCP；桥接器安装在调用它的客户端。

### SSH 隧道（可选的加密连接方式）

如果选择隧道，服务器使用默认 `A2A_HOST=127.0.0.1` 和 `A2A_PUBLIC_URL=http://127.0.0.1:8502`；服务器防火墙只需原有的 SSH 22 和 UI 8501，不必开放 8502。

本机终端运行（替换 SSH 用户名；若使用指定密钥可加 `-i 密钥路径`）：

```bash
ssh -NT -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:8502:127.0.0.1:8502 用户名@47.85.190.120
```

保持终端运行。本地 8502 若正被测试版 `a2a.serve` 占用，应先停止该测试服务，再建立隧道；不能让 MCP 误连本地账本。这里两端端口都用 8502，以匹配 Agent Card 中的地址；如果服务器曾自定义端口或公网 URL，需同步调整隧道和 MCP 配置。

首次连接时，在服务器 `.env` 中读取 `A2A_TOKEN`，安全复制到本机项目 `.env` 同名字段，然后重新连接 MCP。不要把 token 发到聊天。隧道方式的 MCP 应指向 `http://127.0.0.1:8502`；可运行 `.venv/bin/python deploy/install-a2a-mcp.py --codex` 安装或切回该地址。

验收：

```bash
node deploy/test-a2a-mcp.mjs
```

服务器上的日常重启仍是一条命令：`sudo systemctl restart portfolio-agent`。SSH 隧道在需要从本机访问时保持连接；这条无域名方案供 A2A/MCP 使用，ChatGPT 手机端 Actions 仍需公共 HTTPS。

## 本地使用

需要 Python 3.10+、Node.js 20+。本次实测 Python 3.13、Node.js 22。项目 `.env` 需已有可用的 `DEEPSEEK_API_KEY`。

在项目根目录运行：

```bash
# 已安装项目依赖时可跳过第一行
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python deploy/configure-external-api.py
.venv/bin/python deploy/install-a2a-mcp.py --codex
.venv/bin/python -m a2a.serve
```

配置脚本启用两个接口、生成独立的随机 Bearer token，并把 `.env` 权限设为 600；已有 token 会保留。独立接口服务监听 `127.0.0.1:8502`，不会启动 UI、定时任务或 Telegram。完整应用 `server.py` 也会启动这个接口，因此两种启动方式选一种，避免端口冲突。

已安装的桥接器是上游 [CognicellAI/a2a-mcp](https://github.com/CognicellAI/a2a-mcp)，固定版本 `@cognicellai/a2a-mcp@0.1.1`，安装时禁用 npm 生命周期脚本。安装位置：

- 包：`~/.local/share/portfolio-agent-a2a/`
- MCP 配置：`~/.config/portfolio-agent/a2a-mcp.json`
- Codex MCP 名称：`a2a-bridge`；agent 别名：`portfolio`
- 启动包装器：`deploy/run-a2a-mcp.py`，从项目 `.env` 读取 `A2A_TOKEN`，也支持环境变量 `PORTFOLIO_A2A_TOKEN` 覆盖。不会把 token 写入 MCP 配置或命令参数。

不使用 Codex 的其他 MCP 客户端也可使用安装脚本输出的 `command` 数组配置 stdio server。安装后若客户端尚未显示新工具，刷新 MCP 连接或重启客户端。MCP 不会自动启动 portfolio-agent，必须保持接口服务运行。

在另一个终端验证：

```bash
node deploy/test-a2a-mcp.mjs
# 额外完成一次真实模型与工具问答，会使用模型 API
node deploy/test-a2a-mcp.mjs --ask
```

脚本检查 MCP 初始化、工具发现、Agent Card、鉴权、持仓/交易结构化查询、任务轮询和分页。`--ask` 检查真实问答，输出不包含具体资产数值。

## 接口与查询范围

| 通道 | 发现或入口 | 鉴权 |
|---|---|---|
| A2A 0.3 | `GET /.well-known/agent-card.json`，`POST /` | `A2A_TOKEN` |
| A2A 1.0 JSON-RPC | `GET /a2a/v1/.well-known/agent-card.json`，`POST /a2a/v1` | `A2A_TOKEN` |
| GPT Actions | `GET /openapi.json`，`/api/v1/*` | `ACTIONS_TOKEN` |

发现文档和 OpenAPI 公开；实际数据接口需要 `Authorization: Bearer …`。两个 token 分开，不能互换。它们是个人单账户访问凭证，没有按 agent 或用户隔离的子账户权限。

A2A 支持 0.3 的 `message/send`、`tasks/get`，以及 1.0 的 `SendMessage`、`GetTask`。不支持流式订阅、取消、推送通知、任务列表和扩展卡片。桥接器可能展示这些通用工具，但本服务不会实现对应方法。上游桥接器使用 1.0，旧客户端仍可使用 0.3。

调用 MCP 的 `a2a_send_message` 示例：

```json
{
  "agent": "portfolio",
  "request": {
    "message": {
      "messageId": "每次新问题生成唯一ID，重试复用",
      "role": "ROLE_USER",
      "parts": [{"data": {
        "operation": "transactions",
        "filters": {"market": "US", "start_date": "2026-10-01", "end_date": "2026-10-16", "limit": 25}
      }}]
    },
    "configuration": {"returnImmediately": true}
  }
}
```

自然语言问题把 `parts` 改为 `[{"text":"请复盘我最近一个月的交易"}]`。提交后用 `a2a_get_task`，参数 `{"agent":"portfolio","request":{"id":"返回的任务ID"}}` 查询结果。追问把返回的 `contextId` 放在下一次 `message` 中。1.0 HTTP 响应的任务在 `result.task` 中；桥接器 SDK 会规范化为直接的 task 对象，状态也可能是数字枚举，完成为 3。

| operation / REST 路径 | 可用筛选 | 返回内容 |
|---|---|---|
| `holdings` / `GET /api/v1/holdings` | ticker、market、status、limit、offset | 代码、市场、币种、份额、单位成本、仓位类型及状态 |
| `transactions` / `GET /api/v1/transactions` | ticker、market、action、start_date、end_date、limit、offset | 买卖方向、份额、成交价、原币金额、时间、备注 |
| `POST /api/v1/queries` | question、可选 context_id / request_id | 立即返回 202、task_id、context_id 和状态 |
| `GET /api/v1/queries/{task_id}` | 可选 offset | 状态、答案、后续答案偏移、错误或建议轮询间隔 |

市场为 US/CN/HK/CRYPTO；持仓默认 `status=open`，支持 closed/all；交易包括已清仓标的。归档仓位不返回。默认每页 25 条，最多 100 条，按 `next_offset` 继续。日期含首尾 UTC 日，交易按时间倒序。单位成本是券商残馀成本，不能当现价或总收益，不同币种不能直接相加。实时价格、收益和综合分析使用自然语言接口。

问答接口立即接受任务，避免模型耗时超过单次 HTTP 调用限制。最多同时执行 4 个任务；同一上下文需等前一任务完成才能追问。Actions 繁忙返回 429，A2A 返回 JSON-RPC 错误；应稍后重试。重试复用 `request_id` / `messageId`，防止重复模型调用。答案每页最多 20,000 字符。

任务和追问上下文存在内存中：服务重启、24 小时过期或容量淘汰后不可继续取回；容量最多 256 个任务。已保存的分析审计仍在数据库中。A2A 和 Actions 的任务、上下文相互隔离。

## 阿里云轻量服务器部署（美国弗吉尼亚区）

下面按已有 Ubuntu 服务、目录 `/opt/portfolio-agent`、systemd 名称 `portfolio-agent` 编写；若实际路径不同需替换。部署前备份服务器数据库和 `.env`，不要用本机的账本或 `.env` 覆盖服务器数据。

### 1. 准备域名和 HTTPS

将一个域名（例如 `portfolio.example.com`，下文必须换成你的真实域名）的 A 记录指向 `47.85.190.120`。在阿里云轻量服务器防火墙放行 TCP 80、443；系统启用了 UFW 时也放行这两个端口。8502 保持仅监听回环地址，不需公网放行。

目前的 `http://47.85.190.120:8501/` 是 UI 地址，不能直接作为 Actions 服务。OpenAI 要求有效公共证书、HTTPS 443、TLS 1.2+；单次请求超时 45 秒，因此本实现使用异步提交和轮询。[OpenAI Actions 生产要求](https://developers.openai.com/api/docs/actions/production)

### 2. 更新应用代码与配置

将包含本次修改的版本上传到服务器应用目录，或在修改提交并推送后按现有发布流程更新。保留服务器的 `.env`、数据库、`data/` 和 `.venv`。不要直接用现有 `setup-server.sh` 部署尚未推送的本地修改：它会强制同步远端分支，可能丢弃这些修改。

以运行 portfolio-agent 的服务用户在应用目录执行：

```bash
cd /opt/portfolio-agent
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python deploy/configure-external-api.py --base-url https://portfolio.example.com
```

脚本生成或保留服务器自己的 A2A/Actions token，并设置 `A2A_HOST=127.0.0.1`、`A2A_PORT=8502` 和两个公网 URL。确认 `.env` 属于服务用户且仍有原来的模型密钥。然后重启完整服务：

```bash
sudo systemctl restart portfolio-agent
sudo systemctl --no-pager status portfolio-agent
curl --fail http://127.0.0.1:8502/a2a/v1/.well-known/agent-card.json
```

`server.py` 会同时启动 UI、调度器和外部接口；这里不要额外运行 `python -m a2a.serve`。

### 3. 配置 Caddy 反向代理

如果服务器已有占用 80/443 的 Nginx 或其他代理，在现有代理中配置有效 HTTPS，并转发到 `127.0.0.1:8502`。没有代理时可使用 Caddy。Ubuntu/Debian 安装步骤来自 [Caddy 官方安装文档](https://caddyserver.com/docs/install)：

```bash
sudo apt install --yes debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
sudo chmod o+r /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

参考 [Caddyfile 模板](../deploy/Caddyfile.portfolio-api)，把以下站点块加入 `/etc/caddy/Caddyfile`，保留已有站点：

```caddyfile
portfolio.example.com {
    request_body {
        max_size 100KB
    }
    reverse_proxy 127.0.0.1:8502
}
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
curl --fail https://portfolio.example.com/openapi.json
curl -i https://portfolio.example.com/api/v1/holdings
```

最后一个请求未带 token，预期 **401**；这表明数据接口受保护。DNS 和端口配置正确后，Caddy 自动申请、续期证书，参见 [自动 HTTPS](https://caddyserver.com/docs/automatic-https)。这段代理配置只公开外部 API，UI 仍使用原来的地址和登录设置。

### 4. 配置自己的 Custom GPT

在 ChatGPT 网页端创建 GPT：

1. 复制 [Custom GPT 配置说明](custom-gpt-instructions.md) 中的名称、描述、开场白与 Instructions。
2. 新增 Action，从 `https://你的域名/openapi.json` 导入。也可运行下面的导出脚本后粘贴 JSON；仓库附带的文件使用占位域名，不能原样上线。
3. Authentication 选择 **API Key → Bearer**，填服务器 `.env` 的 **ACTIONS_TOKEN**。在自己的终端或编辑器中读取，直接填入 GPT 配置，不要粘贴到聊天或 Instructions。鉴权配置见 [OpenAI 官方文档](https://developers.openai.com/api/docs/actions/authentication)。
4. 测试持仓、交易和问答操作；问答需测试提交后使用 `getPortfolioAnswer` 轮询。保存为 **仅自己 / Only me**，因为该凭证可读取个人投资数据。
5. 在手机 ChatGPT 用同一个账号打开保存的 GPT，提问“我目前有哪些持仓？”或“最近一个月买卖了什么？”。手机端通过 Actions 访问公网 API，不需要手机安装 MCP。

```bash
.venv/bin/python deploy/export-actions.py --base-url https://portfolio.example.com --output deploy/gpt-actions.openapi.json
```

### 5. 把本机 MCP 切到服务器（可选）

本机重新运行安装配置脚本，将发现地址改成公网域名：

```bash
.venv/bin/python deploy/install-a2a-mcp.py --base-url https://portfolio.example.com --codex
```

此时包装器读取的 token 必须与**服务器 A2A_TOKEN**一致。将该 token 安全配置到本机项目 `.env` 的 A2A_TOKEN，或由 MCP 客户端通过 `PORTFOLIO_A2A_TOKEN` 环境变量注入，然后重启 MCP 连接。不要使用 ACTIONS_TOKEN，也不要假定此前生成的本机 token 与服务器相同。运行 `node deploy/test-a2a-mcp.mjs --ask` 再验收一次。

## 验证记录与限制

本地已完成：真实 MCP stdio → 上游桥接器 → A2A → 账本查询/分页；真实模型工具问答；当前 Codex 会话直接调用 MCP 的发现、提交和取结果；Actions 的鉴权、持仓、交易、异步真实问答；OpenAPI 3.1 schema 验证。

自动测试覆盖按市场和日期筛选、清仓/归档处理、分页、两套 token 隔离、幂等重试、追问、任务状态与只读执行保护。完整测试曾得到 232 通过、1 跳过、1 失败和 5 初始化错误；相同 6 项在未修改的 HEAD 上也复现，涉及新 Streamlit 的测试路径解析和新 LangGraph 的直接 ToolNode 调用约定。

未验证：服务器实际部署、公共证书、ChatGPT GPT 编辑器导入和手机端操作。这些需按以上步骤配置真实域名和 GPT 后验收。接口是个人只读集成，没有订单执行能力或多用户 OAuth。
