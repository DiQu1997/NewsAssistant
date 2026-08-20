# 运维

## 生产环境（OCI，权威实例）

- 主机：`ssh -i ~/.ssh/diqu-oci.key ubuntu@129.146.63.59`（ARM64 / Ubuntu 20.04 / 23GB）
- 代码：`~/NewsAssistant`（分支 claude/repo-purpose-vndfe6）
- Python：uv 安装的 3.12（deadsnakes 无 ARM64 包）；Node 20 官方 tarball
- PostgreSQL 16（pgdg **archive** 源——focal 已归档）；DB 走 unix socket peer 认证：
  `NA_DATABASE_URL=postgresql://ubuntu@/newsassistant?host=/var/run/postgresql`
- 订阅登录态：Claude（`claude setup-token`）+ ChatGPT（`codex login`，
  headless 用 1455 端口 SSH 隧道回本机浏览器完成 OAuth）
- 时区 America/Los_Angeles —— 所有锚点阶段（7 点态势图 / 14 点复盘 /
  15 点雷达 / 16 点批量 note）按此时区

### 服务管理
```bash
sudo systemctl {status|restart|stop} newsassistant
journalctl -u newsassistant -f          # 实时日志
```

### 访问（应用无鉴权，服务绑定 127.0.0.1，绝不裸奔公网）

**首选：Tailscale** —— 任何登录了 diqu97@gmail.com tailnet 的设备直接打开：

    https://newsassistant.tail73f164.ts.net

由 `tailscale serve` 反代（tailnet-only + 正规证书），app 本体仍只绑 loopback。
服务器上管理：`tailscale serve status` / `sudo tailscale serve --https=443 off`。
注意：这台机上还有别的项目——**80 端口属于 marathon-dashboard**（公网开放），
Personal Coach 在 127.0.0.1:8000；改 serve 配置前先 `tailscale serve status`
看清现状，443 归 NewsAssistant。

备用：SSH 隧道
```bash
ssh -i ~/.ssh/diqu-oci.key -N -L 8788:localhost:8787 ubuntu@129.146.63.59
```

### 更新部署
```bash
ssh -i ~/.ssh/diqu-oci.key ubuntu@129.146.63.59 \
  "cd ~/NewsAssistant && git pull && .venv/bin/na init-db && \
   .venv/bin/na sources sync && sudo systemctl restart newsassistant"
```

## 本机（Mac，仅开发）

生产迁移后**本机不再常驻**（避免双倍消耗订阅额度）。开发时手动：
`.venv/bin/na serve --host 127.0.0.1`，用完即停。
launchd 方案（ops/com.newsassistant.serve.plist）保留但不建议再加载。

## 手机访问（局域网，仅本机开发时）

同一 Wi-Fi 下 `http://<电脑局域网IP>:8787/picture`。
注意：应用无鉴权，仅限可信局域网。
