# 运维

## 本机常驻（macOS launchd）

开机自启 + 进程崩溃自动拉起：

```bash
cp ops/com.newsassistant.serve.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.newsassistant.serve.plist
```

停用：

```bash
launchctl unload ~/Library/LaunchAgents/com.newsassistant.serve.plist
```

注意：`na` 入口偶发因 editable install 失效报 `ModuleNotFoundError: newsassistant`，
重跑一次 `pip install -e .` 即恢复。

限制：笔记本合盖睡眠期间不会跑。要么 `sudo pmset -a sleep 0` 常醒（插电时），
要么部署到常开服务器（见下）。

## 服务器部署（真正的稳定态）

任何常开 Linux 盒子即可（如 OCI 实例）。要点：

1. PostgreSQL 16 + `createdb newsassistant`，`.env` 写 `NA_DATABASE_URL`
2. `python3.12 -m venv .venv && pip install -e . claude-agent-sdk`
3. **订阅授权**：服务器上跑 `claude setup-token`（headless OAuth，
   一次性把订阅登录态放上去），Agent SDK 即可用订阅额度
4. `na init-db && na sources sync && na channels sync`
5. systemd unit 跑 `na serve --host 0.0.0.0`，dashboard 走 SSH 隧道或反代
