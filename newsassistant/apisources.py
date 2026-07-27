"""API 类源适配器注册表（阶段 1.5）—— 把一次 API 响应转成条目列表。

结构约定（通用部分，不含任何领域词汇）：
  - 源在注册表里声明 `kind: api` + `adapter: <名字>`；`url` 是完整的请求地址，
    查询参数（要哪种表单、哪个日期窗口）属于**数据**，不进代码
  - 适配器是纯函数 `(响应字节, 请求 URL) -> list[FeedItem]`，与 feeds.parse_feed 同构；
    ingest 拿到条目后走完全相同的下游管线（URL 规范化 / 三级去重 / fetch_article / fetch_log）
  - 适配器可声明 `min_interval`（源站速率合规）与 `headers`（协议要求）

适配器**内部**当然会出现该 API 的字段名 —— 那是协议细节，不是主题先验：
换一个 API 只是多一个适配器，代码里没有任何一处按主题分支。
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from .feeds import FeedItem

log = logging.getLogger(__name__)

ParseFn = Callable[[bytes, str], list[FeedItem]]

# 适配器名 → 上次请求的单调时钟（速率合规用；进程内即可，采集是单进程串行）
_last_request: dict[str, float] = {}


@dataclass(frozen=True)
class ApiAdapter:
    name: str
    parse: ParseFn
    headers: dict[str, str] = field(default_factory=lambda: {"Accept": "application/json"})
    min_interval: float = 0.0   # 同一适配器两次请求的最小间隔（秒）
    notes: str | None = None

    def wait(self) -> None:
        """阻塞到距上次请求满 min_interval 为止。源站合规是源的属性，不是调用方的自觉。"""
        if self.min_interval <= 0:
            return
        prev = _last_request.get(self.name)
        if prev is not None:
            gap = self.min_interval - (time.monotonic() - prev)
            if gap > 0:
                time.sleep(gap)
        _last_request[self.name] = time.monotonic()


ADAPTERS: dict[str, ApiAdapter] = {}


def register(name: str, *, headers: dict[str, str] | None = None,
             min_interval: float = 0.0, notes: str | None = None):
    def deco(fn: ParseFn) -> ParseFn:
        if name in ADAPTERS:
            raise ValueError(f"duplicate api adapter: {name}")
        ADAPTERS[name] = ApiAdapter(
            name=name, parse=fn,
            headers=headers if headers is not None else {"Accept": "application/json"},
            min_interval=min_interval, notes=notes)
        return fn
    return deco


def get_adapter(name: str | None) -> ApiAdapter | None:
    return ADAPTERS.get(name) if name else None


# ── 工具 ────────────────────────────────────────────────────
_WS = re.compile(r"\s+")


def _clean(s: str | None) -> str | None:
    if not s:
        return None
    return _WS.sub(" ", s).strip() or None


def _date_utc(s: str | None) -> datetime | None:
    """"YYYY-MM-DD" → 当日 UTC 零点。API 只给到日期时不假装有时刻精度。"""
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# ── EDGAR 全文检索 API ──────────────────────────────────────
# https://efts.sec.gov/LATEST/search-index?q=&forms=8-K
#   q 留空 + forms=<表单类型> = 按备案时间倒序的最近备案列表（每页 100 条）。
#   SEC 合规：UA 必须带联系方式（NA_USER_AGENT），请求间隔 ≥1s。
#   注：browse-edgar 的 atom 出口在部分网络下被 TLS 指纹拦截，JSON 端点是替代路径。
_EDGAR_ARCHIVE = "https://www.sec.gov/Archives/edgar/data"

# 响应字段 → 摘要行。备案本身没有"正文"可抓（fetch_article=false），
# 这些结构化事实就是全部载荷；顺序即可读性，缺字段自动跳过。
_EDGAR_SUMMARY_FIELDS = (
    ("Form", "form"),
    ("Filed", "file_date"),
    ("Period", "period_ending"),
    ("Items", "items"),
    ("File number", "file_num"),
    ("Location", "biz_locations"),
    ("SIC", "sics"),
    ("Accession", "adsh"),
)


def _edgar_doc_url(cik: str, adsh: str, filename: str, xsl: str | None) -> str:
    parts = [_EDGAR_ARCHIVE, str(int(cik)), adsh.replace("-", "")]
    if xsl:
        parts.append(xsl)
    parts.append(filename)
    return "/".join(parts)


@register("edgar_fulltext", min_interval=1.0,
          notes="SEC EDGAR full-text search JSON；每页 100 条，按备案时间倒序")
def parse_edgar_fulltext(body: bytes, request_url: str) -> list[FeedItem]:
    data = json.loads(body)
    items: list[FeedItem] = []
    for hit in (data.get("hits") or {}).get("hits") or []:
        src = hit.get("_source") or {}
        # _id = "<accession>:<主文档文件名>"
        doc_id = hit.get("_id") or ""
        adsh = src.get("adsh") or (doc_id.split(":", 1)[0] if ":" in doc_id else None)
        filename = doc_id.split(":", 1)[1] if ":" in doc_id else None
        ciks = src.get("ciks") or []
        if not (adsh and filename and ciks):
            log.debug("edgar_fulltext: 跳过残缺条目 %r", doc_id)
            continue

        filer = _clean((src.get("display_names") or [None])[0])
        form = _clean(src.get("form")) or "filing"
        desc = _clean(src.get("file_description"))

        lines = []
        if filer:
            lines.append(f"Filer: {filer}")
        for label, key in _EDGAR_SUMMARY_FIELDS:
            val = src.get(key)
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val if v)
            val = _clean(str(val)) if val not in (None, "") else None
            if val:
                lines.append(f"{label}: {val}")
        lines.append(f"Document: {desc + ' — ' if desc else ''}{filename}")

        items.append(FeedItem(
            url=_edgar_doc_url(ciks[0], adsh, filename, src.get("xsl")),
            title=f"{form} · {filer}" if filer else f"{form} {adsh}",
            published_at=_date_utc(src.get("file_date")),
            author=filer,
            summary="\n".join(lines),
            guid=doc_id,
        ))
    return items
