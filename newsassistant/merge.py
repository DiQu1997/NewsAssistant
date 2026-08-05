"""L2 归并层 —— 系统的心脏（docs/architecture.md §3，决策 D1）。

归档，不是聚类：
  召回（纯确定性，零 LLM）→ 裁决（Agent SDK 单步，强 schema）→
  event-sourcing 写入（系统必须能回答"为什么这篇归到这个故事"）→
  Story 标量增量维护。

裁决按**IDF 合格实体不相交的波次**批量（D25）：归并是有状态的序贯过程 ——
两篇同故事的新文档若同批裁决，彼此看不见对方刚建的故事，会各建一个重复故事。
但召回本身就是合格实体重叠，**合格实体不相交的两篇文档互相召回不到对方
新建的故事**，同波不存在这个竞态，可以打包进一次 SDK 调用，把 ~8k token 的
会话底盘摊薄到 N 篇（同抽取层 D20）。共享任一合格实体即触发波次冲刷
（先落库再召回），序贯语义完整保留。

无候选的文档直接建新故事，不花 LLM。宁可新建不错并：
错并进故事的文档难以剥离，漏并的两个故事后续还能 merge。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import psycopg

from .config import Config
from .llm_extract import DISALLOW_ALL_BUILTIN

log = logging.getLogger(__name__)

MAX_CANDIDATES = 5
CAND_WINDOW_DAYS = 14      # 只在活跃窗口内召回；旧故事休眠后不再吸收新文档
ASSIGN_BATCH = 6           # 每波最多打包的文档数（合格实体不相交才可同波）

ASSIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {"type": "array", "items": {"type": "object", "properties": {
            "doc_index": {"type": "integer", "description": "对应输入文档编号，从 0 开始"},
            "decision": {"type": "string", "enum": ["existing", "new"]},
            "story_id": {"type": "integer",
                         "description": "decision=existing 时必填："
                                        "该文档自己候选列表中的故事 id"},
            "title": {"type": "string",
                      "description": "decision=new 时必填：新故事的规范标题 —— 中立、具体、"
                                     "描述事件本身而非单篇报道角度"},
            "reason": {"type": "string",
                       "description": "决定性判据，40 字内"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        }, "required": ["doc_index", "decision", "reason", "confidence"]}},
    },
    "required": ["verdicts"],
}

JUDGE_PROMPT = """你是新闻情报系统的归并裁决器。给你若干篇新文档，每篇各带自己的
候选故事列表。**每篇独立裁决**：这些文档彼此无关，不要跨文档比较，也不要
因为几篇同时出现就认为它们属于同一故事。你必须调用 submit_assignment 工具
一次性提交全部文档的裁决（每篇一条，doc_index 对应输入编号），除此之外不做任何事。
decision=existing 时 story_id 只能取**该文档自己**候选列表中的 id。

判断标准：
- 同一个**持续事件或进程**的报道属于同一故事（同一次地震的后续伤亡更新、
  同一项法案的各阶段、同一场谈判的多轮）。
- **仅主题相似不构成同一故事**：两次不同的地震是两个故事；两家公司各自的
  裁员是两个故事。
- 后续报道、更正、回应、分析评论都跟随其针对的事件。
- 拿不准时选 new：错并难修，漏并可以后续合并。
- **共享泛化实体（大国、政府、大型机构、政要）不构成同一故事的证据**；
  判断必须基于事件级的具体判据（具体地点、具体人物、事件名、时间与数字的吻合）。
- **候选故事的标题描述它的核心事件**。新文档必须与该核心事件同属一个进程；
  只与故事后期吸收的边缘内容相关、而与标题核心无关的 → new。
- **多主题简报/摘要类文档**（一篇覆盖多个互不相关事件的 digest/newsletter）
  一律 new，并在 reason 中注明 digest —— 它们会污染任何被并入的故事。
- reason 限 40 字内：只写决定性判据（哪个实体/断言指向同一事件），
  不复述事件全貌 —— 长解释不增加裁决质量，只增加开销。"""


@dataclass
class Verdict:
    decision: str = "new"          # existing | new
    story_id: int | None = None
    title: str | None = None
    reason: str = ""
    confidence: float = 0.0
    model: str = "unknown"
    usage: dict | None = None
    error: str | None = None


@dataclass
class DocView:
    id: int
    title: str | None
    published_at: str | None
    claims: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    salient: list[str] = field(default_factory=list)   # IDF 合格实体（波次判据）


@dataclass
class CandidateView:
    id: int
    title: str
    doc_count: int
    shared_entities: list[str] = field(default_factory=list)
    recent_titles: list[str] = field(default_factory=list)
    recent_claims: list[str] = field(default_factory=list)


BatchItem = tuple[DocView, list[CandidateView]]


class Judge(Protocol):
    async def judge_batch(self, items: list[BatchItem]) -> list[Verdict]: ...


LEAN_RULE = ("\n- 禁止输出任何正文文本（分析、预告、总结都不要）："
             "你的全部输出只能是一次 submit_assignment 工具调用。")


class ClaudeJudge:
    """Agent SDK 实现 —— 与抽取层相同的唯一工具强 schema + 批量摊薄模式。
    捕获状态 per-call 局部（抽取层竞态教训，结构上不留共享态）。

    lean：禁 thinking + 禁正文预演。haiku 默认会先把裁决在 thinking 和
    正文里各演一遍再调工具（实测 7.6K token/波，是裁决本身的 9 倍）；
    sonnet 不需要此开关，天然只调工具。"""

    def __init__(self, model: str | None = None, lean: bool = False):
        from claude_agent_sdk import query   # 仅探测依赖可导入
        self._model = model
        self._lean = lean

    @staticmethod
    def _render(items: list[BatchItem]) -> str:
        parts = []
        for i, (doc, cands) in enumerate(items):
            parts += [f"\n===== 文档 {i}（id {doc.id}） =====",
                      f"标题：{doc.title or '(无)'}",
                      f"发布：{doc.published_at or '(未知)'}",
                      "断言：" + "；".join(doc.claims[:8]),
                      "实体：" + "、".join(doc.entities[:15]),
                      f"\n文档 {i} 的候选故事："]
            for c in cands:
                parts += [f"- 故事 id {c.id}：{c.title}（{c.doc_count} 篇）",
                          "  共享实体：" + "、".join(c.shared_entities[:10]),
                          "  最近文档：" + "；".join(c.recent_titles[:3]),
                          "  最近断言：" + "；".join(c.recent_claims[:5])]
        return "\n".join(parts)

    async def judge_batch(self, items: list[BatchItem]) -> list[Verdict]:
        from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions,
                                      ResultMessage, create_sdk_mcp_server,
                                      query, tool)
        captured: dict = {}                  # per-call，无共享

        @tool("submit_assignment", "一次性提交全部文档的归并裁决", ASSIGN_SCHEMA)
        async def submit(args):
            captured.clear()
            captured.update(args)
            return {"content": [{"type": "text", "text": "recorded"}]}

        server = create_sdk_mcp_server(name="merge", version="1.0", tools=[submit])
        options = ClaudeAgentOptions(
            system_prompt=JUDGE_PROMPT + (LEAN_RULE if self._lean else ""),
            mcp_servers={"mg": server},
            allowed_tools=["mcp__mg__submit_assignment"],
            disallowed_tools=DISALLOW_ALL_BUILTIN,
            model=self._model,
            max_turns=6,
            **({"thinking": {"type": "disabled"}} if self._lean else {}),
        )
        model, usage, err = self._model or "unknown", None, None
        async for msg in query(prompt=self._render(items), options=options):
            if isinstance(msg, AssistantMessage):
                model = msg.model or model   # ResultMessage 无 model 字段，只能从这里拿
            elif isinstance(msg, ResultMessage):
                usage = getattr(msg, "usage", None) or {}
                if msg.is_error:
                    err = str(msg.result)[:500]
        if not captured and not err:
            err = "model did not call submit_assignment"
        got = {v.get("doc_index"): v for v in captured.get("verdicts", [])
               if isinstance(v, dict)}
        out: list[Verdict] = []
        for i, (doc, cands) in enumerate(items):
            # usage 是整批一次调用的量，只挂在第 0 篇上，避免审计表重复计费
            u = usage if i == 0 else None
            c = got.get(i)
            if c is None:
                # 缺席即错误，不默认 new：漏判的文档留待下轮重裁，
                # 而不是凭空多出一个故事
                out.append(Verdict(model=model, usage=u,
                                   error=err or f"doc_index {i} missing in batch"))
                continue
            v = Verdict(decision=c.get("decision", "new"), story_id=c.get("story_id"),
                        title=c.get("title"), reason=c.get("reason", ""),
                        confidence=c.get("confidence", 0.0),
                        model=model, usage=u, error=err)
            # schema 之外的最后防线：existing 必须指向**该文档自己**的候选
            if v.decision == "existing" and v.story_id not in {x.id for x in cands}:
                v.decision, v.error = "new", f"judge chose non-candidate story {v.story_id}"
                v.title = None
            out.append(v)
        return out


# ── 召回（纯确定性） ────────────────────────────────────────

def _unassigned_docs(conn: psycopg.Connection, limit: int) -> list[DocView]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.id, d.title, d.published_at::text
            FROM documents d
            JOIN sources s ON s.id = d.source_id
            WHERE d.status='ok' AND d.extracted_at IS NOT NULL
              AND s.section = 'news'
              AND NOT EXISTS (SELECT 1 FROM story_documents sd WHERE sd.document_id=d.id)
            ORDER BY d.published_at DESC NULLS LAST, d.id DESC LIMIT %s""", (limit,))
        docs = [DocView(id=r[0], title=r[1], published_at=r[2]) for r in cur.fetchall()]
        for d in docs:
            cur.execute("SELECT text FROM claims WHERE document_id=%s ORDER BY id LIMIT 8",
                        (d.id,))
            d.claims = [r[0] for r in cur.fetchall()]
            cur.execute("""SELECT DISTINCT e2.canonical_name FROM document_entities de
                           JOIN entities e ON e.id=de.entity_id
                           JOIN entities e2 ON e2.id=coalesce(e.merged_into, e.id)
                           WHERE de.document_id=%s""", (d.id,))
            d.entities = [r[0] for r in cur.fetchall()]
            # 波次判据只看**能进召回**的实体，和 recall() 用同一套 IDF 过滤：
            # 泛化实体召回不到故事，共享它不构成重复故事竞态，不该逼散波次
            cur.execute("""
                WITH ce AS (SELECT de.document_id,
                                   coalesce(e.merged_into, e.id) AS entity_id
                            FROM document_entities de
                            JOIN entities e ON e.id=de.entity_id),
                     df AS (SELECT entity_id, count(DISTINCT document_id) AS n
                            FROM ce GROUP BY entity_id),
                     tot AS (SELECT count(DISTINCT document_id) AS t FROM ce)
                SELECT DISTINCT e2.canonical_name
                FROM ce JOIN df ON df.entity_id = ce.entity_id
                JOIN tot ON true
                JOIN entities e2 ON e2.id = ce.entity_id
                WHERE ce.document_id = %s
                  AND df.n <= greatest(5, tot.t * 0.05)""", (d.id,))
            d.salient = [r[0] for r in cur.fetchall()]
    return docs


def recall(conn: psycopg.Connection, doc_id: int,
           k: int = MAX_CANDIDATES) -> list[CandidateView]:
    """实体倒排 + 活跃时间窗 → 按 IDF 加权的共享实体分取 top-K。

    IDF 降权（真实事故 story#5 的教训）：United States / Donald Trump 这类
    泛化实体出现在 10% 的文档里，等权计数会让大杂烩故事持续滚雪球。
    出现率 > 5%（且 >5 篇）的实体不参与召回，其余按 1/df 加权 ——
    共享「Bite of Seattle」远比共享「United States」值钱。"""
    with conn.cursor() as cur:
        cur.execute("""
            WITH ce AS (SELECT de.document_id,
                               coalesce(e.merged_into, e.id) AS entity_id
                        FROM document_entities de JOIN entities e ON e.id=de.entity_id),
                 cse AS (SELECT se.story_id,
                                coalesce(e.merged_into, e.id) AS entity_id
                         FROM story_entities se JOIN entities e ON e.id=se.entity_id),
                 df AS (SELECT entity_id, count(DISTINCT document_id) AS n
                        FROM ce GROUP BY entity_id),
                 tot AS (SELECT count(DISTINCT document_id) AS t FROM ce)
            SELECT s.id, s.title, sum(1.0 / df.n) AS score,
                   array_agg(DISTINCT e.canonical_name) AS shared_names
            FROM ce de
            JOIN df ON df.entity_id = de.entity_id
            JOIN tot ON true
            JOIN cse se ON se.entity_id = de.entity_id
            JOIN stories s ON s.id = se.story_id
            JOIN entities e ON e.id = de.entity_id
            WHERE de.document_id = %s AND s.state = 'active'
              AND s.updated_at > now() - make_interval(days => %s)
              AND df.n <= greatest(5, tot.t * 0.05)
            GROUP BY s.id, s.title
            ORDER BY score DESC, s.updated_at DESC
            LIMIT %s""", (doc_id, CAND_WINDOW_DAYS, k))
        cands = [CandidateView(id=r[0], title=r[1], doc_count=0,
                               shared_entities=list(r[3])) for r in cur.fetchall()]
        for c in cands:
            cur.execute("SELECT count(*) FROM story_documents WHERE story_id=%s", (c.id,))
            c.doc_count = cur.fetchone()[0]
            cur.execute("""SELECT d.title FROM documents d
                           JOIN story_documents sd ON sd.document_id=d.id
                           WHERE sd.story_id=%s ORDER BY sd.added_at DESC LIMIT 3""",
                        (c.id,))
            c.recent_titles = [r[0] for r in cur.fetchall() if r[0]]
            cur.execute("""SELECT c2.text FROM claims c2
                           WHERE c2.story_id=%s ORDER BY c2.id DESC LIMIT 5""", (c.id,))
            c.recent_claims = [r[0] for r in cur.fetchall()]
    return cands


# ── 写入（event-sourcing） ──────────────────────────────────

def _attach(cur: psycopg.Cursor, story_id: int, doc: DocView) -> None:
    cur.execute("""INSERT INTO story_documents (story_id, document_id)
                   VALUES (%s,%s) ON CONFLICT DO NOTHING""", (story_id, doc.id))
    cur.execute("""INSERT INTO story_entities (story_id, entity_id)
                   SELECT %s, de.entity_id FROM document_entities de
                   WHERE de.document_id=%s ON CONFLICT DO NOTHING""", (story_id, doc.id))
    cur.execute("UPDATE claims SET story_id=%s WHERE document_id=%s", (story_id, doc.id))
    cur.execute("UPDATE stories SET updated_at=now() WHERE id=%s", (story_id,))


def _create_story(cur: psycopg.Cursor, doc: DocView, title: str, reason: str) -> int:
    cur.execute("INSERT INTO stories (title) VALUES (%s) RETURNING id", (title,))
    sid = cur.fetchone()[0]
    cur.execute("""INSERT INTO story_events (story_id, kind, payload)
                   VALUES (%s,'created',%s)""",
                (sid, psycopg.types.json.Jsonb(
                    {"seed_document": doc.id, "reason": reason})))
    _attach(cur, sid, doc)
    return sid


def _update_scalars(cur: psycopg.Cursor, story_id: int) -> None:
    """增量维护派生标量 —— dashboard 的燃料（docs/architecture.md §2）。
    velocity: 近 3 天 vs 前 3 天文档数变化率
    breadth:  独立信源数（status=ok 的文档的 distinct source；转述溯源判决
              落地后改按 syndication_of 归并计数）
    consensus: claim 立场的一致度 100*(1-std/2)
    """
    cur.execute("""
        WITH d AS (SELECT sd.added_at, doc.source_id
                   FROM story_documents sd JOIN documents doc ON doc.id=sd.document_id
                   WHERE sd.story_id=%s AND doc.status='ok'),
             c AS (SELECT stance FROM claims WHERE story_id=%s AND stance IS NOT NULL)
        SELECT (SELECT count(*) FROM d),
               (SELECT count(DISTINCT source_id) FROM d),
               (SELECT count(*) FROM d WHERE added_at > now() - interval '3 days'),
               (SELECT count(*) FROM d WHERE added_at <= now() - interval '3 days'
                                         AND added_at > now() - interval '6 days'),
               (SELECT coalesce(stddev_pop(stance), 0) FROM c)""",
                (story_id, story_id))
    total, breadth, recent, prev, stance_std = cur.fetchone()
    velocity = round(((recent - prev) / prev * 100) if prev else (100 if recent else 0))
    consensus = round(100 * (1 - min(float(stance_std) / 2, 1)))
    stage = 4 if velocity >= 45 else 3 if velocity >= 16 else 2 if velocity >= -12 else 1
    cur.execute("UPDATE stories SET scalars=%s WHERE id=%s",
                (psycopg.types.json.Jsonb({
                    "docs": total, "breadth": breadth, "velocity": velocity,
                    "consensus": consensus, "stage": stage}), story_id))


# ── orchestrator（实体不相交波次批量，见模块 docstring） ────

def _apply_verdict(conn: psycopg.Connection, doc: DocView,
                   cands: list[CandidateView], v: Verdict, stats: dict) -> None:
    """单篇裁决落库：审计先行（含失败），event-sourcing，标量增量。"""
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO llm_calls (purpose, model, input, output)
                       VALUES ('assign',%s,%s,%s)""",
                    (v.model,
                     psycopg.types.json.Json({
                         "document_id": doc.id,
                         "candidates": [c.id for c in cands]}),
                     psycopg.types.json.Json({
                         "decision": v.decision, "story_id": v.story_id,
                         "title": v.title, "reason": v.reason,
                         "confidence": v.confidence, "usage": v.usage,
                         "error": v.error})))
        if v.error and v.decision != "new":
            conn.commit()
            stats["errors"] += 1
            return
        if v.decision == "existing":
            _attach(cur, v.story_id, doc)
            cur.execute("""INSERT INTO story_events (story_id, kind, payload)
                           VALUES (%s,'absorbed',%s)""",
                        (v.story_id, psycopg.types.json.Jsonb({
                            "document_id": doc.id, "reason": v.reason,
                            "confidence": v.confidence,
                            "candidates_considered": [c.id for c in cands]})))
            _update_scalars(cur, v.story_id)
            stats["absorbed"] += 1
        else:
            sid = _create_story(cur, doc, v.title or doc.title or f"story:{doc.id}",
                                v.reason or "judge: new story")
            _update_scalars(cur, sid)
            stats["new_stories"] += 1
    conn.commit()
    stats["docs"] += 1
    log.info("doc %s → %s%s", doc.id, v.decision,
             f" story {v.story_id}" if v.decision == "existing" else "")


async def _flush_wave(conn: psycopg.Connection, judge: Judge,
                      wave: list[BatchItem], stats: dict) -> None:
    """一波一次 SDK 调用。整批调用失败只记错误，文档留待下轮 —— 不降级为
    逐篇重试：那会把省下来的底盘再吐回去，而下一轮本来就会重新拾起它们。"""
    if not wave:
        return
    try:
        verdicts = await judge.judge_batch(wave)
    except Exception:
        stats["errors"] += len(wave)
        log.exception("assignment wave of %d docs failed", len(wave))
        return
    stats["waves"] += 1
    for (doc, cands), v in zip(wave, verdicts):
        try:
            _apply_verdict(conn, doc, cands, v, stats)
        except Exception:
            conn.rollback()
            stats["errors"] += 1
            log.exception("doc %s assignment write failed", doc.id)


async def run_assignment(conn: psycopg.Connection, cfg: Config, judge: Judge,
                         limit: int = 50, batch_size: int = ASSIGN_BATCH) -> dict:
    """波次批量归并。不变量：共享任一 **IDF 合格**实体的两篇文档绝不同波 ——
    相交即先冲刷再召回，后者因此看得见前者裁决产生的新故事，串行语义不丢。

    判据必须是合格实体而非全部实体：召回把 df 超阈的泛化实体排除在外，
    所以只共享泛化实体的两篇文档互相召回不到对方新建的故事，同波是安全的。
    用全部实体做判据在真实数据上等于没批量 —— 相邻文档几乎总共享几个大
    机构名，实测 24 个波全是单篇，底盘一点没摊薄。"""
    stats = {"docs": 0, "new_stories": 0, "absorbed": 0, "errors": 0, "waves": 0}
    wave: list[BatchItem] = []
    wave_ents: set[str] = set()

    for doc in _unassigned_docs(conn, limit):
        if wave and (len(wave) >= batch_size or wave_ents & set(doc.salient)):
            await _flush_wave(conn, judge, wave, stats)
            wave, wave_ents = [], set()
        cands = recall(conn, doc.id)     # 冲刷之后才召回：看得见波内新建的故事
        if not cands:
            # 零候选：确定性新建，不花 LLM。与在批文档必然合格实体不相交
            #（相交早已触发冲刷），所以这个新故事不可能是它们的归宿。
            try:
                with conn.cursor() as cur:
                    sid = _create_story(cur, doc, doc.title or f"story:{doc.id}",
                                        "no candidates in active window")
                    _update_scalars(cur, sid)
                conn.commit()
                stats["new_stories"] += 1
                stats["docs"] += 1
            except Exception:
                conn.rollback()
                stats["errors"] += 1
                log.exception("doc %s story creation failed", doc.id)
            continue
        wave.append((doc, cands))
        wave_ents |= set(doc.salient)
    await _flush_wave(conn, judge, wave, stats)
    return stats
