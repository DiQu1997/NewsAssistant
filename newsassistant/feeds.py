"""RSS/Atom 解析 —— feedparser 之上的最薄封装，产出统一的 FeedItem。"""
from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")


def strip_html(text: str) -> str:
    """feed 摘要常携带内嵌 HTML（USGS 的 <dl> 列表等）——
    落库前剥标签、还原实体、归一空白。块级标签边界转为换行以保留结构。"""
    t = re.sub(r"</(p|dd|dt|li|div|br|tr|h[1-6])>|<br\s*/?>", "\n", text, flags=re.I)
    t = _TAG.sub(" ", t)
    t = html.unescape(t)
    t = "\n".join(_WS.sub(" ", ln).strip() for ln in t.splitlines())
    return re.sub(r"\n{3,}", "\n\n", t).strip()


@dataclass
class FeedItem:
    url: str
    title: str | None
    published_at: datetime | None
    author: str | None
    summary: str | None
    guid: str | None


def _to_dt(t: time.struct_time | None) -> datetime | None:
    if t is None:
        return None
    return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)


def _iso_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_sitemap(body: bytes) -> list[FeedItem]:
    """news-sitemap / 普通 sitemap → FeedItem。

    命名空间前缀站点间不统一，一律按 localname 匹配；loc 只取 <url> 的
    直接子节点（image:loc 的 localname 也叫 loc，会串）。返回新→旧排序：
    大站 sitemap 动辄数百条且顺序无保证，调用方按 max_items 截断时
    必须保住最新条目。"""
    import xml.etree.ElementTree as ET

    def local(tag) -> str:
        return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""

    root = ET.fromstring(body)
    items: list[FeedItem] = []
    for url_el in root.iter():
        if local(url_el.tag) != "url":
            continue
        loc = title = pub = lastmod = None
        for el in url_el:
            ln, text = local(el.tag), (el.text or "").strip()
            if ln == "loc" and text:
                loc = text
            elif ln == "lastmod" and text:
                lastmod = text
            elif ln == "news":
                for sub in el.iter():
                    sn, st = local(sub.tag), (sub.text or "").strip()
                    if sn == "title" and st:
                        title = st
                    elif sn == "publication_date" and st:
                        pub = st
        if not loc:
            continue
        # news:title 兼作 summary：站点 robots 禁抓文章页时（fetch_article
        # false），标题就是该条目的全部合规载荷（sitemap 本身是站点在
        # robots.txt 里声明给机器读的）
        items.append(FeedItem(
            url=loc, title=title, published_at=_iso_dt(pub or lastmod),
            author=None, summary=title, guid=loc))
    items.sort(key=lambda x: (x.published_at is not None, x.published_at),
               reverse=True)
    return items


def parse_feed(body: bytes) -> list[FeedItem]:
    parsed = feedparser.parse(body)
    items: list[FeedItem] = []
    for e in parsed.entries:
        link = e.get("link")
        if not link:
            continue
        items.append(FeedItem(
            url=link,
            title=(e.get("title") or "").strip() or None,
            published_at=_to_dt(e.get("published_parsed") or e.get("updated_parsed")),
            author=e.get("author"),
            summary=e.get("summary"),
            guid=e.get("id"),
        ))
    return items
