"""阅读板块 —— 论文/博客的预消化管线。

与新闻管线的分工：新闻抽取"断言"供归并成事件；阅读板块抽取"值不值得读"——
中文摘要、类型、标签、重要度、一句话推荐理由。读是人的事，筛和预消化是系统的事。
"""
from __future__ import annotations

import json
import logging

import psycopg

from .config import Config
from .contentstore import ContentStore

log = logging.getLogger(__name__)

BATCH = 12
MAX_CHARS_PER_DOC = 6000

READER_PROMPT = """你是技术阅读助理。给你若干篇编号的文章（论文摘要/博客/技术写作），
调用 submit_reading 工具**一次性**提交全部文章的预消化结果，除此之外不输出任何内容。

每篇给出：
- kind：paper（论文）/ engineering（工程实践）/ analysis（深度分析）/
  release（产品/模型发布）/ discussion（社区讨论）/ blog（其他博客）
- tags：2-4 个中文标签（如 "大模型训练"、"芯片"、"数据库"、"安全"）
- summary：两三句中文摘要 —— 说清它做了什么/主张什么/结果如何，保留关键数字
- why_read：一句话，站在"时间有限的技术决策者"角度说为什么值得读（或不值得），
  有态度，别写成摘要的复读
- significance：1-5 重要度 —— 5=领域级进展/必读；4=显著新信息；3=专业相关者
  值得读；2=常规内容；1=噪音。打分要吝啬：大多数内容是 2-3，5 一天难得一篇。"""

READER_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "doc_index": {"type": "integer"},
            "kind": {"type": "string",
                     "enum": ["paper", "engineering", "analysis",
                              "release", "discussion", "blog"]},
            "tags": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string"},
            "why_read": {"type": "string"},
            "significance": {"type": "integer", "minimum": 1, "maximum": 5},
        }, "required": ["doc_index", "kind", "tags", "summary",
                        "why_read", "significance"]}},
    },
    "required": ["items"],
}


def _pending(conn: psycopg.Connection, limit: int) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.id, d.title, d.content_ref
            FROM documents d
            JOIN sources s ON s.id = d.source_id
            WHERE s.section = 'reading' AND d.status = 'ok'
              AND d.fetched_at > now() - interval '7 days'
              AND NOT EXISTS (SELECT 1 FROM reading_notes rn
                              WHERE rn.document_id = d.id)
            ORDER BY d.id DESC LIMIT %s""", (limit,))
        return cur.fetchall()


async def run_reading(conn: psycopg.Connection, cfg: Config,
                      model: str | None = None, limit: int = 60) -> dict:
    from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions,
                                  ResultMessage, create_sdk_mcp_server,
                                  query, tool)

    from .llm_extract import DISALLOW_ALL_BUILTIN

    store = ContentStore(cfg.data_dir)
    stats = {"docs": 0, "errors": 0}
    rows = _pending(conn, limit)
    if not rows:
        return stats

    docs: list[tuple[int, str]] = []      # (doc_id, 文本载荷)
    for doc_id, title, ref in rows:
        body = ""
        if ref:
            try:
                body = store.get(ref)[:MAX_CHARS_PER_DOC]
            except OSError:
                pass
        docs.append((doc_id, f"标题：{title or '(无)'}\n{body}"))

    for k in range(0, len(docs), BATCH):
        batch = docs[k:k + BATCH]
        captured: dict = {}

        @tool("submit_reading", "一次性提交全部文章的预消化结果", READER_SCHEMA)
        async def submit(args):
            captured.clear()
            captured.update(args)
            return {"content": [{"type": "text", "text": "recorded"}]}

        server = create_sdk_mcp_server(name="reading", version="1.0",
                                       tools=[submit])
        options = ClaudeAgentOptions(
            system_prompt=READER_PROMPT,
            mcp_servers={"rd": server},
            allowed_tools=["mcp__rd__submit_reading"],
            disallowed_tools=DISALLOW_ALL_BUILTIN,
            model=model, max_turns=6)
        prompt = "\n\n".join(f"===== 文章 {i} =====\n{text}"
                             for i, (_, text) in enumerate(batch))

        mdl, usage, err = model or "unknown", None, None
        try:
            async for msg in query(prompt=prompt, options=options):
                if isinstance(msg, AssistantMessage):
                    mdl = msg.model or mdl
                elif isinstance(msg, ResultMessage):
                    usage = getattr(msg, "usage", None) or {}
                    if msg.is_error:
                        err = str(msg.result)[:500]
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:500]
        got = {it.get("doc_index"): it for it in captured.get("items", [])
               if isinstance(it, dict)}
        if not got and not err:
            err = "model did not call submit_reading"

        with conn.cursor() as cur:
            cur.execute("""INSERT INTO llm_calls (purpose, model, input, output)
                           VALUES ('reading',%s,%s,%s)""",
                        (mdl,
                         psycopg.types.json.Json(
                             {"docs": [d for d, _ in batch]}),
                         psycopg.types.json.Json(
                             {"n": len(got), "usage": usage, "error": err})))
            if err:
                conn.commit()
                stats["errors"] += len(batch)
                log.warning("reading batch: %s", err)
                continue
            for i, (doc_id, _) in enumerate(batch):
                it = got.get(i)
                if it is None:
                    stats["errors"] += 1
                    continue
                cur.execute("""
                    INSERT INTO reading_notes (document_id, model, payload)
                    VALUES (%s,%s,%s)
                    ON CONFLICT (document_id) DO NOTHING""",
                            (doc_id, mdl, psycopg.types.json.Jsonb({
                                "kind": it["kind"], "tags": it["tags"][:4],
                                "summary": it["summary"],
                                "why_read": it["why_read"],
                                "significance": it["significance"]})))
                stats["docs"] += 1
        conn.commit()
        log.info("reading: batch %d-%d done (%d notes)",
                 k, k + len(batch), len(got))
    return stats
