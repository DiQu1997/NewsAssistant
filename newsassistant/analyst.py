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
4. **外围信号（periphery）3–5 条**：素材里有专门的外围区（periphery_*：
   单源但来自政府/遥测等高证据层的故事、首次出现的新实体）。热点人人会看，
   你的增量价值在外围 —— 挑出现在不热、但结构上可能有意义的信号：
   为什么值得盯、什么情况下它会升级成主线。宁可挑错，不可全部给热点回声。
5. **overview**：开篇一段话，今天的世界一句话是什么状态。

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
        "periphery": {"type": "array", "items": {"type": "object", "properties": {
            "signal": {"type": "string"},
            "why": {"type": "string"},
            "escalation": {"type": "string"},
            "story_id": {"type": "integer"}},
            "required": ["signal", "why", "escalation"]}},
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

        # 外围信号（反茧房）：热度排序会系统性放大热点。这里逆着热度采样 ——
        # 单源但来自高证据层的（政府/遥测/备案），以及首次出现即有一定
        # 提及量的新实体（新角色入场往往先于事件成为热点）
        cur.execute("""
            SELECT s.id, s.title, src.key, src.evidence_tier
            FROM stories s
            JOIN story_documents sd ON sd.story_id=s.id
            JOIN documents d ON d.id=sd.document_id
            JOIN sources src ON src.id=d.source_id
            WHERE s.state='active' AND s.updated_at > now() - interval '48 hours'
              AND coalesce((s.scalars->>'breadth')::int, 1) = 1
              AND src.evidence_tier <= 3
            GROUP BY s.id, src.key, src.evidence_tier
            ORDER BY src.evidence_tier, s.updated_at DESC LIMIT 14""")
        quiet = [{"story_id": r[0], "title": r[1], "src": r[2], "tier": r[3]}
                 for r in cur.fetchall()]
        cur.execute("""
            SELECT e.canonical_name, count(*) AS mentions
            FROM entities e
            JOIN document_entities de ON de.entity_id=e.id
            JOIN documents d ON d.id=de.document_id
            WHERE e.created_at > now() - interval '24 hours'
              AND e.merged_into IS NULL
              AND d.fetched_at > now() - interval '24 hours'
            GROUP BY e.canonical_name
            HAVING count(*) >= 3 ORDER BY count(*) DESC LIMIT 15""")
        novel = [{"name": r[0], "mentions": r[1]} for r in cur.fetchall()]

        out = {"stories": stories, "rising_entities": entities,
               "periphery_quiet_authoritative": quiet,
               "periphery_novel_entities": novel}
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


# ── 收盘复盘（每日，收盘后锚定） ────────────────────────────

WRAP_PROMPT = """你是客户的收盘分析员。美股刚收盘，给他写当日复盘与前瞻。
你会收到：全部关注标的的技术面/期权面快照与当日触发信号、市场宽度（今日 vs 昨日）、
当日相关新闻故事（带断言）、以及你昨天的前瞻（逐条复盘）。
通过 submit_wrap 一次性提交。

**写作铁律（违反即废稿）**：
- 客户有实时仪表盘，每个标的的每项指标他都看得到。**禁止巡检式罗列** ——
  "X 收 N 涨 n%、RSI r、MACD 金叉、成交 v 倍"这种把标的挨个念一遍的句式
  是仪表盘的语音版，出现即失败。不重要的票一个字都不要提。
- 你的全部价值是**判断与解释**：今天真正发生的是哪一两件事、为什么、
  意味着什么、接下来看什么。
- 一个论点最多引用一两个关键数字，且必须服务论证（"IV 与 HV 差 14 个点，
  说明卖波者没为下周的数据密度定价"——数字是论据；"IV 24.86%、HV 38.61%"
  ——这是念表，不许）。

结构：
- headline：一句话给今天定调（说人话，有态度）
- beats：当日复盘写成 **3-5 个论点**。每个 beat：title 是论点本身（像报纸
  小标题，"权重股的内战抵消成了指数的假平静"），text 是 3-5 句论证。
  合在一起要讲完今天的完整故事，而不是覆盖所有标的
- drivers：事件 → 价格的因果对（新闻里的事 → 哪些资产怎么反应 → 机制）
- signals_review：只写**今天发生变化**的结构（新信号/消失的信号/关键位攻防
  结果），≤3 个观察，每个说清含义，不做指标清单
- outlook_tomorrow：focus（一句话主线）、key_levels（具体点位攻防及其含义）、
  watch（开盘前后要盯的事）
- outlook_week / outlook_month：结构性判断 —— 事件日历、周期位置、
  你认为市场当前定价错在哪
- risks：此刻最大的 2-4 个风险，具体化
- revisions：对照你昨日的前瞻逐条判 confirmed/refuted/open。没有则给空数组。

信息与机制分析，不给买卖建议。中文，不用 markdown 记号，语气像给唯一客户写的
收盘 note —— 直接、具体、敢下判断。"""

WRAP_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "beats": {"type": "array", "minItems": 3, "maxItems": 5,
                  "items": {"type": "object", "properties": {
                      "title": {"type": "string"}, "text": {"type": "string"}},
                      "required": ["title", "text"]}},
        "drivers": {"type": "array", "items": {"type": "object", "properties": {
            "event": {"type": "string"}, "impact": {"type": "string"}},
            "required": ["event", "impact"]}},
        "signals_review": {"type": "string"},
        "outlook_tomorrow": {"type": "object", "properties": {
            "focus": {"type": "string"},
            "key_levels": {"type": "array", "items": {"type": "string"}},
            "watch": {"type": "array", "items": {"type": "string"}}},
            "required": ["focus", "key_levels", "watch"]},
        "outlook_week": {"type": "string"},
        "outlook_month": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "revisions": {"type": "array", "items": {"type": "object", "properties": {
            "prior": {"type": "string"},
            "verdict": {"type": "string", "enum": ["confirmed", "refuted", "open"]},
            "note": {"type": "string"}},
            "required": ["prior", "verdict", "note"]}},
    },
    "required": ["headline", "beats", "drivers", "signals_review",
                 "outlook_tomorrow", "outlook_week", "outlook_month",
                 "risks", "revisions"],
}


def _wrap_substrate(conn: psycopg.Connection) -> dict | None:
    """收盘素材：行情快照全集 + 宽度今昨对比 + 当日新闻。
    最新 SPY bar 不是新交易日数据时返回 None（周末/休市）。"""
    from datetime import date
    with conn.cursor() as cur:
        cur.execute("SELECT max(day) FROM market_bars WHERE symbol='SPY'")
        last_bar = cur.fetchone()[0]
        if last_bar is None or (date.today() - last_bar).days > 1:
            return None

        cur.execute("""
            SELECT DISTINCT ON (symbol) symbol, payload
            FROM market_snapshots WHERE symbol != '_MARKET'
            ORDER BY symbol, at DESC""")
        symbols = {}
        for sym, p in cur.fetchall():
            ind, near = p.get("indicators", {}), (p.get("options") or {}).get("near") or {}
            symbols[sym] = {
                "close": ind.get("close"), "ret_1d": ind.get("ret_1d"),
                "ret_21d": ind.get("ret_21d"), "rsi": ind.get("rsi"),
                "score": ind.get("score"), "rs_21d": ind.get("rs_21d"),
                "hv20": ind.get("hv20"), "vol_ratio": ind.get("vol_ratio"),
                "levels": ind.get("levels"), "divergence": ind.get("divergence"),
                "signals": [s.get("note") for s in p.get("signals", [])],
                "atm_iv": near.get("atm_iv"), "pc_oi": near.get("pc_oi"),
                "skew": near.get("skew"), "max_pain": near.get("max_pain"),
                "exp_move_pct": near.get("exp_move_pct"),
                "term_slope": (p.get("options") or {}).get("term_slope"),
            }
        cur.execute("""SELECT payload, at FROM market_snapshots
                       WHERE symbol='_MARKET' ORDER BY at DESC LIMIT 2""")
        rows = cur.fetchall()
        breadth_now = rows[0][0] if rows else None
        breadth_prev = rows[1][0] if len(rows) > 1 else None

        cur.execute("""
            SELECT s.id, s.title, s.scalars
            FROM stories s
            WHERE s.state='active' AND s.updated_at > now() - interval '24 hours'
            ORDER BY (s.scalars->>'breadth')::int DESC NULLS LAST LIMIT 15""")
        stories = []
        for sid, title, scalars in cur.fetchall():
            st = {"story_id": sid, "title": title,
                  "sources": (scalars or {}).get("breadth")}
            cur2 = conn.cursor()
            cur2.execute("""
                SELECT c.text FROM claims c
                JOIN documents d ON d.id=c.document_id
                WHERE c.story_id=%s ORDER BY d.published_at DESC NULLS LAST
                LIMIT 5""", (sid,))
            st["claims"] = [r[0] for r in cur2.fetchall()]
            stories.append(st)
    return {"as_of": str(last_bar), "symbols": symbols,
            "breadth_today": breadth_now, "breadth_prev": breadth_prev,
            "news_today": stories}


async def run_wrap(conn: psycopg.Connection, model: str | None = None) -> dict:
    from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions,
                                  ResultMessage, create_sdk_mcp_server,
                                  query, tool)
    from .llm_extract import DISALLOW_ALL_BUILTIN

    substrate = _wrap_substrate(conn)
    if substrate is None:
        return {"wraps": 0, "skipped": "no fresh trading day (weekend/holiday)"}
    with conn.cursor() as cur:
        cur.execute("""SELECT payload FROM pictures WHERE desk='wrap'
                       ORDER BY at DESC LIMIT 1""")
        r = cur.fetchone()
    prev = None
    if r:
        prev = {k: r[0].get(k) for k in
                ("outlook_tomorrow", "outlook_week", "outlook_month", "risks")}

    captured: dict = {}

    @tool("submit_wrap", "一次性提交收盘复盘", WRAP_SCHEMA)
    async def submit(args):
        captured.clear()
        captured.update(args)
        return {"content": [{"type": "text", "text": "recorded"}]}

    server = create_sdk_mcp_server(name="wrap", version="1.0", tools=[submit])
    options = ClaudeAgentOptions(
        system_prompt=WRAP_PROMPT,
        mcp_servers={"wr": server},
        allowed_tools=["mcp__wr__submit_wrap"],
        disallowed_tools=DISALLOW_ALL_BUILTIN,
        model=model, max_turns=6)

    prompt = ("=== 收盘素材 ===\n"
              + json.dumps(substrate, ensure_ascii=False)[:70_000]
              + "\n\n=== 你昨日的前瞻（逐条复盘进 revisions）===\n"
              + (json.dumps(prev, ensure_ascii=False)
                 if prev else "（无 —— revisions 给空数组）"))
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
    if not captured and not err:
        err = "model did not call submit_wrap"

    with conn.cursor() as cur:
        cur.execute("""INSERT INTO llm_calls (purpose, model, input, output)
                       VALUES ('wrap',%s,%s,%s)""",
                    (mdl, psycopg.types.json.Json({"as_of": substrate["as_of"]}),
                     psycopg.types.json.Json({"payload": dict(captured) or None,
                                              "usage": usage, "error": err})))
        if err:
            conn.commit()
            log.warning("wrap: %s", err)
            return {"wraps": 0, "errors": 1}
        payload = dict(captured)
        payload["as_of"] = substrate["as_of"]
        cur.execute("INSERT INTO pictures (desk, model, payload) VALUES ('wrap',%s,%s)",
                    (mdl, psycopg.types.json.Jsonb(payload)))
    conn.commit()
    log.info("wrap: done (%s)", substrate["as_of"])
    return {"wraps": 1}


# ── 故事级深度报告（按需） ──────────────────────────────────

REPORT_PROMPT = """你是首席分析员。客户点开了一个故事，要一份专业的深度报告。
你会收到该故事的全部素材：断言（带来源与日期）、已有综述、时间线。
通过 submit_report 工具一次性提交。要求：

- background：这件事的来龙去脉与结构性成因 —— 不是复述新闻，是解释"为什么会走到这一步"
- situation：当前态势的本质判断，一段话
- parties：主要各方，各自的立场与真实利益（立场是说的，利益是图的，分开写）
- implications：传导与影响 —— 这件事正在改变什么（市场/地缘/产业），机制写清
- scenarios：2-4 个情景推演，各给触发条件与可能性（low/medium/high）
- watch：接下来最值得盯的 3-5 个具体信号

事实基于素材；判断是你的署名观点，敢下结论。中文，不用 markdown 记号。"""

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "background": {"type": "string"},
        "situation": {"type": "string"},
        "parties": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "position": {"type": "string"},
            "interest": {"type": "string"}},
            "required": ["name", "position", "interest"]}},
        "implications": {"type": "string"},
        "scenarios": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "trigger": {"type": "string"},
            "likelihood": {"type": "string", "enum": ["low", "medium", "high"]}},
            "required": ["name", "trigger", "likelihood"]}},
        "watch": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["background", "situation", "parties", "implications",
                 "scenarios", "watch"],
}


async def run_story_report(conn: psycopg.Connection, story_id: int,
                           model: str | None = None) -> dict:
    from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions,
                                  ResultMessage, create_sdk_mcp_server,
                                  query, tool)
    from .llm_extract import DISALLOW_ALL_BUILTIN

    with conn.cursor() as cur:
        cur.execute("""SELECT title, summary, timeline FROM stories WHERE id=%s""",
                    (story_id,))
        row = cur.fetchone()
        if not row:
            return {"error": f"story {story_id} not found"}
        title, summary, timeline = row
        cur.execute("""
            SELECT c.text, src.key, coalesce(to_char(d.published_at,'MM-DD'),'?')
            FROM claims c
            JOIN documents d ON d.id=c.document_id
            JOIN sources src ON src.id=d.source_id
            WHERE c.story_id=%s ORDER BY d.published_at NULLS LAST, c.id
            LIMIT 120""", (story_id,))
        claims = [{"text": r[0], "src": r[1], "at": r[2]} for r in cur.fetchall()]

    substrate = {"title": title, "claims": claims,
                 "synthesis": [x.get("text") for x in (summary or [])],
                 "timeline": [{"when": x.get("when"), "what": x.get("what")}
                              for x in (timeline or [])]}

    captured: dict = {}

    @tool("submit_report", "一次性提交深度报告", REPORT_SCHEMA)
    async def submit(args):
        captured.clear()
        captured.update(args)
        return {"content": [{"type": "text", "text": "recorded"}]}

    server = create_sdk_mcp_server(name="report", version="1.0", tools=[submit])
    options = ClaudeAgentOptions(
        system_prompt=REPORT_PROMPT,
        mcp_servers={"rp": server},
        allowed_tools=["mcp__rp__submit_report"],
        disallowed_tools=DISALLOW_ALL_BUILTIN,
        model=model, max_turns=6)

    mdl, usage, err = model or "unknown", None, None
    try:
        async for msg in query(prompt=json.dumps(substrate, ensure_ascii=False)[:80_000],
                               options=options):
            if isinstance(msg, AssistantMessage):
                mdl = msg.model or mdl
            elif isinstance(msg, ResultMessage):
                usage = getattr(msg, "usage", None) or {}
                if msg.is_error:
                    err = str(msg.result)[:500]
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:500]
    if not captured and not err:
        err = "model did not call submit_report"

    with conn.cursor() as cur:
        cur.execute("""INSERT INTO llm_calls (purpose, model, input, output)
                       VALUES ('story_report',%s,%s,%s)""",
                    (mdl, psycopg.types.json.Json({"story_id": story_id}),
                     psycopg.types.json.Json({"payload": dict(captured) or None,
                                              "usage": usage, "error": err})))
        if err:
            conn.commit()
            log.warning("story_report %s: %s", story_id, err)
            return {"error": err}
        cur.execute("""UPDATE stories SET deep_report=%s, deep_report_at=now()
                       WHERE id=%s""",
                    (psycopg.types.json.Jsonb(dict(captured)), story_id))
    conn.commit()
    log.info("story_report %s: done", story_id)
    return {"ok": True}


async def run_all_desks(conn: psycopg.Connection, analyst: Analyst,
                        skip_fresh_hours: int = 20) -> dict:
    """跑全部 desk。当天已出图的 desk 跳过 —— 重试只补失败的那个，
    不重复烧已成功 desk 的额度。"""
    out: dict = {}
    for desk in DESKS:
        with conn.cursor() as cur:
            cur.execute("""SELECT at > now() - make_interval(hours => %s)
                           FROM pictures WHERE desk=%s
                           ORDER BY at DESC LIMIT 1""",
                        (skip_fresh_hours, desk))
            r = cur.fetchone()
        if r and r[0]:
            out["skipped_fresh"] = out.get("skipped_fresh", 0) + 1
            continue
        st = await run_picture(conn, analyst, desk)
        for k, v in st.items():
            if isinstance(v, int):
                out[k] = out.get(k, 0) + v
    return out
