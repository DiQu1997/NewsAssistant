"""L1 抽取层 —— Claude Agent SDK（走 Claude Code CLI 登录态，计费到订阅）。

强 schema 靠工具调用：给模型唯一一个 `submit_extraction` 工具（带 JSON
schema），不给任何文件/网络工具，要求把结构化结果作为工具参数提交 ——
schema 校验发生在工具层，比"请输出 JSON"可靠。

Extractor 是协议：orchestrator 只依赖它，测试用 FakeExtractor，
生产用 ClaudeExtractor。每次调用（含失败）都落 llm_calls —— 可审计是底线。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Protocol

import psycopg

from .config import Config
from .contentstore import ContentStore

log = logging.getLogger(__name__)

MAX_CHARS = 12000          # 超长正文截断（抽取要的是断言，不是全文复读）

CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "text":  {"type": "string", "description": "断言的一句话陈述，保留可核查的具体性（数字、日期、机构名）"},
            "who":   {"type": "string"}, "did": {"type": "string"},
            "whom":  {"type": "string"}, "when": {"type": "string"},
            "where": {"type": "string"},
            "stance": {"type": "integer", "minimum": -2, "maximum": 2,
                       "description": "本文对该断言的立场：-2 否认/反驳 -1 质疑 0 中性转述 +1 支持 +2 强支持"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        }, "required": ["text", "stance", "confidence"]}},
        "entities": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string", "description": "实体的规范名（全称，不带头衔）"},
            "kind": {"type": "string",
                     "enum": ["org", "person", "product", "place", "event", "other"]},
        }, "required": ["name", "kind"]}},
        "lang": {"type": "string", "description": "正文主要语言，ISO 639-1"},
        "is_opinion": {"type": "boolean", "description": "评论/观点文，而非事实报道"},
    },
    "required": ["claims", "entities", "lang", "is_opinion"],
}

SYSTEM_PROMPT = """你是新闻情报系统的抽取器。给你一篇文档的正文，你必须调用
submit_extraction 工具提交结构化抽取结果，除此之外不做任何事、不输出任何散文。

抽取原则：
- claim 是**可核查的断言**：谁/做了什么/对谁/何时/何地。保留数字、日期、机构名。
- 只抽文档实际主张或转述的断言，不做推断、不补外部知识。
- stance 是**本文**对断言的立场（转述别人的否认 → 记否认方的断言，stance 按本文口吻）。
- 实体用规范全称；同一实体出现多次只提交一次。
- 断言 3–10 条为宜；空洞的套话（"各方表示关切"）不算断言。"""


@dataclass
class ExtractionResult:
    claims: list[dict] = field(default_factory=list)
    entities: list[dict] = field(default_factory=list)
    lang: str | None = None
    is_opinion: bool = False
    model: str = "unknown"
    tokens_in: int | None = None
    tokens_out: int | None = None
    usage: dict | None = None      # SDK 返回的完整 usage（含缓存命中），整体入审计
    error: str | None = None


class Extractor(Protocol):
    async def extract(self, text: str, title: str | None) -> ExtractionResult: ...


class ClaudeExtractor:
    """Agent SDK 实现。CLI 未登录时构造即失败，错误早暴露。"""

    def __init__(self, model: str | None = None):
        from claude_agent_sdk import (ClaudeAgentOptions, create_sdk_mcp_server,
                                      query, tool)
        self._query = query
        self._model = model
        captured: dict = {}
        self._captured = captured

        @tool("submit_extraction", "提交本文档的结构化抽取结果", CLAIM_SCHEMA)
        async def submit(args):
            captured.clear()
            captured.update(args)
            return {"content": [{"type": "text", "text": "recorded"}]}

        server = create_sdk_mcp_server(name="extract", version="1.0", tools=[submit])
        self._options = ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={"ex": server},
            allowed_tools=["mcp__ex__submit_extraction"],
            disallowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep",
                              "WebFetch", "WebSearch"],
            model=model,
            max_turns=3,
        )

    async def extract(self, text: str, title: str | None) -> ExtractionResult:
        from claude_agent_sdk import ResultMessage
        prompt = f"标题：{title or '(无)'}\n\n正文：\n{text[:MAX_CHARS]}"
        self._captured.clear()
        model, tin, tout, usage, err = self._model or "unknown", None, None, None, None
        async for msg in self._query(prompt=prompt, options=self._options):
            if isinstance(msg, ResultMessage):
                model = getattr(msg, "model", None) or model
                usage = getattr(msg, "usage", None) or {}
                tin = usage.get("input_tokens")
                tout = usage.get("output_tokens")
                if msg.is_error:
                    err = str(msg.result)[:500]
        if not self._captured and not err:
            err = "model did not call submit_extraction"
        c = dict(self._captured)
        return ExtractionResult(
            claims=c.get("claims", []), entities=c.get("entities", []),
            lang=c.get("lang"), is_opinion=c.get("is_opinion", False),
            model=model, tokens_in=tin, tokens_out=tout, usage=usage, error=err)


# ── orchestrator ────────────────────────────────────────────

def _pending_docs(conn: psycopg.Connection, limit: int) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute("""SELECT id, title, content_ref FROM documents
                       WHERE status='ok' AND extracted_at IS NULL
                         AND content_ref IS NOT NULL
                       ORDER BY id LIMIT %s""", (limit,))
        return cur.fetchall()


def _upsert_entity(cur: psycopg.Cursor, name: str, kind: str) -> int:
    cur.execute("""SELECT id FROM entities
                   WHERE lower(canonical_name)=lower(%s) AND kind=%s
                     AND merged_into IS NULL""", (name, kind))
    r = cur.fetchone()
    if r:
        return r[0]
    cur.execute("INSERT INTO entities (canonical_name, kind) VALUES (%s,%s) RETURNING id",
                (name, kind))
    return cur.fetchone()[0]


async def run_extraction(conn: psycopg.Connection, cfg: Config,
                         extractor: Extractor, limit: int = 20) -> dict:
    store = ContentStore(cfg.data_dir)
    stats = {"docs": 0, "claims": 0, "entities": 0, "errors": 0}

    for doc_id, title, ref in _pending_docs(conn, limit):
        try:
            text = store.get(ref)
        except OSError:
            log.warning("doc %s: content file missing", doc_id)
            stats["errors"] += 1
            continue

        res = await extractor.extract(text, title)

        with conn.cursor() as cur:
            # 审计先行：调用本身（含失败）永远落库
            cur.execute("""INSERT INTO llm_calls (purpose, model, input, output,
                           tokens_in, tokens_out) VALUES ('extract',%s,%s,%s,%s,%s)""",
                        (res.model,
                         psycopg.types.json.Json({"document_id": doc_id,
                                                  "chars": len(text)}),
                         psycopg.types.json.Json({
                             "claims": res.claims, "entities": res.entities,
                             "lang": res.lang, "is_opinion": res.is_opinion,
                             "usage": res.usage, "error": res.error}),
                         res.tokens_in, res.tokens_out))
            if res.error:
                conn.commit()
                log.warning("doc %s: extract error: %s", doc_id, res.error)
                stats["errors"] += 1
                continue

            for cl in res.claims:
                struct = {k: cl.get(k) for k in ("who", "did", "whom", "when", "where")
                          if cl.get(k)}
                cur.execute("""INSERT INTO claims (document_id, text, struct, stance,
                               confidence, model_ver) VALUES (%s,%s,%s,%s,%s,%s)""",
                            (doc_id, cl["text"], psycopg.types.json.Json(struct),
                             cl["stance"], cl["confidence"], res.model))
            for ent in res.entities:
                eid = _upsert_entity(cur, ent["name"].strip(), ent["kind"])
                cur.execute("""INSERT INTO document_entities (document_id, entity_id)
                               VALUES (%s,%s) ON CONFLICT DO NOTHING""", (doc_id, eid))
            cur.execute("""UPDATE documents SET extracted_at=now(), extract_model=%s,
                           lang=coalesce(lang,%s),
                           meta = meta || %s
                           WHERE id=%s""",
                        (res.model, res.lang,
                         psycopg.types.json.Jsonb({"is_opinion": res.is_opinion}),
                         doc_id))
        conn.commit()
        stats["docs"] += 1
        stats["claims"] += len(res.claims)
        stats["entities"] += len(res.entities)
        log.info("doc %s: %d claims, %d entities", doc_id, len(res.claims),
                 len(res.entities))
    return stats
