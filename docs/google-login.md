# Google 登录部署

页面只允许 `.env` 中 `AUTH_ALLOWED_EMAILS` 列出的 Google 账号访问。密码登录已删除；旧 `AUTH_PASSWORD`、IP 黑名单、`auth_ok` 会话标记不再用于鉴权。默认启用认证，缺少配置或白名单时拒绝访问。仅本机开发可以显式设置 `AUTH_ENABLED=false`。

以下示例使用 `https://portfolio.example.com`，授权账号以 `owner@example.com` 表示。部署时请替换示例域名和邮箱。无需新的域名或端口。A2A 的 Bearer token 不受影响。Google 负责账号认证，页面在每次运行时重新检查邮箱授权，不能以“任意 Google 账号已登录”作为访问依据。

## 1. 创建 Google 登录客户端

在 [Google Cloud Console](https://console.cloud.google.com/) 创建或选择项目，进入 **Google Auth Platform**：

1. **Branding**：应用名填 `Portfolio Agent`，支持和联系邮箱填你的邮箱；如要求授权域名，填 `example.com`。
2. **Audience**：个人 Gmail 账号选择 **External**。可先保留 Testing；如显示 Test users，添加 `owner@example.com`。
3. **Data Access**：只使用 `openid`、`email`、`profile` 身份权限，不申请 Gmail、Drive、离线访问等权限。
4. **Clients → Create client**：类型选 **Web application**。授权重定向 URI 必须逐字填写：

   ```text
   https://portfolio.example.com/oauth2callback
   ```

   本方案使用服务端重定向，不需要 JavaScript origins；如果填写，使用 `https://portfolio.example.com`，不带路径。
5. 保存 Client ID 和 Client Secret。Client Secret 不要发到聊天、提交到 Git 或放进命令行参数。

本应用只请求基本身份权限；Google 官方说明这类请求不受 Testing 状态通常的 7 天授权到期限制。不需要每周更换 Client Secret。[Google Audience 说明](https://support.google.com/cloud/answer/15549945?hl=en)

## 2. 同步代码并配置服务器

先把这次修改同步到 `/opt/portfolio-agent`，包括 `app/auth.py`、`app/main.py`、`app/i18n.py`、`config.py`、`requirements.txt` 和 `deploy/configure-google-auth.py`。如果使用 Git，需要先提交推送对应分支，再在服务器拉取。**本地文件修改不会自动上线。** 不要在改动尚未推送时运行会重置到远端分支的 `setup-server.sh`。

在服务器以运行应用的用户执行（当前为 `admin`）：

```bash
cd /opt/portfolio-agent
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python deploy/configure-google-auth.py \
  --base-url https://portfolio.example.com \
  --email owner@example.com
```

按提示输入 Client ID 和 Client Secret。密钥输入不回显。脚本将：

- 启用 `AUTH_ENABLED=true`，设置唯一授权邮箱。
- 自动生成随机 Cookie 签名密钥，将 Google 配置写入 `.streamlit/secrets.toml`，文件权限为 `600`，已被 Git 忽略。
- 保留 `.env` 中的模型、A2A 和其他设置，删除旧 `AUTH_PASSWORD` 和 `AUTH_MAX_FAILURES`。
- 保留 secrets 文件的其他顶级配置；替换 `[auth]` 为仅 Google 登录。同一客户端重复执行时保留 Cookie 密钥；更换客户端 ID 时重新生成。

确认配置完成后：

```bash
sudo systemctl restart portfolio-agent
sudo systemctl status portfolio-agent --no-pager
```

当前 Caddy 对 `/a2a/v1` 的路由保持原样；其余路径转发到 `127.0.0.1:8501`，因此 `/oauth2callback`、`/auth/login`、`/auth/logout` 自动到达 Streamlit，无需新增 Caddy 规则。保留 Streamlit 的 CORS/XSRF 防护。公网使用 HTTPS，云防火墙保持关闭 8501、8502 的公网入口。

`setup-server.sh` 的目录同步已排除 `.streamlit/secrets.toml`，后续部署会保留登录配置并收紧文件权限。迁移服务器时将 `.env` 与 secrets 文件私密迁移，并维持服务用户可读、权限 `600`；域名不变时 Google 回调地址不变。

## 3. 验收

1. 无痕窗口访问网站，应只显示 Google 登录按钮，不显示资产、导航或密码框。
2. 使用 `owner@example.com` 登录，应进入页面，侧边栏显示邮箱和“退出登录”。
3. 换用其他 Google 账号，应该显示“没有访问权限”，不能读取任何页面数据。
4. 退出后当前页面回到登录状态；使用无痕窗口再次访问仍需登录。
5. 运行 `node deploy/test-a2a-mcp.mjs`，确认独立的 A2A 通道可用。

本地回归测试：

```bash
.venv/bin/python -m pytest tests/test_auth.py tests/test_google_auth_setup.py tests/test_i18n.py tests/test_a2a_server.py -q
```

真实 Google 回调需要有效的 OAuth 客户端和浏览器授权，模拟测试不能代替上述验收。

## 会话与故障排查

- Streamlit 使用签名身份 Cookie，默认可保留登录约 30 天；不会每次打开页面都要求重新授权。Google 的短期 ID token 有效期与网站登录 Cookie 不是一回事。退出会清除当前浏览器 Cookie，但其他已经打开的会话仍可能保持登录；移除白名单并重启服务会终止这些会话。[Streamlit 认证说明](https://docs.streamlit.io/develop/concepts/connections/authentication)
- 浏览器需要能连接 Google 登录服务，服务器也需要能连接 Google 的身份验证端点。域名和 HTTPS 本身不会解决中国大陆网络访问 Google 的限制。
- `redirect_uri_mismatch`：检查 Google 客户端和 secrets 文件是否都使用完整的 `https://portfolio.example.com/oauth2callback`，没有多余斜杠或端口。
- “登录尚未配置完成”：检查授权邮箱、secrets 文件位置、文件权限，以及服务的工作目录是否为 `/opt/portfolio-agent`；不要通过关闭认证来修复。
- 正确邮箱仍被拒绝：要求 Google 验证过的 Gmail 或 Google Workspace 身份，且邮箱完全匹配白名单。第三方邮箱注册的 Google 账号不能仅凭 `email_verified` 获得访问权。[Google 邮箱权威性说明](https://developers.google.com/identity/sign-in/web/backend-auth)
- 登录后回到登录页：检查浏览器是否禁用 Cookie、HTTPS 地址是否一致、服务器时间是否正确；查看 `journalctl -u portfolio-agent`。日志可能含 OAuth 回调参数，分享前应移除凭据和授权码。
- `AUTH_ENABLED=false` 是本地开发开关，公网环境必须保持为 `true`。Client Secret 和 Cookie 密钥仍是服务端秘密，但它们不再是用户输入即可直接访问资产的共享密码。
