"""板块综述层（section_digest，docs/design-handoff）。

每个域一段模型写的话：**这半天这个板块发生了什么、共同主题是什么** ——
不是复述某一条故事的摘要，而是跨故事看出主线。首页 5a 的板块综述行、
板块页 5b 的板块头共用这一段。

最高原则 5 沿用：每句综述必须注明支撑它的 claim id，无引用的句子丢弃。
has_new 由确定性活动量（近 12h 新增断言数）算出 —— 模型改不了这个标记，
只负责把话写老实：本域近 12h 无新增断言时，必须如实说，不许拿旧闻充数。

产物廉价可再生：每 12h（搭 synthesize 的 8:00/20:00 车）覆盖重算。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import psycopg

from .llm_extract import DISALLOW_ALL_BUILTIN, DOMAINS
from .synth import _enforce_citations

log = logging.getLogger(__name__)

WINDOW_HOURS = 12        # 「这半天」的窗口，搭 8:00/20:00 车
MAX_STORIES = 8          # 每域喂给模型的活动故事上限（按近期活动降序）
MAX_CLAIMS = 6           # 每故事喂的近期宣称上限

SECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string", "description": "一句综述，中立、具体"},
            "claim_ids": {"type": "array", "items": {"type": "integer"},
                          "description": "支撑这句的 claim id（≥1，必须出自给定列表）"},
        }, "required": ["text", "claim_ids"]}},
        "theme": {"type": "string",
                  "description": "一句话点出这半天本域的共同主题；无新事件时说清"
                                 "是哪条推进、或为何没有"},
        "lead_story_id": {"type": "integer",
                          "description": "最能代表本域头条的故事 id（必须来自给定故事）"},
    },
    "required": ["text", "theme"],
}

SECTION_PROMPT = """你是情报系统的板块综述器。给你一个板块（如「政治」）近 12 小时
有活动的故事，每个故事带标题与本半天新增的宣称（每条带 id、立场、来源）。你必须
调用 submit_digest 工具一次性提交，除此之外不做任何事。

规则：
- 写的是**这半天这个板块发生了什么、共同主题是什么** —— 不是复述某一条故事的
  摘要，也不是把几条标题串起来。要跨故事看出主线（例：「今天的动向都指向同一
  件事：欧洲各国在把临时边境措施变成常设安排，法案层面首次出现内阁分裂」）。
- **每句必须在 claim_ids 里注明支撑它的宣称 id**，无引用的句子会被系统直接丢弃。
  只综合给定内容，不引入外部知识，不推测。
- 2-4 句，紧凑。来源之间有分歧时呈现分歧，不裁决谁对。
- **如果系统告诉你本域近 12h 无新增宣称，必须如实说** —— 例「今天没有新事件，
  只有一条推进：……」或「本域今日无新动向」。绝不拿旧闻充数、绝不编造进展。
  这条是首页可信度的关键。
- theme 一句话概括共同主题。lead_story_id 选最能代表本域头条的那条。"""


@dataclass
class SectionDigest:
    domain: str
    text: list[dict] = field(default_factory=list)     # {text, claim_ids}
    theme: str = ""
    has_new: bool = False
    new_claims: int = 0
    lead_story_id: int | None = None
    model: str = "unknown"
    usage: dict | None = None
    error: str | None = None


@dataclass
class DomainView:
    domain: str
    stories: list[dict] = field(default_factory=list)  # {id, title, importance, recent}
    new_claims: int = 0                                # 近 12h 新增断言数（确定性）


class SectionDigester(Protocol):
    async def digest(self, view: DomainView) -> SectionDigest: ...


class ClaudeSectionDigester:
    """Agent SDK 实现 —— 与 ClaudeSynthesizer 同构：唯一工具强 schema，
    捕获状态 per-call（并发竞态教训）。"""

    def __init__(self, model: str | None = None):
        from claude_agent_sdk import query  # 仅探测依赖可导入
        self._model = model

    @staticmethod
    def _render(v: DomainView) -> str:
        parts = [f"## 板块：{v.domain}",
                 f"（近 {WINDOW_HOURS}h 本域新增宣称 {v.new_claims} 条，"
                 f"活动故事 {len(v.stories)} 个）"]
        if v.new_claims == 0:
            parts.append("**注意：本域近 12h 无新增宣称，必须如实说明，"
                         "不要复述旧闻、不要编造进展。**")
        for s in v.stories:
            parts.append(f"\n### 故事 {s['id']}：{s['title']}"
                         f"（重要度 {s.get('importance')}，本半天新增 "
                         f"{len(s['recent'])} 条）")
            parts += [f"[{c['id']}] {c['text']}（立场 {c['stance']:+d}，源 {c['source']}）"
                      for c in s['recent']]
        if not v.stories:
            parts.append("（本域近 12h 无任何活动故事。）")
        return "\n".join(parts)

    async def digest(self, view: DomainView) -> SectionDigest:
        from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions,
                                      ResultMessage, create_sdk_mcp_server,
                                      query, tool)
        captured: dict = {}

        @tool("submit_digest", "一次性提交板块综述", SECTION_SCHEMA)
        async def submit(args):
            captured.clear()
            captured.update(args)
            return {"content": [{"type": "text", "text": "recorded"}]}

        server = create_sdk_mcp_server(name="sd", version="1.0", tools=[submit])
        options = ClaudeAgentOptions(
            system_prompt=SECTION_PROMPT,
            mcp_servers={"sd": server},
            allowed_tools=["mcp__sd__submit_digest"],
            disallowed_tools=DISALLOW_ALL_BUILTIN,
            model=self._model,
            max_turns=4,
        )
        model, usage, err = self._model or "unknown", None, None
        async for msg in query(prompt=self._render(view), options=options):
            if isinstance(msg, AssistantMessage):
                model = msg.model or model
            elif isinstance(msg, ResultMessage):
                usage = getattr(msg, "usage", None) or {}
                if msg.is_error:
                    err = str(msg.result)[:500]
        if not captured and not err:
            err = "model did not call submit_digest"
        return SectionDigest(
            domain=view.domain,
            text=[x for x in captured.get("text", []) if isinstance(x, dict)],
            theme=captured.get("theme") if isinstance(captured.get("theme"), str) else "",
            lead_story_id=(captured.get("lead_story_id")
                           if isinstance(captured.get("lead_story_id"), int) else None),
            new_claims=view.new_claims,
            has_new=view.new_claims > 0,       # 确定性，模型改不了
            model=model, usage=usage, error=err)


# ── 选取输入 ────────────────────────────────────────────────

def _domain_view(conn: psycopg.Connection, domain: str,
                 hours: int = WINDOW_HOURS) -> DomainView:
    """一个域近 hours 有活动的故事（primary 域 = domains[1]），带各自近期宣称。
    活动 = 近 hours 内有新增 claim 或新增 doc。"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.id, s.title, s.importance,
                   (SELECT count(*) FROM claims c
                    WHERE c.story_id=s.id AND c.extracted_at > now()-make_interval(hours=>%s)),
                   (SELECT count(*) FROM story_documents sd
                    WHERE sd.story_id=s.id AND sd.added_at > now()-make_interval(hours=>%s))
            FROM stories s
            WHERE s.state='active' AND s.domains[1]=%s
            ORDER BY 4 DESC, s.importance DESC NULLS LAST
            LIMIT %s""", (hours, hours, domain, MAX_STORIES))
        rows = [r for r in cur.fetchall() if (r[3] or 0) > 0 or (r[4] or 0) > 0]

        stories, new_total = [], 0
        for sid, title, imp, rc, _rd in rows:
            new_total += rc or 0
            cur.execute("""
                SELECT c.id, c.text, coalesce(c.stance,0), src.key
                FROM claims c
                JOIN documents d ON d.id=c.document_id
                JOIN sources src ON src.id=d.source_id
                WHERE c.story_id=%s AND c.extracted_at > now()-make_interval(hours=>%s)
                ORDER BY c.extracted_at DESC, c.id
                LIMIT %s""", (sid, hours, MAX_CLAIMS))
            recent = [{"id": r[0], "text": r[1], "stance": r[2], "source": r[3]}
                      for r in cur.fetchall()]
            stories.append({"id": sid, "title": title, "importance": imp,
                            "recent": recent})
    return DomainView(domain=domain, stories=stories, new_claims=new_total)


# ── 单域产出（测试与生产共用同一逻辑）────────────────────────

EMPTY_THEME = "今日无新动向"


async def digest_domain(view: DomainView,
                        digester: SectionDigester) -> SectionDigest:
    """一个域的综述。近 12h 无新增断言时**不调模型**，直接返回确定性 canned ——
    valid_ids 为空会让引用校验丢掉每一句（含那句「没有新事件」），所以「无新事件」
    这个状态由代码保证，模型碰都不碰。有新增断言时才调模型并套引用校验。"""
    if view.new_claims == 0:
        return SectionDigest(domain=view.domain, text=[], theme=EMPTY_THEME,
                             has_new=False, new_claims=0, model="(canned)")
    res = await digester.digest(view)
    if res.error:
        return res
    valid = {c["id"] for s in view.stories for c in s["recent"]}
    res.text, _drop = _enforce_citations(res.text, valid, ("text",))
    if res.lead_story_id not in {s["id"] for s in view.stories}:
        res.lead_story_id = None
    return res


# ── orchestrator ────────────────────────────────────────────

async def run_section_digests(conn: psycopg.Connection,
                              digester: SectionDigester) -> dict:
    """六个域各生成一段综述，覆盖写入 section_digests。审计不单列（覆盖式产物）。"""
    stats = {"domains": 0, "sentences": 0, "empty": 0, "errors": 0}
    for domain in DOMAINS:
        view = _domain_view(conn, domain)
        res = await digest_domain(view, digester)
        if res.error:
            stats["errors"] += 1
            log.warning("section %s: digest error: %s", domain, res.error)
            continue
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO section_digests
                    (domain, text, theme, has_new, new_claims, lead_story_id, generated_at)
                VALUES (%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (domain) DO UPDATE SET
                    text=EXCLUDED.text, theme=EXCLUDED.theme, has_new=EXCLUDED.has_new,
                    new_claims=EXCLUDED.new_claims, lead_story_id=EXCLUDED.lead_story_id,
                    generated_at=now()""",
                (domain, psycopg.types.json.Jsonb(res.text), res.theme, res.has_new,
                 res.new_claims, res.lead_story_id))
        conn.commit()
        stats["domains"] += 1
        stats["sentences"] += len(res.text)
        if not res.has_new:
            stats["empty"] += 1
        log.info("section %s: %d sentences, has_new=%s (%d new claims)",
                 view.domain, len(res.text), res.has_new, res.new_claims)
    return stats
