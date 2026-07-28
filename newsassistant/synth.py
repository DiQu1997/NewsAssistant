"""L3 合成层（阶段 4）—— 带引用的 running summary（docs/architecture.md §5）。

最高原则 5：**综述里无引用支撑的句子不允许出现。**
这里不是靠提示词自觉，而是结构强制：模型必须为每句话提交 claim_ids，
编排器只保留引用合法（非空、且都是本故事真实 claim id）的句子，
其余丢弃并计数。时间线条目同理。开放问题不需要引用 —— 它们的本质
就是数据里"还没有答案"的东西。

选择策略：活跃、多源/多文档、且自上次合成后有新文档的故事。
单文档故事跳过 —— 一篇文档的"综述"就是它自己，不值一次强模型调用。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import psycopg

from .llm_extract import DISALLOW_ALL_BUILTIN

log = logging.getLogger(__name__)

MAX_CLAIMS = 80          # 超长故事截断（按时间序保最新）；综述本就该压缩

SYNTH_SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"},
            "claim_ids": {"type": "array", "items": {"type": "integer"},
                          "minItems": 1,
                          "description": "支撑本句的 claim id（来自输入列表），至少一个"},
        }, "required": ["text", "claim_ids"]}},
        "timeline": {"type": "array", "items": {"type": "object", "properties": {
            "when": {"type": "string", "description": "时间锚点（ISO 日期或输入中的时间表述）"},
            "what": {"type": "string", "description": "该时点发生的状态变化，一句话"},
            "claim_ids": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
        }, "required": ["when", "what", "claim_ids"]}},
        "open_questions": {"type": "array", "items": {"type": "object", "properties": {
            "question": {"type": "string"},
            "why": {"type": "string", "description": "为什么当前数据回答不了它"},
        }, "required": ["question"]}},
    },
    "required": ["sentences"],
}

SYNTH_PROMPT = """你是情报综述员。给你一个故事的标题与全部断言（各带 id、本文立场、
信源与证据层级、时间），可能还有上一版综述。你必须调用 submit_synthesis 工具
一次性提交，除此之外不做任何事。

要求：
- sentences：3-8 句 running summary，按时间/因果组织，中立、具体、可核验。
  **每句必须给出支撑它的 claim_ids** —— 没有引用的句子会被系统直接丢弃。
  不要写任何断言列表里没有依据的话（背景知识、推测、常识补全都不行）。
- 信源有分歧时（同一事实的立场/数字不一致），在句子里点名分歧双方，
  引用双方的 claim。
- timeline：时间锚定的**状态变化**（不是每篇报道一条 —— 同一状态的重复报道
  合并），每条带引用。没有明确时间锚点的不要编。
- open_questions：数据里尚未回答、但对理解这个故事关键的具体问题
  （不是泛泛的"后续如何"）。
- 上一版综述存在时做增量更新：保留仍然成立的句子（连同引用），
  改写被新断言推翻/更新的句子。"""


@dataclass
class ClaimRow:
    id: int
    text: str
    stance: int | None
    source: str
    tier: int
    published_at: str | None


@dataclass
class StoryView:
    id: int
    title: str
    claims: list[ClaimRow] = field(default_factory=list)
    prev_sentences: list[dict] = field(default_factory=list)


@dataclass
class SynthResult:
    sentences: list[dict] = field(default_factory=list)
    timeline: list[dict] = field(default_factory=list)
    open_questions: list[dict] = field(default_factory=list)
    model: str = "unknown"
    usage: dict | None = None
    error: str | None = None


class Synthesizer(Protocol):
    async def synthesize(self, story: StoryView) -> SynthResult: ...


class ClaudeSynthesizer:
    """Agent SDK 实现 —— 唯一工具强 schema，捕获状态 per-call（家族惯例）。
    合成用强模型（架构 §5：~10² 次/日的判断力节点），默认由 CLI --model 决定。"""

    def __init__(self, model: str | None = None):
        from claude_agent_sdk import query   # 仅探测依赖可导入
        self._model = model

    @staticmethod
    def _render(s: StoryView) -> str:
        parts = [f"# 故事：{s.title}", "\n## 断言（id | 立场 | 信源 L层 | 时间 | 内容）"]
        for c in s.claims:
            parts.append(f"{c.id} | {c.stance if c.stance is not None else '·'} | "
                         f"{c.source} L{c.tier} | {c.published_at or '?'} | {c.text}")
        if s.prev_sentences:
            parts.append("\n## 上一版综述（增量更新它）")
            for x in s.prev_sentences:
                parts.append(f"- {x.get('text')} [引用: {x.get('claim_ids')}]")
        return "\n".join(parts)

    async def synthesize(self, story: StoryView) -> SynthResult:
        from claude_agent_sdk import (ClaudeAgentOptions, ResultMessage,
                                      create_sdk_mcp_server, query, tool)
        captured: dict = {}

        @tool("submit_synthesis", "一次性提交综述、时间线与开放问题", SYNTH_SCHEMA)
        async def submit(args):
            captured.clear()
            captured.update(args)
            return {"content": [{"type": "text", "text": "recorded"}]}

        server = create_sdk_mcp_server(name="synth", version="1.0", tools=[submit])
        options = ClaudeAgentOptions(
            system_prompt=SYNTH_PROMPT,
            mcp_servers={"sy": server},
            allowed_tools=["mcp__sy__submit_synthesis"],
            disallowed_tools=DISALLOW_ALL_BUILTIN,
            model=self._model,
            max_turns=6,
        )
        model, usage, err = self._model or "unknown", None, None
        async for msg in query(prompt=self._render(story), options=options):
            if isinstance(msg, ResultMessage):
                model = getattr(msg, "model", None) or model
                usage = getattr(msg, "usage", None) or {}
                if msg.is_error:
                    err = str(msg.result)[:500]
        if not captured and not err:
            err = "model did not call submit_synthesis"
        return SynthResult(
            sentences=[x for x in captured.get("sentences", []) if isinstance(x, dict)],
            timeline=[x for x in captured.get("timeline", []) if isinstance(x, dict)],
            open_questions=[x for x in captured.get("open_questions", [])
                            if isinstance(x, dict)],
            model=model, usage=usage, error=err)


# ── orchestrator ────────────────────────────────────────────

def _load_story(conn: psycopg.Connection, story_id: int) -> StoryView:
    with conn.cursor() as cur:
        cur.execute("SELECT title, summary FROM stories WHERE id=%s", (story_id,))
        title, summary = cur.fetchone()
        cur.execute("""
            SELECT c.id, c.text, c.stance, s.key, s.evidence_tier,
                   d.published_at::text
            FROM claims c
            JOIN documents d ON d.id = c.document_id
            JOIN sources s ON s.id = d.source_id
            WHERE c.story_id = %s
            ORDER BY d.published_at NULLS LAST, c.id
            """, (story_id,))
        rows = cur.fetchall()
    claims = [ClaimRow(id=r[0], text=r[1], stance=r[2], source=r[3],
                       tier=r[4], published_at=r[5]) for r in rows[-MAX_CLAIMS:]]
    prev = (summary or {}).get("sentences", []) if isinstance(summary, dict) else []
    return StoryView(id=story_id, title=title, claims=claims, prev_sentences=prev)


def _cited(items: list[dict], valid: set[int], kind: str, stats: dict) -> list[dict]:
    """引用强制：claim_ids 非空且全部真实，否则丢弃（最高原则 5）。"""
    out = []
    for x in items:
        ids = [i for i in x.get("claim_ids", []) if isinstance(i, int)]
        if ids and set(ids) <= valid:
            out.append({**x, "claim_ids": ids})
        else:
            stats["dropped"] += 1
            log.warning("synth: dropped uncited %s: %r (ids=%s)",
                        kind, str(x.get("text") or x.get("what"))[:80],
                        x.get("claim_ids"))
    return out


async def run_synthesis(conn: psycopg.Connection, synthesizer: Synthesizer,
                        limit: int = 10, min_docs: int = 2) -> dict:
    stats = {"stories": 0, "sentences": 0, "dropped": 0, "errors": 0}
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.id FROM stories s
            WHERE s.state='active'
              AND (s.synthesized_at IS NULL OR s.updated_at > s.synthesized_at)
              AND (SELECT count(*) FROM story_documents sd
                   WHERE sd.story_id=s.id) >= %s
            ORDER BY (s.scalars->>'docs')::int DESC NULLS LAST, s.updated_at DESC
            LIMIT %s""", (min_docs, limit))
        story_ids = [r[0] for r in cur.fetchall()]

    for sid in story_ids:
        story = _load_story(conn, sid)
        if not story.claims:
            continue
        res = await synthesizer.synthesize(story)
        with conn.cursor() as cur:
            # 审计先行：调用本身（含失败）永远落库
            cur.execute("""INSERT INTO llm_calls (purpose, model, input, output)
                           VALUES ('synthesize',%s,%s,%s)""",
                        (res.model,
                         psycopg.types.json.Json({
                             "story_id": sid, "claims": [c.id for c in story.claims]}),
                         psycopg.types.json.Json({
                             "sentences": res.sentences, "timeline": res.timeline,
                             "open_questions": res.open_questions,
                             "usage": res.usage, "error": res.error})))
            if res.error:
                conn.commit()
                stats["errors"] += 1
                log.warning("story %s: synthesis error: %s", sid, res.error)
                continue

            valid = {c.id for c in story.claims}
            dropped_before = stats["dropped"]
            sentences = _cited(res.sentences, valid, "sentence", stats)
            timeline = _cited(res.timeline, valid, "timeline entry", stats)
            questions = [q for q in res.open_questions if q.get("question")]

            cur.execute("""UPDATE stories SET
                               summary=%s, timeline=%s, open_questions=%s,
                               synthesized_at=now()
                           WHERE id=%s""",
                        (psycopg.types.json.Jsonb(
                            {"sentences": sentences, "model": res.model}),
                         psycopg.types.json.Jsonb(timeline),
                         psycopg.types.json.Jsonb(questions), sid))
            cur.execute("""INSERT INTO story_events (story_id, kind, payload)
                           VALUES (%s,'synthesized',%s)""",
                        (sid, psycopg.types.json.Jsonb({
                            "model": res.model,
                            "sentences": len(sentences), "timeline": len(timeline),
                            "open_questions": len(questions),
                            "dropped_uncited": stats["dropped"] - dropped_before,
                            "claims_considered": len(story.claims)})))
        conn.commit()
        stats["stories"] += 1
        stats["sentences"] += len(sentences)
        log.info("story %s synthesized: %d sentences, %d timeline, %d questions",
                 sid, len(sentences), len(timeline), len(questions))
    return stats
