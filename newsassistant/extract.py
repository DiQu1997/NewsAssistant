"""正文抽取 —— trafilatura，确定性、免费。

v1 教训写进代码注释里：禁止用 LLM 解析 HTML。LLM 花在理解上，
不花在"从 HTML 里找 <article> 标签"上。
"""
from __future__ import annotations

from dataclasses import dataclass

import trafilatura


@dataclass
class Extracted:
    text: str | None
    title: str | None = None
    author: str | None = None
    date: str | None = None      # ISO 字符串（trafilatura 的日期发现）


def extract_article(html: bytes | str, url: str | None = None) -> Extracted:
    # bytes 直接交给 trafilatura：它自带编码探测（GBK/Big5 等非 UTF-8
    # 站点强解 UTF-8 会得到全文替换符）
    doc = trafilatura.bare_extraction(
        html, url=url, with_metadata=True,
        include_comments=False, include_tables=False)
    if doc is None:
        return Extracted(text=None)
    # trafilatura>=2 返回 Document 对象；旧版返回 dict —— 两者都兼容
    get = (lambda k: getattr(doc, k, None)) if not isinstance(doc, dict) else doc.get
    text = get("text") or None
    title = get("title") or None
    if text and not title:
        # 元数据缺标题时兜底取正文首行（sitemap 源常无条目标题，
        # 而正文首行几乎总是标题本身）
        first = text.lstrip().splitlines()[0].strip()
        if 6 <= len(first) <= 160:
            title = first
    return Extracted(
        text=text,
        title=title,
        author=get("author") or None,
        date=get("date") or None)
