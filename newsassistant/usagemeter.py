"""订阅用量表 —— Claude Code 的 OAuth usage 端点，返回 5h/7d 窗口的
**真实占用百分比**（token 计数换算不出这个：限额权重不公开且随模型不同）。

凭据取自 Claude Code 的存放处（macOS Keychain / ~/.claude/.credentials.json），
只读、不落盘、不传出。任何失败一律返回 None —— 用量表是观测件，绝不阻塞管线。
"""
from __future__ import annotations

import json
import logging
import platform
import subprocess
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"


def _token(timeout: float) -> str | None:
    try:
        if platform.system() == "Darwin":
            raw = subprocess.run(
                ["security", "find-generic-password",
                 "-s", "Claude Code-credentials", "-w"],
                capture_output=True, timeout=timeout).stdout
            if raw:
                return json.loads(raw)["claudeAiOauth"]["accessToken"]
        p = Path.home() / ".claude" / ".credentials.json"
        if p.is_file():
            return json.loads(p.read_text())["claudeAiOauth"]["accessToken"]
    except Exception:
        pass
    return None


def fetch_claude_usage(timeout: float = 6.0) -> dict | None:
    """{'five_hour': {'utilization': 7.0, 'resets_at': iso},
        'seven_day': {...}} 或 None。utilization 是百分比。"""
    tok = _token(timeout)
    if not tok:
        return None
    try:
        req = urllib.request.Request(_ENDPOINT, headers={
            "Authorization": f"Bearer {tok}",
            "anthropic-beta": "oauth-2025-04-20"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        out = {}
        for w in ("five_hour", "seven_day"):
            if isinstance(d.get(w), dict):
                out[w] = {"utilization": d[w].get("utilization"),
                          "resets_at": d[w].get("resets_at")}
        return out or None
    except Exception as e:
        log.debug("usage fetch failed: %s", e)
        return None
