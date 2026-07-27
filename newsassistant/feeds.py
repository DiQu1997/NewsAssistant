"""RSS/Atom 解析 —— feedparser 之上的最薄封装，产出统一的 FeedItem。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser


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
