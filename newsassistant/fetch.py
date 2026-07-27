"""HTTP 采集器 —— 条件请求、robots、超时、UA。

代理与 CA 走环境变量（httpx trust_env 默认开启），不在代码里写死。
"""
from __future__ import annotations

import logging
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)


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
        self.respect_robots = respect_robots
        self.client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout, follow_redirects=True)
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def close(self) -> None:
        self.client.close()

    # ── robots ──────────────────────────────────────────────
    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        host = "{0.scheme}://{0.netloc}".format(urlsplit(url))
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.client.get(host + "/robots.txt")
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                    self._robots[host] = rp
                else:
                    self._robots[host] = None   # 无 robots → 允许
            except httpx.HTTPError:
                self._robots[host] = None
        return self._robots[host]

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        rp = self._robots_for(url)
        return rp is None or rp.can_fetch(self.user_agent, url)

    # ── 拉取 ─────────────────────────────────────────────────
    def get(self, url: str, etag: str | None = None,
            last_modified: str | None = None, check_robots: bool = False) -> FetchResult:
        if check_robots and not self.allowed(url):
            return FetchResult(status=0, body=None, error="robots_disallowed")
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
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
