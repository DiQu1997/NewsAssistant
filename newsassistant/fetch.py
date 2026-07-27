"""HTTP 采集器 —— 条件请求、robots、超时、UA。

代理与 CA 走环境变量（httpx trust_env 默认开启），不在代码里写死。

两条通道（source.fetch_via）：httpx（默认）与 curl 子进程。
后者存在的唯一理由是真实世界的 TLS 指纹拦截：SEC 在同一 UA 下拒绝 httpx 而放行
curl。通道是源的结构属性，语义（FetchResult）两条通道完全一致，调用方无感。
'auto' = httpx 优先，遇网络错误/403 回退 curl —— 部署环境是否被拦截无法预先知道。
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

VIA_CHOICES = ("httpx", "curl", "auto")


@dataclass
class FetchResult:
    status: int              # HTTP 状态；0 = 网络错误
    body: bytes | None
    etag: str | None = None
    last_modified: str | None = None
    final_url: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.body is not None

    @property
    def not_modified(self) -> bool:
        return self.status == 304


class Fetcher:
    def __init__(self, user_agent: str, timeout: float = 20.0, respect_robots: bool = True):
        self.user_agent = user_agent
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout, follow_redirects=True)
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def close(self) -> None:
        self.client.close()

    # ── robots ──────────────────────────────────────────────
    def _robots_for(self, url: str, via: str = "httpx"
                    ) -> urllib.robotparser.RobotFileParser | None:
        host = "{0.scheme}://{0.netloc}".format(urlsplit(url))
        if host not in self._robots:
            r = self._raw(host + "/robots.txt", {}, via)
            if r.ok:
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(r.body.decode("utf-8", "replace").splitlines())
                self._robots[host] = rp
            else:
                self._robots[host] = None   # 无 robots / 取不到 → 允许
        return self._robots[host]

    def allowed(self, url: str, via: str = "httpx") -> bool:
        if not self.respect_robots:
            return True
        rp = self._robots_for(url, via)
        return rp is None or rp.can_fetch(self.user_agent, url)

    # ── 拉取 ─────────────────────────────────────────────────
    def get(self, url: str, etag: str | None = None,
            last_modified: str | None = None, check_robots: bool = False,
            headers: dict[str, str] | None = None, via: str = "httpx") -> FetchResult:
        if via not in VIA_CHOICES:
            raise ValueError(f"unknown fetch channel: {via}")
        probe = "httpx" if via == "auto" else via
        if check_robots and not self.allowed(url, probe):
            return FetchResult(status=0, body=None, error="robots_disallowed")

        hdrs = dict(headers or {})
        if etag:
            hdrs["If-None-Match"] = etag
        if last_modified:
            hdrs["If-Modified-Since"] = last_modified

        res = self._raw(url, hdrs, probe)
        if via == "auto" and (res.status == 0 or res.status == 403):
            # 网络错误或 403 可能是 TLS 指纹/UA 层的拦截 —— 换通道再试一次
            log.info("via=auto: httpx 未通过（status=%s error=%s），回退 curl：%s",
                     res.status, res.error, url)
            alt = self._raw(url, hdrs, "curl")
            if alt.status not in (0, 403):
                return alt
        return res

    def _raw(self, url: str, headers: dict[str, str], via: str) -> FetchResult:
        return self._curl(url, headers) if via == "curl" else self._httpx(url, headers)

    def _httpx(self, url: str, headers: dict[str, str]) -> FetchResult:
        try:
            r = self.client.get(url, headers=headers)
        except httpx.HTTPError as e:
            log.warning("fetch error %s: %s", url, e)
            return FetchResult(status=0, body=None, error=type(e).__name__)
        return FetchResult(
            status=r.status_code,
            body=r.content if r.status_code == 200 else None,
            etag=r.headers.get("ETag"),
            last_modified=r.headers.get("Last-Modified"),
            final_url=str(r.url))

    def _curl(self, url: str, headers: dict[str, str]) -> FetchResult:
        """curl 子进程通道 —— 与 _httpx 语义一致的 FetchResult。

        代理/CA 同样由环境变量决定（curl 自读 https_proxy），不写死。
        """
        with tempfile.TemporaryDirectory(prefix="na-curl-") as tmp:
            body_path, head_path = Path(tmp) / "body", Path(tmp) / "head"
            cmd = ["curl", "-sS", "--location", "--compressed",
                   "--max-time", str(int(self.timeout)),
                   "--user-agent", self.user_agent,
                   "--dump-header", str(head_path), "--output", str(body_path),
                   "--write-out", "%{http_code}\t%{url_effective}"]
            for k, v in headers.items():
                cmd += ["--header", f"{k}: {v}"]
            cmd.append(url)
            try:
                p = subprocess.run(cmd, capture_output=True, timeout=self.timeout + 10)
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
                log.warning("curl fetch error %s: %s", url, e)
                return FetchResult(status=0, body=None, error=f"curl:{type(e).__name__}")
            if p.returncode != 0:
                log.warning("curl fetch error %s: rc=%d %s", url, p.returncode,
                            p.stderr.decode("utf-8", "replace").strip()[:200])
                return FetchResult(status=0, body=None, error=f"curl:rc{p.returncode}")

            out = p.stdout.decode("utf-8", "replace").strip().split("\t")
            try:
                status = int(out[0])
            except (ValueError, IndexError):
                return FetchResult(status=0, body=None, error="curl:no_status")
            final_url = out[1] if len(out) > 1 else url
            resp = _last_header_block(head_path.read_text("utf-8", "replace")
                                      if head_path.exists() else "")
            body = body_path.read_bytes() if status == 200 and body_path.exists() else None
            return FetchResult(status=status, body=body,
                               etag=resp.get("etag"),
                               last_modified=resp.get("last-modified"),
                               final_url=final_url)


def _last_header_block(dump: str) -> dict[str, str]:
    """--dump-header 在重定向链上会写多个响应头块；只有最后一块是最终响应。"""
    blocks = [b for b in dump.replace("\r\n", "\n").split("\n\n") if b.strip()]
    out: dict[str, str] = {}
    for line in (blocks[-1].splitlines() if blocks else []):
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip().lower()] = v.strip()
    return out
