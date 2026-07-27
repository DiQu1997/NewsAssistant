"""实体消歧 —— 与故事归并同构的"确定性召回 + LLM 裁决"（docs/architecture.md §2）。

真实病例（2026-07-27 库内实测）：United Kingdom / UK / Britain 三条记录；
United States 按 kind 分裂成 org 与 place 两条。后果是双重的：
实体倒排召回漏配（漏并），且高频实体的 df 被稀释、逃过 IDF 降权（错并帮凶）。

原则：不硬编码别名映射表 —— 那是主题先验，永远列不全。候选由**结构性**
信号产生（字面归一、首字母缩写模式、词元子集），同一性由 LLM 裁决，
判据落 llm_calls，合并落 merged_into + aliases（append-only，可回滚）。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

import psycopg

log = logging.getLogger(__name__)

RESOLVE_SCHEMA = {
    "type": "object",
    "properties": {
        "pairs": {"type": "array", "items": {"type": "object", "properties": {
            "pair_index": {"type": "integer", "description": "对应输入编号，从 0 开始"},
            "same": {"type": "boolean",
                     "description": "两个名字是否指同一现实实体（含缩写、简称、译名、"
                                    "旧称）。母子公司、机构与其下属、人物与其职位头衔"
                                    "均不算同一实体"},
            "canonical": {"type": "string",
                          "description": "same=true 时：应作为规范名的一个（选更完整正式的）"},
            "reason": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        }, "required": ["pair_index", "same", "reason", "confidence"]}},
    },
    "required": ["pairs"],
}

RESOLVE_PROMPT = """你是实体消歧裁决器。给你若干对实体名（各带类型与出现语境），
你必须调用 submit_resolution 工具一次性提交全部裁决，除此之外不做任何事。

判断标准：
- 同一现实实体的不同表达 → same=true：缩写（UK / United Kingdom）、常用简称
  （Britain / United Kingdom）、带缀变体（U.S. X Department / United States
  Department of X）、同一实体被标了不同类型（国家既标 org 又标 place）。
- **不是**同一实体 → same=false：母公司与子公司（Reuters / Thomson Reuters）、
  人物与其职位（Donald Trump / Trump administration）、机构与其下属单位、
  仅名字相似的不同人/地。
- canonical 选更完整、正式的那个名字。
- 拿不准 → same=false（错合并会污染所有引用它的故事召回）。"""


@dataclass
class Resolution:
    pair_index: int
    same: bool = False
    canonical: str | None = None
    reason: str = ""
    confidence: float = 0.0


@dataclass
class ResolveResult:
    resolutions: list[Resolution] = field(default_factory=list)
    model: str = "unknown"
    usage: dict | None = None
    error: str | None = None


class Resolver(Protocol):
    async def resolve(self, pairs: list[dict]) -> ResolveResult: ...


class ClaudeResolver:
    """Agent SDK 实现，批量提交（同抽取层的底盘摊薄逻辑）。捕获状态 per-call。"""

    def __init__(self, model: str | None = None):
        from claude_agent_sdk import query   # 仅探测依赖可导入
        self._model = model

    async def resolve(self, pairs: list[dict]) -> ResolveResult:
        from claude_agent_sdk import (ClaudeAgentOptions, ResultMessage,
                                      create_sdk_mcp_server, query, tool)
        from .llm_extract import DISALLOW_ALL_BUILTIN
        captured: dict = {}

        @tool("submit_resolution", "一次性提交全部实体对的消歧裁决", RESOLVE_SCHEMA)
        async def submit(args):
            captured.clear()
            captured.update(args)
            return {"content": [{"type": "text", "text": "recorded"}]}

        server = create_sdk_mcp_server(name="resolve", version="1.0", tools=[submit])
        options = ClaudeAgentOptions(
            system_prompt=RESOLVE_PROMPT,
            mcp_servers={"rs": server},
            allowed_tools=["mcp__rs__submit_resolution"],
            disallowed_tools=DISALLOW_ALL_BUILTIN,
            model=self._model,
            max_turns=6,
        )
        prompt = "\n".join(
            f"对 {i}：「{p['a_name']}」[{p['a_kind']}]（语境：{p['a_ctx']}）"
            f" vs 「{p['b_name']}」[{p['b_kind']}]（语境：{p['b_ctx']}）"
            for i, p in enumerate(pairs))
        model, usage, err = self._model or "unknown", None, None
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, ResultMessage):
                model = getattr(msg, "model", None) or model
                usage = getattr(msg, "usage", None) or {}
                if msg.is_error:
                    err = str(msg.result)[:500]
        if not captured and not err:
            err = "model did not call submit_resolution"
        res = [Resolution(**{k: v for k, v in r.items()
                             if k in ("pair_index", "same", "canonical", "reason",
                                      "confidence")})
               for r in captured.get("pairs", []) if isinstance(r, dict)]
        return ResolveResult(resolutions=res, model=model, usage=usage, error=err)


# ── 确定性候选发现 ──────────────────────────────────────────

_PUNCT = re.compile(r"[.’'’,-]")
_STOP = {"the", "of", "for", "and"}


def _norm(name: str) -> str:
    return _PUNCT.sub("", name).casefold().strip()


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"\s+", _norm(name)) if t and t not in _STOP]


def _acronym(name: str) -> str:
    toks = _tokens(name)
    return "".join(t[0] for t in toks) if len(toks) >= 2 else ""


def _fold(src: list[str], ref: list[str]) -> list[str]:
    """把 src 里的短 token 尝试按 ref 的连续词元首字母展开：
    ["us","department"] 对照 ["united","states","department"] → us 展开。"""
    out: list[str] = []
    for t in src:
        expanded = None
        if 2 <= len(t) <= 4:
            for i in range(len(ref)):
                for j in range(i + 2, min(i + 1 + len(t), len(ref)) + 1):
                    if "".join(x[0] for x in ref[i:j]) == t:
                        expanded = ref[i:j]
                        break
                if expanded:
                    break
        out.extend(expanded or [t])
    return out


def is_candidate_pair(a: str, b: str) -> bool:
    """结构性信号：字面归一相同 / 首字母缩写（整名或名内一段）/ 词元子集。
    只产生候选，不做判决 —— Reuters/Thomson Reuters 会进候选，由裁决否掉。"""
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return True
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    if na.replace(" ", "") in (_acronym(b),) or nb.replace(" ", "") in (_acronym(a),):
        return True
    sa, sb = set(_fold(ta, tb)), set(_fold(tb, ta))
    small, big = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    return len(small) >= 1 and small <= big and len(big) - len(small) <= 3


def find_candidate_pairs(conn: psycopg.Connection, limit: int = 40) -> list[dict]:
    """在未合并实体间找候选对。O(n²) 字面比较 —— 实体数在 10^3 量级毫无压力。"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.id, e.canonical_name, e.kind,
                   (SELECT count(*) FROM document_entities de WHERE de.entity_id=e.id),
                   coalesce((SELECT d.title FROM document_entities de
                             JOIN documents d ON d.id=de.document_id
                             WHERE de.entity_id=e.id LIMIT 1), '')
            FROM entities e WHERE e.merged_into IS NULL""")
        ents = cur.fetchall()
    pairs = []
    for i in range(len(ents)):
        for j in range(i + 1, len(ents)):
            a, b = ents[i], ents[j]
            if is_candidate_pair(a[1], b[1]):
                pairs.append({
                    "a_id": a[0], "a_name": a[1], "a_kind": a[2], "a_df": a[3],
                    "a_ctx": a[4][:60],
                    "b_id": b[0], "b_name": b[1], "b_kind": b[2], "b_df": b[3],
                    "b_ctx": b[4][:60]})
                if len(pairs) >= limit:
                    return pairs
    return pairs


# ── orchestrator ────────────────────────────────────────────

async def run_resolution(conn: psycopg.Connection, resolver: Resolver,
                         limit: int = 40) -> dict:
    stats = {"pairs": 0, "merged": 0, "kept": 0, "errors": 0}
    pairs = find_candidate_pairs(conn, limit)
    if not pairs:
        return stats
    res = await resolver.resolve(pairs)

    with conn.cursor() as cur:
        cur.execute("""INSERT INTO llm_calls (purpose, model, input, output)
                       VALUES ('resolve_entity',%s,%s,%s)""",
                    (res.model,
                     psycopg.types.json.Json({"pairs": [
                         {k: p[k] for k in ("a_id", "a_name", "b_id", "b_name")}
                         for p in pairs]}),
                     psycopg.types.json.Json({
                         "resolutions": [vars(r) for r in res.resolutions],
                         "usage": res.usage, "error": res.error})))
        conn.commit()
        if res.error:
            stats["errors"] = 1
            return stats

        for r in res.resolutions:
            if r.pair_index >= len(pairs):
                continue
            stats["pairs"] += 1
            if not r.same or r.confidence < 0.7:
                stats["kept"] += 1
                continue
            p = pairs[r.pair_index]
            # 规范条目：裁决指定的名字；平局取 df 更高者
            if r.canonical and _norm(r.canonical) == _norm(p["b_name"]):
                keep, drop = p["b_id"], p["a_id"]
                keep_name, drop_name = p["b_name"], p["a_name"]
            else:
                keep, drop = p["a_id"], p["b_id"]
                keep_name, drop_name = p["a_name"], p["b_name"]
            # 路径压缩：keep 若已被合并，追到链根；批内先后合并会成链，
            # 而读取端只解析一级（真实病例：UK→UK[place]→UK[org] 两级链）
            seen = set()
            while True:
                cur.execute("SELECT merged_into FROM entities WHERE id=%s", (keep,))
                nxt = cur.fetchone()[0]
                if nxt is None or nxt in seen:
                    break
                seen.add(keep)
                keep = nxt
            if keep == drop:
                stats["kept"] += 1
                continue
            cur.execute("UPDATE entities SET merged_into=%s WHERE id=%s AND merged_into IS NULL",
                        (keep, drop))
            did_merge = cur.rowcount
            # 已指向 drop 的旧合并全部改指新根，保持树高 ≤1
            cur.execute("UPDATE entities SET merged_into=%s WHERE merged_into=%s",
                        (keep, drop))
            if did_merge:
                cur.execute("""UPDATE entities SET aliases =
                               (SELECT array_agg(DISTINCT x) FROM
                                unnest(aliases || %s::text) AS x) WHERE id=%s""",
                            (drop_name, keep))
                # 引用改挂规范条目（document_entities 可能产生重复对，先去重）
                cur.execute("""DELETE FROM document_entities de USING document_entities de2
                               WHERE de.entity_id=%s AND de2.entity_id=%s
                                 AND de.document_id=de2.document_id""", (drop, keep))
                cur.execute("UPDATE document_entities SET entity_id=%s WHERE entity_id=%s",
                            (keep, drop))
                cur.execute("""DELETE FROM story_entities se USING story_entities se2
                               WHERE se.entity_id=%s AND se2.entity_id=%s
                                 AND se.story_id=se2.story_id""", (drop, keep))
                cur.execute("UPDATE story_entities SET entity_id=%s WHERE entity_id=%s",
                            (keep, drop))
                stats["merged"] += 1
                log.info("entity merge: %r ← %r (%s)", keep_name, drop_name,
                         r.reason[:80])
        conn.commit()
    return stats
