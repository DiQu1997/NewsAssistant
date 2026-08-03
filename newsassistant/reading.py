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


# ── 阅读版本（整篇重写，用户指定提示词） ─────────────────────

DIGEST_PROMPT = """你将把一篇文章重写成"阅读版本"，输出简体中文和英文两个版本，
按内容主题分成若干小节；目标是让读者通过阅读就能完整理解文章讲了什么，
就好像是在读一篇 Blog 版的文章一样。通过 submit_digest 工具一次性提交。

结构要求：
1. metadata：Title / Author / URL（素材里给了 URL 和来源，作者从文中识别，
   识别不出用来源名）
2. overview：用一段话点明文章的核心论题与结论
3. sections（按主题梳理）：
   - 每个小节都需要根据文章中的内容详细展开，让读者不需要再二次查看原文，
     每个小节篇幅要充分（数百字级别的详细展开）
   - 若出现方法/框架/流程，将其重写为条理清晰的步骤或段落
   - 若有关键数字、定义、原话，如实保留核心词，并在括号内补充注释
4. frameworks（框架 & 心智模型）：从文章中抽象出 framework & mindset，
   重写为条理清晰的步骤或段落，每个都要充分展开

风格与限制：
- 永远不要高度浓缩！宁可长，不可丢信息
- 不新增事实；若原文表述含混，保持原意并注明不确定性；若素材只有摘要级内容，
  基于现有内容如实展开，不虚构补全
- 专有名词保留原文，并在括号给出中文释义（中文版）
- 段落不要过载：一段一个逻辑；列表用以 "- " 开头的行；段落间用空行分隔
- 字数要求本身不要出现在产出里
- 中文版任何部分都不要出现繁体中文
- en 版本为对等的英文重写（不是中文版的翻译腔，是英文母语者的行文）"""

_SEC = {"type": "array", "items": {"type": "object", "properties": {
    "title": {"type": "string"}, "body": {"type": "string"}},
    "required": ["title", "body"]}}

DIGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "metadata": {"type": "object", "properties": {
            "title": {"type": "string"}, "author": {"type": "string"},
            "url": {"type": "string"}}, "required": ["title", "author", "url"]},
        "zh": {"type": "object", "properties": {
            "overview": {"type": "string"}, "sections": _SEC,
            "frameworks": _SEC},
            "required": ["overview", "sections", "frameworks"]},
        "en": {"type": "object", "properties": {
            "overview": {"type": "string"}, "sections": _SEC,
            "frameworks": _SEC},
            "required": ["overview", "sections", "frameworks"]},
    },
    "required": ["metadata", "zh", "en"],
}

DIGEST_MAX_CHARS = 30_000


async def run_digest(conn: psycopg.Connection, cfg: Config, doc_id: int,
                     model: str | None = None) -> dict:
    from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions,
                                  ResultMessage, create_sdk_mcp_server,
                                  query, tool)

    from .llm_extract import DISALLOW_ALL_BUILTIN

    store = ContentStore(cfg.data_dir)
    with conn.cursor() as cur:
        cur.execute("""SELECT d.title, d.url, d.content_ref, src.name
                       FROM documents d JOIN sources src ON src.id=d.source_id
                       WHERE d.id=%s""", (doc_id,))
        r = cur.fetchone()
    if not r:
        return {"error": f"doc {doc_id} not found"}
    title, url, ref, src_name = r
    body = ""
    if ref:
        try:
            body = store.get(ref)[:DIGEST_MAX_CHARS]
        except OSError:
            pass
    if len(body) < 200:
        body += "\n（素材有限：仅有以上摘要级内容）"

    prompt = (f"标题：{title}\n来源：{src_name}\nURL：{url}\n\n正文：\n{body}")
    captured: dict = {}
    mdl, usage, err = model or "unknown", None, None

    if model and model.startswith("codex:"):
        # ChatGPT 订阅侧：长文生成挪出 Claude 额度
        from .llm_extract import codex_structured
        m, _, eff = model[6:].partition("@")
        eff = eff or "medium"
        sys_prompt = DIGEST_PROMPT.replace(
            "通过 submit_digest 工具一次性提交。",
            "把结果作为最终答复输出：仅一个符合约定 schema 的 JSON 对象，"
            "不输出任何其他文字、不使用任何工具。")
        payload, err = await codex_structured(
            sys_prompt + "\n\n" + prompt, DIGEST_SCHEMA, m, eff, timeout=900)
        captured = payload or {}
        mdl = f"codex:{m}@{eff}"
    else:
        @tool("submit_digest", "一次性提交双语阅读版本", DIGEST_SCHEMA)
        async def submit(args):
            captured.clear()
            captured.update(args)
            return {"content": [{"type": "text", "text": "recorded"}]}

        server = create_sdk_mcp_server(name="digest", version="1.0",
                                       tools=[submit])
        options = ClaudeAgentOptions(
            system_prompt=DIGEST_PROMPT,
            mcp_servers={"dg": server},
            allowed_tools=["mcp__dg__submit_digest"],
            disallowed_tools=DISALLOW_ALL_BUILTIN,
            model=model, max_turns=6)
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
    if not captured and not err:
        err = "model did not call submit_digest"

    with conn.cursor() as cur:
        cur.execute("""INSERT INTO llm_calls (purpose, model, input, output)
                       VALUES ('digest',%s,%s,%s)""",
                    (mdl, psycopg.types.json.Json({"doc_id": doc_id}),
                     psycopg.types.json.Json({"usage": usage, "error": err,
                                              "ok": bool(captured)})))
        if err:
            conn.commit()
            log.warning("digest %s: %s", doc_id, err)
            return {"error": err}
        cur.execute("""INSERT INTO reading_digests (document_id, model, payload)
                       VALUES (%s,%s,%s)
                       ON CONFLICT (document_id) DO UPDATE SET
                         at=now(), model=EXCLUDED.model,
                         payload=EXCLUDED.payload""",
                    (doc_id, mdl, psycopg.types.json.Jsonb(dict(captured))))
    conn.commit()
    log.info("digest %s: done", doc_id)
    return {"ok": True}


async def run_digest_batch(conn: psycopg.Connection, cfg: Config,
                           model: str | None = None, limit: int = 6) -> dict:
    """自动阅读版本：重要度 ≥ digest_min_sig 且还没有 digest 的，按重要度取。"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT rn.document_id FROM reading_notes rn
            WHERE (rn.payload->>'significance')::int >= %s
              AND rn.at > now() - interval '7 days'
              AND NOT EXISTS (SELECT 1 FROM reading_digests rd
                              WHERE rd.document_id = rn.document_id)
            ORDER BY (rn.payload->>'significance')::int DESC, rn.at DESC
            LIMIT %s""", (cfg.digest_min_sig, limit))
        ids = [r[0] for r in cur.fetchall()]
    stats = {"digests": 0, "errors": 0}
    for did in ids:
        res = await run_digest(conn, cfg, did, model)
        stats["digests" if res.get("ok") else "errors"] += 1
    return stats


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
