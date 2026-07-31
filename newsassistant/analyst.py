"""态势图（picture）—— 管线之上的分析员层。

管道各阶段是自下而上的整理（文档→断言→故事→摘要）；这一层是自上而下的
解释：读取近 48h 的聚合素材，组织成少数几个"剧场"（theater），给出张力、
动量、跨剧场连线、署名观点与对昨日观点的复盘。

两类句子，两套规则（对 synthesis"句句必须引用"铁律的受控扩展）：
  - 事实性叙述：evidence_claim_ids 必须指向素材里的真实 claim
  - 观点：必须有 reasoning + confidence + falsifier，明确标注为分析员判断，
    并在次日的 revisions 里被复盘 —— 观点可以错，但必须可追责
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Protocol

import psycopg

log = logging.getLogger(__name__)

MAX_SUBSTRATE_CHARS = 60_000
STORY_LIMIT = 24
CLAIMS_PER_STORY = 10

_VIZ_GUIDE = """   - viz：挑最能表达该剧场的形式，数据只能来自素材，不得编造数值：
     · map —— 地理性剧场（冲突、打击、灾害、航道）。markers 给经纬度+kind
       （strike/disaster/chokepoint/event）；arcs 画流向/打击线（a→b 经纬度），
       弧线两端尽量落在 markers 里的点上（发射地/目标都值得成为 marker），
       且必须给 label 说明这条线是什么。经纬度用常识坐标，一位小数即可
     · network —— 关系性剧场（阵营、施压、供应、资金）。nodes + edges，
       edge kind 从 conflict/alliance/pressure/supply/funding 里选
     · causal —— 传导链（"A→B→C 杀估值"这类）。nodes 是环节名，
       links 给 from/to/sign（+ 放大 / - 抑制）
     · timeline（演进）/ matrix（立场分歧：行=阵营，列=议题）/ list（并列信号）
     · 没有合适的就用 none。整份 picture 的 viz 类型不要单一化 ——
       地图、网络、传导链正是你比新闻列表强的地方"""

ANALYST_PROMPT = """你是这套公共信息系统的首席分析员。你的读者只有一个人：系统的主人。
他不要新闻列表 —— 他要一张 picture：世界现在处于什么状态、哪里的张力在积累、
什么在加速、哪些看似无关的事其实相连、共识可能错在哪。

你会收到近 48 小时的聚合素材（故事、断言、来源、实体热度）和你昨天的观点清单。
通过 submit_picture 工具一次性提交完整态势图。要求：

1. **剧场（theaters）3–6 个**：把素材组织成少数活跃剧场，不是罗列故事。每个剧场：
   - tension 1–5（张力）与 momentum（rising/holding/falling）
   - narrative：两三句话讲清态势。事实必须来自素材，把支撑的 claim id 放进
     evidence_claim_ids（伪造 id 的剧场会被整个丢弃）
{viz_guide}
   - links：与其他剧场的因果/传导连线，写清机制（"A 推高油价 → B 通胀预期"）
2. **观点（opinions）2–5 条**：这是你存在的意义。敢下判断：什么被高估、什么被
   低估、什么正在被忽视、接下来最可能发生什么。每条必须有 reasoning（推理链）、
   confidence（low/medium/high）、falsifier（什么发生会证明你错了）。
3. **复盘（revisions）**：对照昨日观点逐条判定 confirmed/refuted/open 并说明。
   没有昨日观点时给空数组。被打脸就认，这是你和嘴炮的区别。
4. **overview**：开篇一段话，今天的世界一句话是什么状态。

语言：中文。语气：专业分析员对唯一客户 —— 直接、具体、有立场，不打官腔。
不要用 markdown 记号（** 等），输出是纯文本渲染。""".format(viz_guide=_VIZ_GUIDE)

MARKETS_PROMPT = """你是这套信息系统的市场分析员（desk analyst）。你的读者只有一个人：
系统的主人。他要的不是财经新闻摘要，而是一份 desk note：同一批世界新闻，
从"这对资产价格意味着什么"的维度重新组织。

你会收到近 48 小时的聚合素材（故事、断言、实体热度、监管与备案文件）和你昨天的
观点清单。通过 submit_picture 工具一次性提交。结构复用态势图，但语义是市场的：

1. **主题（theaters）3–6 个**：按市场逻辑组织（利率与久期、能源与航运、
   AI 资本开支链、防务与军工、避险与汇率……视素材而定），不按新闻分类。每个主题：
   - tension = 对市场的重要度 1–5；momentum = 定价压力方向（rising 在升温）
   - narrative：讲清传导机制 —— 什么事件、通过什么通道、作用到什么资产。
     事实放 evidence_claim_ids（伪造 id 整个主题丢弃）
{viz_guide}
     · 市场主题额外优先考虑：causal（事件→通道→资产的传导链）、
       matrix（行=板块/资产，列=方向/机制/观察点）
   - links：主题间的传导（"能源溢价 → 通胀预期 → 久期压力"）
2. **观点（opinions）2–5 条**：哪些定价错了、哪些共识过度、接下来最重要的
   单一变量是什么。reasoning + confidence + falsifier 缺一不可。
3. **复盘（revisions）**：对照昨日观点逐条 confirmed/refuted/open。
4. **overview**：今天市场的一句话状态。

铁律：你做的是信息与机制分析 —— 指出传导路径、错误定价、观察点与触发条件。
**绝不给出买卖建议**（不说"应该买入/卖出/加仓"），不做收益承诺。
语言：中文。不用 markdown 记号。""".format(viz_guide=_VIZ_GUIDE)

DESKS: dict[str, str] = {
    "general": ANALYST_PROMPT,
    "markets": MARKETS_PROMPT,
}

PICTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "theaters": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"},
            "tension": {"type": "integer", "minimum": 1, "maximum": 5},
            "momentum": {"type": "string", "enum": ["rising", "holding", "falling"]},
            "narrative": {"type": "string"},
            "evidence_claim_ids": {"type": "array", "items": {"type": "integer"}},
            "viz": {"type": "object", "properties": {
                "type": {"type": "string",
                         "enum": ["timeline", "matrix", "list",
                                  "map", "network", "causal", "none"]},
                "title": {"type": "string"},
                "events": {"type": "array", "items": {"type": "object",
                    "properties": {"when": {"type": "string"},
                                   "what": {"type": "string"}},
                    "required": ["when", "what"]}},
                "rows": {"type": "array", "items": {"type": "string"}},
                "cols": {"type": "array", "items": {"type": "string"}},
                "cells": {"type": "array", "items":
                          {"type": "array", "items": {"type": "string"}}},
                "items": {"type": "array", "items": {"type": "string"}},
                "markers": {"type": "array", "items": {"type": "object",
                    "properties": {
                        "lat": {"type": "number"}, "lon": {"type": "number"},
                        "label": {"type": "string"},
                        "kind": {"type": "string",
                                 "enum": ["strike", "disaster",
                                          "chokepoint", "event"]},
                        "note": {"type": "string"}},
                    "required": ["lat", "lon", "label", "kind"]}},
                "arcs": {"type": "array", "items": {"type": "object",
                    "properties": {
                        "a_lat": {"type": "number"}, "a_lon": {"type": "number"},
                        "b_lat": {"type": "number"}, "b_lon": {"type": "number"},
                        "label": {"type": "string"}},
                    "required": ["a_lat", "a_lon", "b_lat", "b_lon"]}},
                "nodes": {"type": "array", "items": {"type": "object",
                    "properties": {"id": {"type": "string"},
                                   "kind": {"type": "string"}},
                    "required": ["id"]}},
                "edges": {"type": "array", "items": {"type": "object",
                    "properties": {
                        "a": {"type": "string"}, "b": {"type": "string"},
                        "kind": {"type": "string",
                                 "enum": ["conflict", "alliance", "pressure",
                                          "supply", "funding"]},
                        "label": {"type": "string"}},
                    "required": ["a", "b", "kind"]}},
                "links": {"type": "array", "items": {"type": "object",
                    "properties": {
                        "from": {"type": "string"}, "to": {"type": "string"},
                        "sign": {"type": "string", "enum": ["+", "-"]},
                        "label": {"type": "string"}},
                    "required": ["from", "to", "sign"]}},
            }, "required": ["type"]},
            "links": {"type": "array", "items": {"type": "object", "properties": {
                "to": {"type": "string"}, "why": {"type": "string"}},
                "required": ["to", "why"]}},
        }, "required": ["name", "tension", "momentum", "narrative",
                        "evidence_claim_ids", "viz"]}},
        "opinions": {"type": "array", "items": {"type": "object", "properties": {
            "statement": {"type": "string"},
            "reasoning": {"type": "string"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "falsifier": {"type": "string"},
            "evidence_claim_ids": {"type": "array", "items": {"type": "integer"}},
        }, "required": ["statement", "reasoning", "confidence", "falsifier"]}},
        "revisions": {"type": "array", "items": {"type": "object", "properties": {
            "prior": {"type": "string"},
            "verdict": {"type": "string", "enum": ["confirmed", "refuted", "open"]},
            "note": {"type": "string"}},
            "required": ["prior", "verdict", "note"]}},
    },
    "required": ["overview", "theaters", "opinions", "revisions"],
}


@dataclass
class PictureResult:
    payload: dict | None = None
    model: str = "unknown"
    usage: dict | None = None
    error: str | None = None


class Analyst(Protocol):
    async def compose(self, desk: str, substrate: dict,
                      prev_opinions: list[dict]) -> PictureResult: ...


class ClaudeAnalyst:
    def __init__(self, model: str | None = None):
        from claude_agent_sdk import query   # 仅探测依赖可导入
        self._model = model

    async def compose(self, desk: str, substrate: dict,
                      prev_opinions: list[dict]) -> PictureResult:
        from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions,
                                      ResultMessage, create_sdk_mcp_server,
                                      query, tool)
        from .llm_extract import DISALLOW_ALL_BUILTIN
        captured: dict = {}

        @tool("submit_picture", "一次性提交完整态势图", PICTURE_SCHEMA)
        async def submit(args):
            captured.clear()
            captured.update(args)
            return {"content": [{"type": "text", "text": "recorded"}]}

        server = create_sdk_mcp_server(name="picture", version="1.0",
                                       tools=[submit])
        options = ClaudeAgentOptions(
            system_prompt=DESKS[desk],
            mcp_servers={"pc": server},
            allowed_tools=["mcp__pc__submit_picture"],
            disallowed_tools=DISALLOW_ALL_BUILTIN,
            model=self._model,
            max_turns=8,
        )
        prompt = (
            "=== 近 48 小时素材 ===\n"
            + json.dumps(substrate, ensure_ascii=False)[:MAX_SUBSTRATE_CHARS]
            + "\n\n=== 你昨日的观点（逐条复盘进 revisions）===\n"
            + (json.dumps(prev_opinions, ensure_ascii=False)
               if prev_opinions else "（无 —— revisions 给空数组）"))
        model, usage, err = self._model or "unknown", None, None
        try:
            async for msg in query(prompt=prompt, options=options):
                if isinstance(msg, AssistantMessage):
                    model = msg.model or model
                elif isinstance(msg, ResultMessage):
                    usage = getattr(msg, "usage", None) or {}
                    if msg.is_error:
                        err = str(msg.result)[:500]
        except Exception as e:
            # 限额窗口/断流等：作为 error 结果返回，审计照落，调度下轮重试
            err = f"{type(e).__name__}: {e}"[:500]
        if not captured and not err:
            err = "model did not call submit_picture"
        return PictureResult(payload=dict(captured) or None, model=model,
                             usage=usage, error=err)


# ── 素材 ────────────────────────────────────────────────────

def _substrate(conn: psycopg.Connection, desk: str = "general"
               ) -> tuple[dict, set[int]]:
    """近 48h 的聚合素材 + 可引用 claim id 全集（引用校验用）。
    markets desk 额外附带一手权威层（tier≤2：联邦公报、8-K 等）的最新条目。"""
    valid_ids: set[int] = set()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.id, s.title, s.scalars, s.summary
            FROM stories s
            WHERE s.state='active' AND s.updated_at > now() - interval '48 hours'
            ORDER BY (s.scalars->>'breadth')::int DESC NULLS LAST,
                     (s.scalars->>'docs')::int DESC NULLS LAST
            LIMIT %s""", (STORY_LIMIT,))
        stories = []
        for sid, title, scalars, summary in cur.fetchall():
            st = {"story_id": sid, "title": title,
                  "sources": (scalars or {}).get("breadth"),
                  "docs": (scalars or {}).get("docs")}
            if summary:
                st["synthesis"] = [x.get("text") for x in summary][:6]
            stories.append(st)
        for st in stories:
            cur.execute("""
                SELECT c.id, c.text, src.key,
                       coalesce(to_char(d.published_at,'MM-DD'), '?')
                FROM claims c
                JOIN documents d ON d.id=c.document_id
                JOIN sources src ON src.id=d.source_id
                WHERE c.story_id=%s
                ORDER BY d.published_at DESC NULLS LAST, c.id DESC
                LIMIT %s""", (st["story_id"], CLAIMS_PER_STORY))
            st["claims"] = [{"id": r[0], "text": r[1], "src": r[2], "at": r[3]}
                            for r in cur.fetchall()]
            valid_ids.update(c["id"] for c in st["claims"])

        # 实体热度变化：今天 vs 昨天的提及量，升温实体是剧场化的线索
        cur.execute("""
            SELECT e.canonical_name,
                   count(*) FILTER (WHERE d.fetched_at > now() - interval '24 hours') AS today,
                   count(*) FILTER (WHERE d.fetched_at <= now() - interval '24 hours') AS yday
            FROM document_entities de
            JOIN documents d ON d.id=de.document_id
            JOIN entities e ON e.id=de.entity_id
            WHERE d.fetched_at > now() - interval '48 hours'
              AND e.merged_into IS NULL
            GROUP BY e.canonical_name
            HAVING count(*) FILTER (WHERE d.fetched_at > now() - interval '24 hours') >= 5
            ORDER BY today DESC LIMIT 30""")
        entities = [{"name": r[0], "today": r[1], "yesterday": r[2]}
                    for r in cur.fetchall()]

        out = {"stories": stories, "rising_entities": entities}
        if desk == "markets":
            cur.execute("""
                SELECT src.key, d.title, left(coalesce(d.published_at::text,''),10)
                FROM documents d JOIN sources src ON src.id=d.source_id
                WHERE src.evidence_tier <= 2 AND d.status='ok'
                  AND d.fetched_at > now() - interval '48 hours'
                ORDER BY d.published_at DESC NULLS LAST LIMIT 40""")
            out["primary_filings"] = [
                {"src": r[0], "title": r[1], "at": r[2]} for r in cur.fetchall()]
    return out, valid_ids


def _prev_opinions(conn: psycopg.Connection, desk: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""SELECT payload->'opinions' FROM pictures
                       WHERE desk=%s ORDER BY at DESC LIMIT 1""", (desk,))
        r = cur.fetchone()
    return list(r[0]) if r and r[0] else []


# ── orchestrator ────────────────────────────────────────────

async def run_picture(conn: psycopg.Connection, analyst: Analyst,
                      desk: str = "general") -> dict:
    if desk not in DESKS:
        raise ValueError(f"unknown desk {desk!r} (have: {sorted(DESKS)})")
    substrate, valid_ids = _substrate(conn, desk)
    if not substrate["stories"]:
        return {"pictures": 0, "skipped": "no active stories in window"}
    prev = _prev_opinions(conn, desk)
    res = await analyst.compose(desk, substrate, prev)

    with conn.cursor() as cur:
        cur.execute("""INSERT INTO llm_calls (purpose, model, input, output)
                       VALUES ('picture',%s,%s,%s)""",
                    (res.model,
                     psycopg.types.json.Json({
                         "desk": desk,
                         "stories": [s["story_id"] for s in substrate["stories"]],
                         "prev_opinions": len(prev)}),
                     psycopg.types.json.Json({
                         "payload": res.payload, "usage": res.usage,
                         "error": res.error})))
        if res.error or not res.payload:
            conn.commit()
            log.warning("picture[%s]: %s", desk, res.error)
            return {"pictures": 0, "errors": 1}

        # 引用校验：伪造 claim id 的剧场整个丢弃（对观点仅剔除坏 id，不弃条 ——
        # 观点的可信度由 reasoning/falsifier 承担，不靠引用背书）
        payload = res.payload
        theaters, dropped = [], 0
        for t in payload.get("theaters", []):
            ids = [i for i in t.get("evidence_claim_ids", [])
                   if isinstance(i, int)]
            if ids and set(ids) <= valid_ids:
                theaters.append(t)
            else:
                dropped += 1
        for op in payload.get("opinions", []):
            op["evidence_claim_ids"] = [
                i for i in op.get("evidence_claim_ids", [])
                if isinstance(i, int) and i in valid_ids]
        payload["theaters"] = theaters

        cur.execute("INSERT INTO pictures (desk, model, payload) VALUES (%s,%s,%s)",
                    (desk, res.model, psycopg.types.json.Jsonb(payload)))
    conn.commit()
    log.info("picture[%s]: %d theaters (%d dropped), %d opinions, %d revisions",
             desk, len(theaters), dropped, len(payload.get("opinions", [])),
             len(payload.get("revisions", [])))
    return {"pictures": 1, "theaters": len(theaters),
            "dropped_theaters": dropped,
            "opinions": len(payload.get("opinions", []))}


async def run_all_desks(conn: psycopg.Connection, analyst: Analyst) -> dict:
    out: dict = {}
    for desk in DESKS:
        st = await run_picture(conn, analyst, desk)
        for k, v in st.items():
            if isinstance(v, int):
                out[k] = out.get(k, 0) + v
    return out
