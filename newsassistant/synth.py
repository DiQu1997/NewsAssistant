"""L3 合成层 —— 故事的 running summary / 时间线 / 开放问题（docs/architecture.md §5）。

最高原则 5：**综述里无引用支撑的句子不允许出现。**
结构上的落点：模型必须为每句综述、每条时间线注明 claim id；orchestrator
校验引用（id 必须属于本故事、非空），无效引用的句子直接丢弃并计数 ——
引用不是装饰，是句子存在的许可证。

增量维护：上一版综述随 claims 一起喂给模型（"在此基础上更新"），
synthesized_at < updated_at 的故事视为过期。产物廉价可再生 ——
换模型/换提示词后全量重算是设计内操作。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import psycopg

from .llm_extract import DISALLOW_ALL_BUILTIN

log = logging.getLogger(__name__)

MAX_CLAIMS = 40          # 喂给模型的 claim 上限（新到旧）；超长故事先靠这个截断
MIN_DOCS = 2             # 单篇故事不合成：综述只会复述唯一一篇的 claims

SYNTH_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string", "description": "一句综述，中立、具体"},
            "claim_ids": {"type": "array", "items": {"type": "integer"},
                          "description": "支撑这句话的 claim id（≥1，必须出自给定列表）"},
        }, "required": ["text", "claim_ids"]}},
        "timeline": {"type": "array", "items": {"type": "object", "properties": {
            "when": {"type": "string",
                     "description": "时间锚点，ISO 日期或原文的时间表述"},
            "what": {"type": "string", "description": "该时点发生的状态变化，一句话"},
            "claim_ids": {"type": "array", "items": {"type": "integer"}},
        }, "required": ["when", "what", "claim_ids"]}},
        "open_questions": {"type": "array", "items": {"type": "string"},
                           "description": "现有报道未回答的具体问题（不超过 5 条）"},
    },
    "required": ["summary", "timeline", "open_questions"],
}

SYNTH_PROMPT = """你是情报系统的合成器。给你一个故事的标题、按时间排列的断言
（每条带 id、立场、来源），可能还有上一版综述。你必须调用 submit_synthesis
工具一次性提交产物，除此之外不做任何事。

规则：
- **每句综述、每条时间线必须在 claim_ids 里注明支撑它的断言 id**。
  没有断言支撑的话一个字都不能写 —— 无引用的句子会被系统直接丢弃。
- 只综合给定断言的内容，不引入外部知识，不推测。
- 来源之间有分歧时**呈现分歧**（"A 称 X，B 称 Y"），不要裁决谁对。
- 综述 3-6 句：先事件核心（发生了什么、主体、时间地点），再最新进展，
  再分歧或未证实之处。有上一版时在其基础上更新，不推倒重写。
- 时间线只收**状态变化**（伤亡数字更新、立场转变、程序节点），
  不收纯背景；when 用断言里的时间表述，没有就不编。
- open_questions 是现有报道**明确缺失**的具体信息（"死者身份尚未公布"），
  不是泛泛的"事态将如何发展"。"""


@dataclass
class Synthesis:
    summary: list[dict] = field(default_factory=list)      # {text, claim_ids}
    timeline: list[dict] = field(default_factory=list)     # {when, what, claim_ids}
    open_questions: list[str] = field(default_factory=list)
    model: str = "unknown"
    usage: dict | None = None
    error: str | None = None


@dataclass
class StoryView:
    id: int
    title: str
    claims: list[dict] = field(default_factory=list)   # {id, text, stance, source, at}
    prev_summary: list[dict] | None = None


class Synthesizer(Protocol):
    async def synthesize(self, story: StoryView) -> Synthesis: ...


class ClaudeSynthesizer:
    """Agent SDK 实现 —— 唯一工具强 schema，捕获状态 per-call（并发竞态教训）。"""

    def __init__(self, model: str | None = None):
        from claude_agent_sdk import query   # 仅探测依赖可导入
        self._model = model

    @staticmethod
    def _render(s: StoryView) -> str:
        parts = [f"## 故事：{s.title}", "\n## 断言（旧→新）"]
        parts += [f"[{c['id']}] {c['text']}（立场 {c['stance']:+d}，"
                  f"源 {c['source']}，{c['at']}）" for c in s.claims]
        if s.prev_summary:
            parts += ["\n## 上一版综述（在此基础上更新）"]
            parts += [x.get("text", "") for x in s.prev_summary]
        return "\n".join(parts)

    async def synthesize(self, story: StoryView) -> Synthesis:
        from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions,
                                      ResultMessage, create_sdk_mcp_server,
                                      query, tool)
        captured: dict = {}

        @tool("submit_synthesis", "一次性提交综述/时间线/开放问题", SYNTH_SCHEMA)
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
            if isinstance(msg, AssistantMessage):
                model = msg.model or model   # ResultMessage 无 model 字段，只能从这里拿
            elif isinstance(msg, ResultMessage):
                usage = getattr(msg, "usage", None) or {}
                if msg.is_error:
                    err = str(msg.result)[:500]
        if not captured and not err:
            err = "model did not call submit_synthesis"
        return Synthesis(
            summary=[x for x in captured.get("summary", []) if isinstance(x, dict)],
            timeline=[x for x in captured.get("timeline", []) if isinstance(x, dict)],
            open_questions=[q for q in captured.get("open_questions", [])
                            if isinstance(q, str)][:5],
            model=model, usage=usage, error=err)


# ── 选取与渲染输入 ──────────────────────────────────────────

def _stale_stories(conn: psycopg.Connection, limit: int,
                   min_docs: int = MIN_DOCS) -> list[StoryView]:
    """待合成 = 活跃、多篇、且从未合成或合成后又有更新的故事，按文档数降序。"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.id, s.title, s.summary
            FROM stories s
            WHERE s.state='active'
              AND (s.synthesized_at IS NULL OR s.updated_at > s.synthesized_at)
              AND (SELECT count(*) FROM story_documents sd
                   WHERE sd.story_id=s.id) >= %s
            ORDER BY (s.scalars->>'docs')::int DESC NULLS LAST, s.id
            LIMIT %s""", (min_docs, limit))
        stories = [StoryView(id=r[0], title=r[1], prev_summary=r[2])
                   for r in cur.fetchall()]
        for s in stories:
            cur.execute("""
                SELECT c.id, c.text, coalesce(c.stance,0), src.key,
                       coalesce(to_char(d.published_at,'YYYY-MM-DD'), '?')
                FROM claims c
                JOIN documents d ON d.id=c.document_id
                JOIN sources src ON src.id=d.source_id
                WHERE c.story_id=%s
                ORDER BY d.published_at NULLS LAST, c.id
                LIMIT %s""", (s.id, MAX_CLAIMS))
            s.claims = [{"id": r[0], "text": r[1], "stance": r[2],
                         "source": r[3], "at": r[4]} for r in cur.fetchall()]
    return stories


def _enforce_citations(items: list[dict], valid_ids: set[int],
                       keys: tuple[str, ...]) -> tuple[list[dict], int]:
    """引用校验：claim_ids 必须非空且全部属于本故事。违规条目丢弃。"""
    kept, dropped = [], 0
    for it in items:
        ids = [i for i in it.get("claim_ids", []) if isinstance(i, int)]
        if ids and set(ids) <= valid_ids and all(it.get(k) for k in keys):
            kept.append({**{k: it[k] for k in keys}, "claim_ids": ids})
        else:
            dropped += 1
    return kept, dropped


# ── orchestrator ────────────────────────────────────────────

async def run_synthesis(conn: psycopg.Connection, synthesizer: Synthesizer,
                        limit: int = 10, min_docs: int = MIN_DOCS) -> dict:
    stats = {"stories": 0, "sentences": 0, "dropped": 0, "errors": 0}
    for story in _stale_stories(conn, limit, min_docs):
        res = await synthesizer.synthesize(story)
        with conn.cursor() as cur:
            # 审计先行：调用本身（含失败）永远落库
            cur.execute("""INSERT INTO llm_calls (purpose, model, input, output)
                           VALUES ('synthesize',%s,%s,%s)""",
                        (res.model,
                         psycopg.types.json.Json({
                             "story_id": story.id,
                             "claims": [c["id"] for c in story.claims]}),
                         psycopg.types.json.Json({
                             "summary": res.summary, "timeline": res.timeline,
                             "open_questions": res.open_questions,
                             "usage": res.usage, "error": res.error})))
            if res.error:
                conn.commit()
                stats["errors"] += 1
                log.warning("story %s: synthesis error: %s", story.id, res.error)
                continue

            valid = {c["id"] for c in story.claims}
            summary, drop_s = _enforce_citations(res.summary, valid, ("text",))
            timeline, drop_t = _enforce_citations(res.timeline, valid,
                                                  ("when", "what"))
            if not summary:
                # 全部句子引用无效 = 本次合成不可用；不覆盖旧版
                conn.commit()
                stats["errors"] += 1
                log.warning("story %s: all %d sentences dropped (bad citations)",
                            story.id, len(res.summary))
                continue

            cur.execute("""UPDATE stories SET summary=%s, timeline=%s,
                           open_questions=%s, synthesized_at=now() WHERE id=%s""",
                        (psycopg.types.json.Jsonb(summary),
                         psycopg.types.json.Jsonb(timeline),
                         psycopg.types.json.Jsonb(res.open_questions), story.id))
            cur.execute("""INSERT INTO story_events (story_id, kind, payload)
                           VALUES (%s,'synthesized',%s)""",
                        (story.id, psycopg.types.json.Jsonb({
                            "model": res.model, "sentences": len(summary),
                            "timeline": len(timeline), "dropped": drop_s + drop_t})))
        conn.commit()
        stats["stories"] += 1
        stats["sentences"] += len(summary)
        stats["dropped"] += drop_s + drop_t
        log.info("story %s: %d sentences, %d timeline, %d dropped",
                 story.id, len(summary), len(timeline), drop_s + drop_t)
    return stats
