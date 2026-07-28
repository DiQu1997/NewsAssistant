"""L3 快照导出 —— Postgres → JSON，dashboard 生成器的输入（阶段 5 前端真化）。

原型的生成架构 = 生产架构的形状：store → 查询 → 视图。真化 = 把 store
从虚构数据换成这里导出的真实快照，生成器（prototypes/dashboard/*.mjs）
只消费结构，不知道任何主题。

快照是纯派生产物（廉价可再生），每次全量导出，不做增量。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import psycopg

log = logging.getLogger(__name__)

SERIES_DAYS = 14         # 故事火花线：近 N 天逐日文档数（真数据，替代原型伪随机）
TOP_ENTITIES = 40


def _story_series(cur: psycopg.Cursor, story_id: int) -> list[int]:
    cur.execute("""
        SELECT date_trunc('day', sd.added_at)::date, count(*)
        FROM story_documents sd WHERE sd.story_id=%s
        GROUP BY 1""", (story_id,))
    by_day = {d.isoformat(): n for d, n in cur.fetchall()}
    today = datetime.now(timezone.utc).date()
    out = []
    for i in range(SERIES_DAYS - 1, -1, -1):
        day = today.fromordinal(today.toordinal() - i)
        out.append(by_day.get(day.isoformat(), 0))
    return out


def _source_daily(cur: psycopg.Cursor, days: int = 30) -> dict[str, list[int]]:
    """源 × 日矩阵：近 N 天每源逐日可用文档数（published_at 回退 fetched_at）。"""
    cur.execute("""
        SELECT s.key, coalesce(d.published_at, d.fetched_at)::date, count(*)
        FROM documents d JOIN sources s ON s.id=d.source_id
        WHERE d.status='ok'
          AND coalesce(d.published_at, d.fetched_at) > now() - make_interval(days => %s)
        GROUP BY 1,2""", (days,))
    raw: dict[str, dict[str, int]] = {}
    for key, day, n in cur.fetchall():
        raw.setdefault(key, {})[day.isoformat()] = n
    today = datetime.now(timezone.utc).date()
    out = {}
    for key, by_day in raw.items():
        out[key] = [by_day.get(
            today.fromordinal(today.toordinal() - i).isoformat(), 0)
            for i in range(days - 1, -1, -1)]
    return out


def _cooccurrence(cur: psycopg.Cursor, top: int = 26) -> dict:
    """实体共现图：df 头部实体间的文档级共现边（规范条目，穿透合并）。"""
    cur.execute("""
        WITH ce AS (SELECT DISTINCT de.document_id,
                           coalesce(e.merged_into, e.id) AS eid
                    FROM document_entities de JOIN entities e ON e.id=de.entity_id),
             head AS (SELECT eid, count(*) AS df FROM ce GROUP BY eid
                      ORDER BY df DESC LIMIT %s)
        SELECT e.canonical_name, e.kind, h.df FROM head h
        JOIN entities e ON e.id=h.eid ORDER BY h.df DESC""", (top,))
    nodes = [{"name": r[0], "kind": r[1], "df": r[2]} for r in cur.fetchall()]
    idx = {n["name"]: i for i, n in enumerate(nodes)}
    cur.execute("""
        WITH ce AS (SELECT DISTINCT de.document_id,
                           coalesce(e.merged_into, e.id) AS eid
                    FROM document_entities de JOIN entities e ON e.id=de.entity_id),
             head AS (SELECT eid, count(*) AS df FROM ce GROUP BY eid
                      ORDER BY df DESC LIMIT %s)
        SELECT e1.canonical_name, e2.canonical_name, count(*)
        FROM ce a JOIN ce b ON a.document_id=b.document_id AND a.eid < b.eid
        JOIN head h1 ON h1.eid=a.eid JOIN head h2 ON h2.eid=b.eid
        JOIN entities e1 ON e1.id=a.eid JOIN entities e2 ON e2.id=b.eid
        GROUP BY 1,2 HAVING count(*) >= 2 ORDER BY 3 DESC LIMIT 80""", (top,))
    edges = [{"a": idx[r[0]], "b": idx[r[1]], "w": r[2]} for r in cur.fetchall()
             if r[0] in idx and r[1] in idx]
    return {"nodes": nodes, "edges": edges}


def export_snapshot(conn: psycopg.Connection) -> dict:
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) FILTER (WHERE status='ok'),
                              count(DISTINCT source_id),
                              count(*) FILTER (WHERE extracted_at IS NOT NULL),
                              max(fetched_at)::text
                       FROM documents""")
        docs_ok, n_sources, extracted, last_fetch = cur.fetchone()
        cur.execute("SELECT count(*) FROM claims")
        n_claims = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM entities WHERE merged_into IS NULL")
        n_entities = cur.fetchone()[0]

        # ── 源构成（真实采集统计） ──
        cur.execute("""
            SELECT s.key, s.name, s.evidence_tier,
                   count(d.id) FILTER (WHERE d.status='ok')
            FROM sources s LEFT JOIN documents d ON d.source_id=s.id
            WHERE s.enabled GROUP BY s.id ORDER BY 4 DESC""")
        sources = [{"key": k, "name": n, "tier": t, "docs": c}
                   for k, n, t, c in cur.fetchall()]

        # ── 实体活跃榜（规范条目，穿透合并） ──
        cur.execute("""
            SELECT e2.canonical_name, e2.kind, count(DISTINCT de.document_id) AS df
            FROM document_entities de
            JOIN entities e ON e.id=de.entity_id
            JOIN entities e2 ON e2.id=coalesce(e.merged_into, e.id)
            GROUP BY 1,2 ORDER BY df DESC LIMIT %s""", (TOP_ENTITIES,))
        entities = [{"name": n, "kind": k, "df": d} for n, k, d in cur.fetchall()]

        # ── 故事池（活跃全量） ──
        cur.execute("""
            SELECT s.id, s.title, s.state, s.scalars, s.summary, s.timeline,
                   s.open_questions, s.created_at::date::text,
                   to_char(s.updated_at,'MM-DD HH24:MI'), s.synthesized_at IS NOT NULL
            FROM stories s WHERE s.state='active'
            ORDER BY (s.scalars->>'docs')::int DESC NULLS LAST, s.updated_at DESC""")
        stories = []
        for sid, title, state, sc, summary, timeline, oq, created, updated, has_syn in cur.fetchall():
            stories.append({
                "id": sid, "title": title, "state": state, "scalars": sc or {},
                "summary": summary, "timeline": timeline, "open_questions": oq,
                "created": created, "updated": updated, "synthesized": has_syn})

        detail_ids = [s["id"] for s in stories if s["synthesized"]]
        claims_ref: dict[int, dict] = {}
        for s in stories:
            cur2 = conn.cursor()
            s["series"] = _story_series(cur2, s["id"])
            cur2.close()
            if s["id"] not in detail_ids:
                continue
            # 详情页数据：文档（带层级/转述）、事件履历、实体、被引 claims
            cur.execute("""
                SELECT d.id, d.title, src.key, src.evidence_tier,
                       coalesce(to_char(d.published_at,'MM-DD'),'?'), d.url,
                       (SELECT count(*) FROM documents c
                        WHERE c.syndication_of = d.id)
                FROM story_documents sd
                JOIN documents d ON d.id=sd.document_id
                JOIN sources src ON src.id=d.source_id
                WHERE sd.story_id=%s ORDER BY d.published_at NULLS LAST""", (s["id"],))
            s["docs"] = [{"id": r[0], "title": r[1], "source": r[2], "tier": r[3],
                          "date": r[4], "url": r[5], "copies": r[6]}
                         for r in cur.fetchall()]
            cur.execute("""SELECT to_char(at,'MM-DD HH24:MI'), kind, payload
                           FROM story_events WHERE story_id=%s ORDER BY id""", (s["id"],))
            s["events"] = [{"at": r[0], "kind": r[1], "payload": r[2]}
                           for r in cur.fetchall()]
            cur.execute("""
                SELECT DISTINCT e2.canonical_name, e2.kind
                FROM story_entities se
                JOIN entities e ON e.id=se.entity_id
                JOIN entities e2 ON e2.id=coalesce(e.merged_into, e.id)
                WHERE se.story_id=%s ORDER BY 1 LIMIT 20""", (s["id"],))
            s["entities"] = [{"name": r[0], "kind": r[1]} for r in cur.fetchall()]
            # 被综述/时间线引用的 claim 全文（引用是可点开的，不是装饰）
            cited: set[int] = set()
            for part in (s["summary"] or []) + (s["timeline"] or []):
                cited.update(part.get("claim_ids", []))
            if cited:
                cur.execute("""
                    SELECT c.id, c.text, coalesce(c.stance,0), src.key,
                           coalesce(to_char(d.published_at,'MM-DD'),'?'), d.id
                    FROM claims c
                    JOIN documents d ON d.id=c.document_id
                    JOIN sources src ON src.id=d.source_id
                    WHERE c.id = ANY(%s)""", (list(cited),))
                for r in cur.fetchall():
                    claims_ref[r[0]] = {"text": r[1], "stance": r[2],
                                        "source": r[3], "date": r[4], "doc": r[5]}

    with conn.cursor() as cur:
        daily = _source_daily(cur)
        cooc = _cooccurrence(cur)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "daily_sources": daily,
        "cooc": cooc,
        "totals": {"docs": docs_ok, "sources": n_sources, "extracted": extracted,
                   "claims": n_claims, "entities": n_entities,
                   "stories": len(stories),
                   "synthesized": len(detail_ids),
                   "last_fetch": last_fetch},
        "sources": sources,
        "entities": entities,
        "stories": stories,
        "claims": {str(k): v for k, v in claims_ref.items()},
    }


def write_snapshot(conn: psycopg.Connection, out: Path) -> Path:
    snap = export_snapshot(conn)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=None),
                   encoding="utf-8")
    log.info("snapshot: %d stories (%d with synthesis) → %s",
             snap["totals"]["stories"], snap["totals"]["synthesized"], out)
    return out
