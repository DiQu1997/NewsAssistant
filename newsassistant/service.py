"""常驻服务 —— FastAPI 读接口 + 进程内调度器（architecture.md §6）。

两个职责一个进程：按时推进管线、响应查询。一个部署单元、一份日志、
一个 /health，而不是"一个 crontab + 一个构建脚本 + 一堆手敲"。

三条结构性约定：

1. **长任务不进请求路径。** 抽取/归并是分钟级的，HTTP 里同步跑必然超时。
   调度器串行推进管线，API 纯读 —— 最简单且够用的分工。没有任务队列，
   因为单用户本机服务里它只会是又一个要维护的状态机。
2. **调度器跑在线程里。** 阶段函数是阻塞式 psycopg 调用，直接放事件循环
   会把 API 一起卡死，所以每轮 `to_thread` 起一个自己的连接。
3. **互斥在库里不在进程里。** run_cycle 持 advisory lock，所以同时手敲
   `na run-cycle`、或误开第二个 serve，都不会两轮并行；进程崩溃时锁随
   连接自动释放，不需要清理残留状态。

数据归宿是本机（D17）：这是 localhost 单用户服务，暂不涉及认证与多用户。
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg

from . import db
from .config import Config, load
from .pipeline import default_stages, run_cycle

log = logging.getLogger(__name__)

TICK_SECONDS = 60          # 调度器唤醒间隔；跑不跑由各阶段的 min_interval 决定


def _rows(cur: psycopg.Cursor) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def create_app(cfg: Config | None = None, scheduler: bool = True,
               model: str | None = None):
    from fastapi import FastAPI, HTTPException

    cfg = cfg or load()
    state: dict = {"running": False, "last": None}

    def connect() -> psycopg.Connection:
        return db.connect(cfg.database_url)

    async def loop() -> None:
        """每 tick 叫一次 run_cycle，跑不跑由阶段节奏决定（判定在库里）。"""
        while True:
            try:
                state["running"] = True
                state["last"] = await asyncio.to_thread(_cycle_in_thread, cfg, model)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("scheduler tick failed")   # 调度器自身绝不因单轮失败退出
            finally:
                state["running"] = False
            await asyncio.sleep(TICK_SECONDS)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(loop()) if scheduler else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="NewsAssistant", lifespan=lifespan)

    @app.get("/health")
    def health():
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT stage, started_at, finished_at, error
                           FROM pipeline_runs ORDER BY id DESC LIMIT 1""")
            last = _rows(cur)
        return {"ok": True, "scheduler": scheduler,
                "cycle_running": state["running"], "last_run": last[0] if last else None}

    @app.get("/api/runs")
    def runs(limit: int = 50):
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT cycle, stage, started_at, finished_at, stats, error
                           FROM pipeline_runs ORDER BY id DESC LIMIT %s""",
                        (min(limit, 500),))
            return _rows(cur)

    @app.get("/api/stats")
    def stats():
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT
                (SELECT count(*) FROM documents WHERE status='ok'),
                (SELECT count(*) FROM documents WHERE extracted_at IS NOT NULL),
                (SELECT count(*) FROM claims),
                (SELECT count(*) FROM entities WHERE merged_into IS NULL),
                (SELECT count(*) FROM stories WHERE state='active'),
                (SELECT count(*) FROM stories WHERE state='dormant'),
                (SELECT count(*) FROM stories WHERE state='archived'),
                (SELECT count(*) FROM stories WHERE synthesized_at IS NOT NULL)""")
            d, e, c, ent, st, dorm, arch, syn = cur.fetchone()
        return {"docs": d, "extracted": e, "claims": c, "entities": ent,
                "stories": st, "dormant": dorm, "archived": arch,
                "synthesized": syn}

    @app.get("/api/pipeline")
    def api_pipeline():
        """信息流页的管线进度条：近 24h 采集→抽取→归编漏斗、72h V2 字段
        覆盖率（回填进行时它就是回填进度）、关键阶段最近完成时间。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT
                count(*),
                count(*) FILTER (WHERE status='ok'),
                count(*) FILTER (WHERE status='off_topic'),
                count(*) FILTER (WHERE status='ok' AND extracted_at IS NOT NULL),
                count(*) FILTER (WHERE status='ok' AND extracted_at IS NOT NULL
                                 AND EXISTS (SELECT 1 FROM story_documents sd
                                             WHERE sd.document_id=documents.id))
                FROM documents WHERE fetched_at > now() - interval '24 hours'""")
            fetched, kept, off, extracted, assigned = cur.fetchone()
            cur.execute("""SELECT count(*),
                                  count(*) FILTER (WHERE importance IS NOT NULL)
                           FROM documents
                           WHERE status='ok' AND extracted_at IS NOT NULL
                             AND fetched_at > now() - interval '72 hours'""")
            v2_total, v2_done = cur.fetchone()
            cur.execute("""SELECT DISTINCT ON (stage) stage, finished_at, error
                           FROM pipeline_runs
                           WHERE stage IN ('ingest','extract','assign','hierarchy',
                                           'market')
                             AND finished_at IS NOT NULL
                           ORDER BY stage, id DESC""")
            stages = {r[0]: {"finished_at": r[1].isoformat(),
                             "error": r[2]} for r in cur.fetchall()}
        return {"window_h": 24, "fetched": fetched, "kept": kept,
                "off_topic": off, "extracted": extracted, "assigned": assigned,
                "v2": {"total": v2_total, "done": v2_done},
                "stages": stages, "ingest_schedule": "每日 8:00 / 20:00"}

    @app.get("/api/stories")
    def stories(limit: int = 50, offset: int = 0, synthesized: bool = False):
        with connect() as conn, conn.cursor() as cur:
            cur.execute(f"""SELECT id, title, state, scalars, updated_at, synthesized_at
                            FROM stories
                            WHERE state='active'
                              {'AND synthesized_at IS NOT NULL' if synthesized else ''}
                            ORDER BY updated_at DESC LIMIT %s OFFSET %s""",
                        (min(limit, 200), offset))
            return _rows(cur)

    @app.get("/api/channels")
    def channels():
        """频道列表 —— 含各自的查询与标识色。前端不硬编码任何频道（D3）。"""
        from .channels import list_channels
        with connect() as conn:
            return list_channels(conn)

    @app.get("/api/channels/{key}/stories")
    def channel_stories(key: str, limit: int = 40, offset: int = 0):
        from .channels import BadQuery, channel_stories, get_channel
        from .snapshot import _story_series
        with connect() as conn:
            ch = get_channel(conn, key)
            if not ch:
                raise HTTPException(404, f"channel {key} not found")
            try:
                rows = channel_stories(conn, ch["query"], limit=limit, offset=offset)
            except BadQuery as exc:               # 坏查询是配置错误，不是 500
                raise HTTPException(422, str(exc)) from exc
            with conn.cursor() as cur:
                # 子主题 = 涌现簇词表（channel_topics，自我演化）；
                # channels.topics（yaml）只是冷启动种子，展示以 live 词表为准
                cur.execute("""SELECT key, name, hint FROM channel_topics
                               WHERE channel=%s ORDER BY created_at""", (key,))
                live = [{"key": k, "name": n, "hint": h}
                        for k, n, h in cur.fetchall()]
                if live:
                    ch["topics"] = live
                    cur.execute("""SELECT story_id, topic FROM story_topics
                                   WHERE channel=%s AND story_id=ANY(%s)""",
                                (key, [r["id"] for r in rows] or [0]))
                    tag = dict(cur.fetchall())
                    for r in rows:
                        r["topic"] = tag.get(r["id"])
                for r in rows:
                    r["series"] = _story_series(cur, r["id"])
        return {"channel": ch, "stories": rows}

    @app.get("/api/channels/{key}/structure")
    def channel_structure(key: str, limit: int = 60):
        """这个频道的数据里有什么结构 —— 视图由它选（D4）。

        未触发的检测器也返回：'为什么这个频道没有链路图' 必须能被回答，
        否则用户只会以为页面坏了。"""
        from dataclasses import asdict

        from .channels import BadQuery, channel_stories, get_channel
        from .structure import detect
        with connect() as conn:
            ch = get_channel(conn, key)
            if not ch:
                raise HTTPException(404, f"channel {key} not found")
            try:
                rows = channel_stories(conn, ch["query"], limit=limit)
            except BadQuery as exc:
                raise HTTPException(422, str(exc)) from exc
            dets = detect(conn, [r["id"] for r in rows])
        return {"channel": {"key": ch["key"], "name": ch["name"]},
                "slice": {"stories": len(rows)},
                "detections": [asdict(d) for d in dets]}

    @app.get("/api/stories/{story_id}")
    def story(story_id: int):
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, title, state, scalars, summary, timeline,
                           open_questions, updated_at, synthesized_at,
                           importance, domains, created_at, facts, views
                           FROM stories WHERE id=%s""", (story_id,))
            rows = _rows(cur)
            if not rows:
                raise HTTPException(404, f"story {story_id} not found")
            s = rows[0]
            # 层级归属（多父 DAG）：面包屑用
            cur.execute("""SELECT n.id, n.key, n.name FROM node_edges e
                           JOIN nodes n ON n.id=e.parent_id
                           WHERE e.child_kind='story' AND e.child_id=%s""",
                        (story_id,))
            s["nodes"] = _rows(cur)
            # 综述里引用到的断言原文 —— 引用可点开是原则 5 的前端face
            cur.execute("""SELECT c.id, c.text, c.stance, src.key AS source
                           FROM claims c
                           JOIN documents d ON d.id=c.document_id
                           JOIN sources src ON src.id=d.source_id
                           WHERE c.story_id=%s ORDER BY c.id""", (story_id,))
            s["claims"] = _rows(cur)
            cur.execute("""SELECT kind, payload, at FROM story_events
                           WHERE story_id=%s ORDER BY id""", (story_id,))
            s["events"] = _rows(cur)
            # 原文列表：报告页"回到新闻本身"的出口
            cur.execute("""SELECT d.id, d.title, d.url, src.key AS source,
                           src.name AS source_name, src.evidence_tier,
                           d.published_at, d.syndication_of
                           FROM story_documents sd
                           JOIN documents d ON d.id=sd.document_id
                           JOIN sources src ON src.id=d.source_id
                           WHERE sd.story_id=%s
                           ORDER BY d.published_at DESC NULLS LAST""", (story_id,))
            s["docs"] = _rows(cur)
            cur.execute("""SELECT deep_report, deep_report_at FROM stories
                           WHERE id=%s""", (story_id,))
            r = cur.fetchone()
            s["deep_report"], s["deep_report_at"] = r[0], r[1]
        return s

    # ── V2 头版 / 层级（docs/redesign-ui.md §六）────────────────

    DOMAIN_META = [
        {"key": "政治", "color": "#9E2B25"},
        {"key": "地缘政治", "color": "#B5761E"},
        {"key": "经济", "color": "#1E7A63"},
        {"key": "金融", "color": "#1E7A63"},
        {"key": "business", "color": "#2F5D8C"},
        {"key": "科技", "color": "#6A4BB5"},
    ]

    @app.get("/api/domains")
    def domains():
        """六大域 + 活跃计数。UI 端把经济/金融并成一列（handoff 五列墙）。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT d.dom, count(*) FROM (
                             SELECT unnest(domains) AS dom FROM stories
                             WHERE state='active'
                               AND updated_at > now() - interval '7 days') d
                           GROUP BY 1""")
            n = dict(cur.fetchall())
        return [{**m, "active": n.get(m["key"], 0)} for m in DOMAIN_META]

    def _stance_counts(cur, story_ids: list[int]) -> dict[int, list[int]]:
        """每故事的立场五档计数 [-2..-2+4]，立场微条燃料。"""
        if not story_ids:
            return {}
        cur.execute("""SELECT story_id, stance, count(*) FROM claims
                       WHERE story_id = ANY(%s) AND stance IS NOT NULL
                       GROUP BY 1, 2""", (story_ids,))
        out: dict[int, list[int]] = {}
        for sid, stance, n in cur.fetchall():
            out.setdefault(sid, [0, 0, 0, 0, 0])[max(-2, min(2, stance)) + 2] = n
        return out

    @app.get("/api/front")
    def front(window_hours: int = 72):
        """头版：必读候选 + 域墙（节点组 + standalone event）+ 未解问题带。
        排序键 = 热度分（幅度×近期活动×时间衰减）；同一故事整版只出现一次。"""
        from .snapshot import _story_series
        with connect() as conn, conn.cursor() as cur:
            # 头版排序 = 热度分，不是全时段 importance。importance 在头部会饱和
            # （大量故事顶到 5），退化成 updated_at 排序，而 updated_at 连 synthesize
            # 重算都会 bump —— 冷掉的老议题靠一次重算就霸榜。
            # heat = importance（幅度） × ln(2+近72h新增文档)（近期真实活动，压缩免碾压）
            #        × exp(-距最后一篇文档小时/48)（时间衰减，冷了自动沉）。
            # 半衰期 48h（HEAT_HALFLIFE）；衰减锚在“最后一篇文档”而非 updated_at，
            # 绕开重算的假新鲜。d72 实时算不预存 —— 预存会冻结，冷故事永不重算。
            cur.execute("""
                SELECT id, title, importance, domains, scalars, updated_at,
                       created_at, summary, open_questions
                FROM (
                  SELECT s.id, s.title, s.importance, s.domains, s.scalars,
                         s.updated_at, s.created_at, s.summary, s.open_questions,
                         (SELECT max(sd.added_at)
                            FROM story_documents sd JOIN documents d ON d.id=sd.document_id
                            WHERE sd.story_id=s.id AND d.status='ok') AS last_doc_at,
                         (SELECT count(*)
                            FROM story_documents sd JOIN documents d ON d.id=sd.document_id
                            WHERE sd.story_id=s.id AND d.status='ok'
                              AND sd.added_at > now() - interval '72 hours') AS d72
                  FROM stories s
                  WHERE s.state='active'
                    AND s.updated_at > now() - make_interval(hours => %s)
                ) t
                ORDER BY (coalesce(importance, 0) * ln(2 + d72)
                          * exp(-(EXTRACT(EPOCH FROM
                              (now() - coalesce(last_doc_at, updated_at))) / 3600) / 48.0)
                         ) DESC NULLS LAST
                LIMIT 150""", (window_hours,))
            rows = _rows(cur)
            for r in rows:
                summ = r.pop("summary") or []
                r["lede"] = (summ[0].get("text") if summ else None)
                r["age_days"] = (
                    r["updated_at"] - r["created_at"]).days if r["created_at"] else 0
            hero = rows[:3]
            rest = rows[3:]
            ids = [r["id"] for r in rows]
            stance = _stance_counts(cur, ids)
            for r in rows:
                r["stance"] = stance.get(r["id"])
            for r in hero:
                r["series"] = _story_series(cur, r["id"])

            # 为何在头版：给 hero 算可解释的排序依据（后端给、前端不编）——
            # 今日新增断言 / 今日新入库 / 今日新加入的独立源 + 既有广度与一致度。
            # 「新加入的独立源」= 近 24h 有 doc、而 24h 前从未在本故事出现的源。
            hero_ids = [r["id"] for r in hero]
            if hero_ids:
                cur.execute("""
                    SELECT s.id,
                      (SELECT count(*) FROM claims c WHERE c.story_id=s.id
                         AND c.extracted_at > now()-interval '24 hours'),
                      (SELECT count(*) FROM story_documents sd
                         JOIN documents d ON d.id=sd.document_id
                         WHERE sd.story_id=s.id AND d.status='ok'
                           AND sd.added_at > now()-interval '24 hours'),
                      (SELECT count(DISTINCT d.source_id) FROM story_documents sd
                         JOIN documents d ON d.id=sd.document_id
                         WHERE sd.story_id=s.id AND d.status='ok'
                           AND sd.added_at > now()-interval '24 hours'
                           AND NOT EXISTS (
                             SELECT 1 FROM story_documents sd2
                             JOIN documents d2 ON d2.id=sd2.document_id
                             WHERE sd2.story_id=s.id AND d2.source_id=d.source_id
                               AND sd2.added_at <= now()-interval '24 hours'))
                    FROM stories s WHERE s.id = ANY(%s)""", (hero_ids,))
                delta = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
                for r in hero:
                    nc, nd, ns = delta.get(r["id"], (0, 0, 0))
                    sc = r.get("scalars") or {}
                    bits = []
                    if nc:
                        bits.append(f"今日新增 {nc} 条可核查断言")
                    if ns:
                        bits.append(f"{ns} 个独立源今日加入")
                    if nd:
                        bits.append(f"{nd} 篇入库")
                    head = "、".join(bits) if bits else "今日无新增，靠既有权重与新鲜度上榜"
                    tail = f"；共 {sc.get('breadth', '?')} 独立源"
                    if sc.get("consensus") is not None:
                        tail += f"，一致度 {sc['consensus']}"
                    r["reason"] = {"new_claims": nc, "new_docs": nd,
                                   "new_sources": ns, "text": head + tail + "。"}

            # 故事 → 节点归属（多父：取与故事主域一致的第一个节点做展示位）
            cur.execute("""SELECT e.child_id, n.id, n.key, n.name, n.domains,
                                  n.importance, n.hint
                           FROM node_edges e JOIN nodes n ON n.id=e.parent_id
                           WHERE e.child_kind='story' AND e.child_id = ANY(%s)
                           ORDER BY e.at DESC""", (ids or [0],))
            story_nodes: dict[int, list[dict]] = {}
            for sid, nid, nkey, nname, ndoms, nimp, nhint in cur.fetchall():
                story_nodes.setdefault(sid, []).append(
                    {"id": nid, "key": nkey, "name": nname,
                     "domains": ndoms or [], "importance": nimp, "hint": nhint})
            for r in rows:
                r["nodes"] = [{"id": n["id"], "key": n["key"], "name": n["name"]}
                              for n in story_nodes.get(r["id"], [])]

            # 域墙：主域分列；列内按节点分组，未挂节点的平铺列尾
            walls: dict[str, dict] = {m["key"]: {"nodes": {}, "standalone": []}
                                      for m in DOMAIN_META}
            for r in rest:
                dom = (r["domains"] or [None])[0]
                if dom not in walls:
                    continue
                grp = None
                for n in story_nodes.get(r["id"], []):
                    if (n["domains"] or [None])[0] == dom:
                        grp = n
                        break
                if grp:
                    g = walls[dom]["nodes"].setdefault(
                        grp["id"], {"node": grp, "events": []})
                    g["events"].append(r)
                else:
                    walls[dom]["standalone"].append(r)
            wall_out = []
            for m in DOMAIN_META:
                w = walls[m["key"]]
                groups = sorted(w["nodes"].values(),
                                key=lambda g: (-(g["node"]["importance"] or 0)))
                for g in groups:
                    g["events"] = g["events"][:5]
                wall_out.append({"domain": m["key"], "color": m["color"],
                                 "groups": groups,
                                 "standalone": w["standalone"][:8]})

            # 未解问题带：从头版故事的 open_questions 抽，恒在最后
            band = []
            for r in rows:
                for q in (r.get("open_questions") or []):
                    text = q.get("text") if isinstance(q, dict) else str(q)
                    if text:
                        band.append({"question": text, "story_id": r["id"],
                                     "story_title": r["title"],
                                     "node": (r["nodes"][0]["name"]
                                              if r["nodes"] else None)})
                        break
                if len(band) >= 4:
                    break
            for r in rows:
                r.pop("open_questions", None)

            # 板块综述：每域一段模型写的话（section_digest 阶段，8/20 点重算）。
            # theme 供 5a 板块列的紧凑版，text 供 5b 板块头的完整版。
            cur.execute("""SELECT domain, text, theme, has_new, new_claims,
                                  lead_story_id, generated_at
                           FROM section_digests""")
            digests = {r[0]: {"text": r[1] or [], "theme": r[2],
                              "has_new": r[3], "new_claims": r[4],
                              "lead_story_id": r[5],
                              "generated_at": r[6].isoformat() if r[6] else None}
                       for r in cur.fetchall()}
        return {"hero": hero, "walls": wall_out, "open_questions": band,
                "section_digests": digests, "window_hours": window_hours}

    @app.get("/api/nodes/{node_id}")
    def node_detail(node_id: int):
        """节点页：父链（多父 DAG）、子节点、直属 event、去重上滚标量。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, key, name, hint, domains, importance,
                           created_at, last_active_at FROM nodes WHERE id=%s""",
                        (node_id,))
            rows = _rows(cur)
            if not rows:
                raise HTTPException(404, f"node {node_id} not found")
            node = rows[0]
            cur.execute("""SELECT n.id, n.key, n.name FROM node_edges e
                           JOIN nodes n ON n.id=e.parent_id
                           WHERE e.child_kind='node' AND e.child_id=%s""",
                        (node_id,))
            node["parents"] = _rows(cur)
            cur.execute("""SELECT n.id, n.key, n.name, n.hint, n.domains,
                           n.importance, n.last_active_at
                           FROM node_edges e JOIN nodes n ON n.id=e.child_id
                           WHERE e.parent_id=%s AND e.child_kind='node'
                           ORDER BY n.importance DESC NULLS LAST""", (node_id,))
            node["children_nodes"] = _rows(cur)
            cur.execute("""SELECT s.id, s.title, s.importance, s.domains,
                           s.scalars, s.updated_at
                           FROM node_edges e JOIN stories s ON s.id=e.child_id
                           WHERE e.parent_id=%s AND e.child_kind='story'
                           ORDER BY s.importance DESC NULLS LAST,
                                    s.updated_at DESC""", (node_id,))
            node["events"] = _rows(cur)
            stance = _stance_counts(cur, [e["id"] for e in node["events"]])
            for e in node["events"]:
                e["stance"] = stance.get(e["id"])
            # 去重上滚：后代闭包 distinct 文档统计
            cur.execute("""
                WITH RECURSIVE closure AS (
                    SELECT child_kind, child_id FROM node_edges WHERE parent_id=%s
                    UNION
                    SELECT e.child_kind, e.child_id FROM node_edges e
                    JOIN closure c ON c.child_kind='node' AND e.parent_id=c.child_id)
                SELECT count(DISTINCT sd.document_id),
                       count(DISTINCT d.source_id),
                       count(DISTINCT c.child_id)
                FROM closure c
                JOIN story_documents sd ON c.child_kind='story'
                     AND sd.story_id=c.child_id
                JOIN documents d ON d.id=sd.document_id AND d.status='ok'""",
                        (node_id,))
            docs, breadth, n_events = cur.fetchone()
            node["rollup"] = {"docs": docs, "breadth": breadth,
                              "events": n_events}
            # 合流时间线：子 event 的 synthesis 时间线按时间合并
            cur.execute("""
                WITH RECURSIVE closure AS (
                    SELECT child_kind, child_id FROM node_edges WHERE parent_id=%s
                    UNION
                    SELECT e.child_kind, e.child_id FROM node_edges e
                    JOIN closure c ON c.child_kind='node' AND e.parent_id=c.child_id)
                SELECT s.id, s.title, s.timeline FROM closure c
                JOIN stories s ON c.child_kind='story' AND s.id=c.child_id
                WHERE s.timeline IS NOT NULL""", (node_id,))
            tl = []
            for sid, stitle, timeline in cur.fetchall():
                for t in (timeline or [])[:6]:
                    # synth 存的字段是 when/what
                    if isinstance(t, dict) and t.get("when"):
                        tl.append({**t, "story_id": sid, "story_title": stitle})
            node["timeline"] = sorted(tl, key=lambda t: t["when"],
                                      reverse=True)[:20]
        return node

    @app.get("/api/daily-shape")
    def daily_shape():
        """画报页数据：域×小时热力、今日新生/转沉寂、实体增幅。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT (d.domains)[1], extract(hour FROM d.fetched_at)::int,
                       count(*)
                FROM documents d
                WHERE d.status='ok' AND d.fetched_at > date_trunc('day', now())
                  AND array_length(d.domains, 1) > 0
                GROUP BY 1, 2""")
            heat: dict[str, list[int]] = {}
            for dom, hour, n in cur.fetchall():
                heat.setdefault(dom, [0] * 24)[hour] = n
            cur.execute("""SELECT count(*) FROM documents
                           WHERE fetched_at > date_trunc('day', now())
                             AND status='ok'""")
            docs_today = cur.fetchone()[0]
            cur.execute("""SELECT id, title, importance FROM stories
                           WHERE created_at > date_trunc('day', now())
                           ORDER BY importance DESC NULLS LAST LIMIT 8""")
            born = _rows(cur)
            cur.execute("""SELECT s.id, s.title FROM story_events e
                           JOIN stories s ON s.id=e.story_id
                           WHERE e.kind='dormant'
                             AND e.at > date_trunc('day', now()) LIMIT 8""")
            dormant = _rows(cur)
            cur.execute("""
                SELECT e.canonical_name, count(*) AS n
                FROM document_entities de
                JOIN documents d ON d.id=de.document_id
                JOIN entities e ON e.id=coalesce(
                    (SELECT merged_into FROM entities WHERE id=de.entity_id),
                    de.entity_id)
                WHERE d.fetched_at > date_trunc('day', now()) AND d.status='ok'
                GROUP BY 1 ORDER BY 2 DESC LIMIT 10""")
            entities = [{"name": r[0], "n": r[1]} for r in cur.fetchall()]
        return {"heat": heat, "docs_today": docs_today, "born": born,
                "dormant": dormant, "entities": entities}

    @app.get("/api/weekly-shape")
    def weekly_shape():
        """复盘页数据：故事生命周期计数、涨落榜、未解问题清单。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT kind, count(*) FROM story_events
                WHERE at > now() - interval '7 days' GROUP BY kind""")
            lifecycle = dict(cur.fetchall())
            cur.execute("""
                SELECT id, title, importance, scalars, updated_at FROM stories
                WHERE state='active' AND updated_at > now() - interval '7 days'
                  AND (scalars->>'velocity') IS NOT NULL
                ORDER BY (scalars->>'velocity')::numeric DESC LIMIT 12""")
            risers = _rows(cur)
            cur.execute("""
                SELECT id, title, importance, scalars, updated_at FROM stories
                WHERE state='active' AND updated_at > now() - interval '7 days'
                  AND (scalars->>'velocity') IS NOT NULL
                ORDER BY (scalars->>'velocity')::numeric ASC LIMIT 6""")
            fallers = _rows(cur)
            cur.execute("""
                SELECT id, title, open_questions, updated_at FROM stories
                WHERE state='active' AND open_questions IS NOT NULL
                  AND jsonb_array_length(open_questions) > 0
                ORDER BY updated_at ASC LIMIT 8""")
            oq = []
            for sid, title, qs, upd in cur.fetchall():
                q = qs[0]
                oq.append({"story_id": sid, "story_title": title,
                           "question": (q.get("text") if isinstance(q, dict)
                                        else str(q)),
                           "since": upd.isoformat() if upd else None})
        return {"lifecycle": lifecycle, "risers": risers, "fallers": fallers,
                "open_questions": oq}

    _report_jobs: set[int] = set()

    @app.post("/api/stories/{story_id}/report")
    def gen_report(story_id: int):
        """按需生成深度报告（opus，约 2-4 分钟）。后台线程跑，前端轮询。"""
        if story_id in _report_jobs:
            return {"status": "running"}

        def _run():
            import asyncio
            from . import db as _db
            from .analyst import run_story_report
            try:
                conn2 = _db.connect(cfg.database_url)
                try:
                    asyncio.run(run_story_report(
                        conn2, story_id, cfg.stage_model("picture")))
                finally:
                    conn2.close()
            finally:
                _report_jobs.discard(story_id)

        import threading
        _report_jobs.add(story_id)
        threading.Thread(target=_run, daemon=True).start()
        return {"status": "started"}

    @app.get("/api/admin/tokens")
    def admin_tokens():
        """LLM 调用统计：按 purpose/model 聚合，含本周/本月/全部三个窗口。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""
              WITH parsed AS (
                SELECT purpose, model, at,
                  COALESCE(tokens_in,
                    (output->'usage'->>'input_tokens')::int, 0) AS t_in,
                  COALESCE(tokens_out,
                    (output->'usage'->>'output_tokens')::int, 0) AS t_out,
                  COALESCE(
                    (output->'usage'->>'cache_read_input_tokens')::int, 0) AS cache_read,
                  COALESCE(
                    (output->'usage'->>'cache_creation_input_tokens')::int, 0) AS cache_write
                FROM llm_calls
              )
              SELECT
                purpose, model,
                count(*) AS calls,
                sum(t_in) AS input_tokens,
                sum(t_out) AS output_tokens,
                sum(cache_read) AS cache_read_tokens,
                sum(cache_write) AS cache_write_tokens,
                min(at) AS first_call,
                max(at) AS last_call,
                count(*) FILTER (WHERE at >= date_trunc('week', now())) AS calls_week,
                sum(t_in) FILTER (WHERE at >= date_trunc('week', now())) AS input_week,
                sum(t_out) FILTER (WHERE at >= date_trunc('week', now())) AS output_week,
                count(*) FILTER (WHERE at >= date_trunc('month', now())) AS calls_month,
                sum(t_in) FILTER (WHERE at >= date_trunc('month', now())) AS input_month,
                sum(t_out) FILTER (WHERE at >= date_trunc('month', now())) AS output_month
              FROM parsed
              GROUP BY purpose, model
              ORDER BY sum(t_in + t_out) DESC NULLS LAST
            """)
            by_purpose = _rows(cur)

            cur.execute("""
              WITH parsed AS (
                SELECT at,
                  COALESCE(tokens_in,
                    (output->'usage'->>'input_tokens')::int, 0) AS t_in,
                  COALESCE(tokens_out,
                    (output->'usage'->>'output_tokens')::int, 0) AS t_out
                FROM llm_calls
              )
              SELECT
                date_trunc('day', at)::date AS day,
                count(*) AS calls,
                sum(t_in) AS input_tokens,
                sum(t_out) AS output_tokens
              FROM parsed
              WHERE at >= now() - interval '30 days'
              GROUP BY day ORDER BY day
            """)
            daily = _rows(cur)

            cur.execute("""
              WITH parsed AS (
                SELECT
                  COALESCE(tokens_in,
                    (output->'usage'->>'input_tokens')::int, 0) AS t_in,
                  COALESCE(tokens_out,
                    (output->'usage'->>'output_tokens')::int, 0) AS t_out,
                  COALESCE(
                    (output->'usage'->>'cache_read_input_tokens')::int, 0) AS cache_read,
                  at
                FROM llm_calls
              )
              SELECT
                count(*) AS total_calls,
                sum(t_in) AS total_input,
                sum(t_out) AS total_output,
                sum(cache_read) AS total_cache_read,
                count(*) FILTER (WHERE at >= date_trunc('week', now())) AS week_calls,
                sum(t_in) FILTER (WHERE at >= date_trunc('week', now())) AS week_input,
                sum(t_out) FILTER (WHERE at >= date_trunc('week', now())) AS week_output,
                count(*) FILTER (WHERE at >= date_trunc('month', now())) AS month_calls,
                sum(t_in) FILTER (WHERE at >= date_trunc('month', now())) AS month_input,
                sum(t_out) FILTER (WHERE at >= date_trunc('month', now())) AS month_output
              FROM parsed
            """)
            totals = _rows(cur)[0]

            cur.execute("""
              WITH parsed AS (
                SELECT model, at,
                  COALESCE(tokens_in,
                    (output->'usage'->>'input_tokens')::int, 0) AS t_in,
                  COALESCE(tokens_out,
                    (output->'usage'->>'output_tokens')::int, 0) AS t_out
                FROM llm_calls
              )
              SELECT model,
                count(*) AS calls,
                sum(t_in) AS input_tokens,
                sum(t_out) AS output_tokens,
                count(*) FILTER (WHERE at >= date_trunc('week', now())) AS calls_week,
                sum(t_in) FILTER (WHERE at >= date_trunc('week', now())) AS input_week,
                sum(t_out) FILTER (WHERE at >= date_trunc('week', now())) AS output_week,
                count(*) FILTER (WHERE at >= date_trunc('month', now())) AS calls_month,
                sum(t_in) FILTER (WHERE at >= date_trunc('month', now())) AS input_month,
                sum(t_out) FILTER (WHERE at >= date_trunc('month', now())) AS output_month
              FROM parsed
              GROUP BY model ORDER BY sum(t_in + t_out) DESC NULLS LAST
            """)
            by_model = _rows(cur)

        return {"by_purpose": by_purpose, "by_model": by_model,
                "daily": daily, "totals": totals}

    @app.get("/api/market")
    def api_market():
        """全部关注标的的最新信号快照（按 config.watchlist 排序）。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (symbol) symbol, at, payload
                FROM market_snapshots ORDER BY symbol, at DESC""")
            snap = {r[0]: {"at": r[1].isoformat(), **r[2]} for r in cur.fetchall()}
        from .universe import active_watchlist
        with connect() as conn:
            watch = active_watchlist(conn, cfg)
        order = [s for s in watch if s in snap]
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (symbol) symbol, at, model, payload
                FROM market_notes ORDER BY symbol, at DESC""")
            notes = {r[0]: {"at": r[1].isoformat(), "model": r[2], **r[3]}
                     for r in cur.fetchall()}
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT symbol, kind, pinned, reason FROM watchlist")
            wl = {r[0]: {"kind": r[1], "pinned": r[2], "reason": r[3]}
                  for r in cur.fetchall()}
        return {"symbols": order, "data": snap, "notes": notes,
                "watchlist": wl, "breadth": snap.get("_MARKET")}

    @app.get("/api/market/overview")
    def market_overview():
        """市场快照仪表盘的一次性供数：宽度、逐标的派生指标、行业聚合、
        叙事强度（自家新闻图谱：提及该公司实体的文档量）、雷达命中。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT ON (symbol) symbol, at, payload
                           FROM market_snapshots ORDER BY symbol, at DESC""")
            snap = {r[0]: r[2] for r in cur.fetchall()}
        from .universe import active_watchlist
        with connect() as conn:
            watch = [s for s in active_watchlist(conn, cfg)
                     if s in snap and s != "_MARKET"]
        breadth = snap.get("_MARKET") or {}

        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT symbol, name, sector FROM universe")
            uni = {r[0]: {"name": r[1], "sector": r[2]} for r in cur.fetchall()}

            rows, narrative = [], {}
            for sym in watch:
                ind = (snap[sym] or {}).get("indicators") or {}
                u = uni.get(sym) or {}
                # 叙事强度：公司名 → 实体 → 近 7/30 日提及文档数。
                # 名称匹配是启发式（规范全称通常能对上），前端已标注口径
                name = (u.get("name") or "").split(",")[0]
                core = name
                for suf in (" Inc.", " Inc", " Corporation", " Corp.", " Corp",
                            " PLC", " plc", " Ltd.", " Ltd", " Company", " Co."):
                    core = core.removesuffix(suf)
                n7 = n30 = 0
                story = None
                if len(core) >= 3:
                    cur.execute("""
                        SELECT count(DISTINCT de.document_id)
                                 FILTER (WHERE d.fetched_at > now() - interval '7 days'),
                               count(DISTINCT de.document_id)
                        FROM entities e
                        JOIN document_entities de ON de.entity_id=coalesce(e.merged_into, e.id)
                        JOIN documents d ON d.id=de.document_id
                        WHERE d.fetched_at > now() - interval '30 days'
                          AND d.status='ok'
                          AND (e.canonical_name ILIKE %s OR e.canonical_name = %s)""",
                                (core + "%", name))
                    n7, n30 = cur.fetchone()
                    cur.execute("""
                        SELECT s.id, s.title FROM stories s
                        JOIN story_entities se ON se.story_id=s.id
                        JOIN entities e ON coalesce(e.merged_into, e.id)=se.entity_id
                        WHERE s.state='active' AND e.canonical_name ILIKE %s
                        ORDER BY s.updated_at DESC LIMIT 1""", (core + "%",))
                    r = cur.fetchone()
                    if r:
                        story = {"id": r[0], "title": r[1]}
                narrative[sym] = {"docs_7d": n7, "docs_30d": n30, "story": story}
                rows.append({
                    "symbol": sym, "name": u.get("name"), "sector": u.get("sector"),
                    "close": ind.get("close"), "ret_1d": ind.get("ret_1d"),
                    "ret_5d": ind.get("ret_5d"), "ret_21d": ind.get("ret_21d"),
                    "ret_63d": ind.get("ret_63d"),
                    "rs_21d": ind.get("rs_21d"), "rsi": ind.get("rsi"),
                    "atr_pct": ind.get("atr_pct"), "atr_trend": ind.get("atr_trend"),
                    "stage": ind.get("stage"), "score": ind.get("score"),
                    "above50": (ind["close"] > ind["sma50"]
                                if ind.get("close") and ind.get("sma50") else None),
                    "above200": (ind["close"] > ind["sma200"]
                                 if ind.get("close") and ind.get("sma200") else None),
                })

            sectors: dict[str, list[float]] = {}
            for r in rows:
                if r["sector"] and r["ret_21d"] is not None:
                    sectors.setdefault(r["sector"], []).append(r["ret_21d"])
            sector_rows = sorted(
                ({"sector": k, "n": len(v), "avg_ret_21d": sum(v) / len(v)}
                 for k, v in sectors.items()),
                key=lambda x: -x["avg_ret_21d"])

            cur.execute("SELECT max(day) FROM radar_hits")
            day = cur.fetchone()[0]
            radar = []
            if day:
                cur.execute("""
                    SELECT h.symbol, h.score, h.reasons, u.name, u.sector
                    FROM radar_hits h LEFT JOIN universe u ON u.symbol=h.symbol
                    WHERE h.day=%s ORDER BY h.score DESC LIMIT 10""", (day,))
                radar = [{"symbol": r[0], "score": round(r[1], 1),
                          "reasons": r[2], "name": r[3], "sector": r[4]}
                         for r in cur.fetchall()]

            # 宏观叙事仪表：六域 importance 加权文档量，本 7 日 vs 前 7 日 ——
            # 我们自己的新闻图谱就是宏观数据源（地缘热度飙升 = 自家地缘风险指数）
            cur.execute("""
                SELECT dom,
                       coalesce(sum(coalesce(d.importance,2)) FILTER
                         (WHERE d.fetched_at > now() - interval '7 days'), 0),
                       coalesce(sum(coalesce(d.importance,2)) FILTER
                         (WHERE d.fetched_at <= now() - interval '7 days'), 0)
                FROM documents d, unnest(d.domains) dom
                WHERE d.fetched_at > now() - interval '14 days' AND d.status='ok'
                GROUP BY dom""")
            gauge_domains = [{"domain": r[0], "cur": int(r[1]), "prev": int(r[2])}
                             for r in cur.fetchall()]
            cur.execute("""
                SELECT id, title, importance, domains FROM stories
                WHERE state='active' AND coalesce(importance,0) >= 4
                  AND domains && ARRAY['地缘政治','经济','金融']::text[]
                ORDER BY importance DESC, updated_at DESC LIMIT 6""")
            gauge_stories = [{"id": r[0], "title": r[1], "importance": r[2],
                              "domains": r[3]} for r in cur.fetchall()]

        return {"breadth": breadth, "rows": rows, "narrative": narrative,
                "sectors": sector_rows, "radar": radar,
                "radar_day": str(day) if day else None,
                "macro": snap.get("_MACRO"),
                "gauge": {"domains": gauge_domains, "stories": gauge_stories}}

    @app.get("/api/radar")
    def api_radar():
        """最近一个扫描日的雷达命中 + 全集规模。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT max(day) FROM radar_hits")
            day = cur.fetchone()[0]
            if day is None:
                return {"day": None, "hits": []}
            cur.execute("""
                SELECT h.symbol, h.score, h.reasons, h.promoted,
                       u.name, u.sector, w.kind
                FROM radar_hits h
                LEFT JOIN universe u ON u.symbol=h.symbol
                LEFT JOIN watchlist w ON w.symbol=h.symbol
                WHERE h.day=%s ORDER BY h.score DESC LIMIT 40""", (day,))
            hits = [{"symbol": r[0], "score": round(r[1], 1), "reasons": r[2],
                     "promoted": r[3], "name": r[4], "sector": r[5],
                     "wl": r[6]} for r in cur.fetchall()]
        return {"day": str(day), "hits": hits}

    @app.post("/api/watchlist/{symbol}/{action}")
    def watchlist_action(symbol: str, action: str):
        """pin / ban / remove / add —— 关注清单的人工否决权。"""
        sym = symbol.upper()
        with connect() as conn, conn.cursor() as cur:
            if action == "pin":
                cur.execute("""UPDATE watchlist SET pinned = NOT pinned
                               WHERE symbol=%s RETURNING pinned""", (sym,))
                r = cur.fetchone()
                conn.commit()
                return {"symbol": sym, "pinned": r[0] if r else None}
            if action == "ban":
                cur.execute("""INSERT INTO watchlist (symbol, kind, reason)
                               VALUES (%s,'banned','manual')
                               ON CONFLICT (symbol) DO UPDATE SET
                                 kind='banned', pinned=false""", (sym,))
            elif action == "remove":
                cur.execute("DELETE FROM watchlist WHERE symbol=%s AND kind!='core'",
                            (sym,))
            elif action == "add":
                cur.execute("""INSERT INTO watchlist (symbol, kind, reason)
                               VALUES (%s,'rotating','manual')
                               ON CONFLICT (symbol) DO UPDATE SET
                                 kind='rotating'""", (sym,))
            else:
                raise HTTPException(400, f"unknown action {action}")
            conn.commit()
        return {"symbol": sym, "action": action, "ok": True}

    _note_jobs: set[str] = set()

    @app.post("/api/market/{symbol}/note")
    def gen_note(symbol: str):
        """按需生成个股分析 note（约 2-4 分钟，后台线程，前端轮询）。"""
        sym = symbol.upper()
        if sym in _note_jobs:
            return {"status": "running"}

        def _run():
            import asyncio
            from . import db as _db
            from .analyst import run_stock_note
            try:
                conn2 = _db.connect(cfg.database_url)
                try:
                    asyncio.run(run_stock_note(
                        conn2, sym, cfg.stage_model("note")))
                finally:
                    conn2.close()
            finally:
                _note_jobs.discard(sym)

        import threading
        _note_jobs.add(sym)
        threading.Thread(target=_run, daemon=True).start()
        return {"status": "started"}

    @app.get("/api/market/{symbol}/bars")
    def api_market_bars(symbol: str, days: int = 180):
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT day, open, high, low, close, volume FROM market_bars
                WHERE symbol=%s ORDER BY day DESC LIMIT %s""",
                        (symbol.upper(), min(days, 400)))
            rows = [{"day": str(r[0]), "o": r[1], "h": r[2], "l": r[3],
                     "c": r[4], "v": r[5]} for r in cur.fetchall()]
        rows.reverse()
        return {"symbol": symbol.upper(), "bars": rows}

    @app.get("/api/reading")
    def api_reading(days: int = 7, kind: str | None = None,
                    tag: str | None = None, min_sig: int = 1):
        """阅读队列：预消化完成的文章，重要度优先。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT d.id, d.title, d.url, d.published_at, src.key, src.name,
                       rn.payload, rn.at
                FROM reading_notes rn
                JOIN documents d ON d.id = rn.document_id
                JOIN sources src ON src.id = d.source_id
                WHERE rn.at > now() - make_interval(days => %s)
                ORDER BY (rn.payload->>'significance')::int DESC,
                         d.published_at DESC NULLS LAST
                LIMIT 400""", (min(days, 60),))
            items = []
            tags: dict[str, int] = {}
            for did, title, url, pub, skey, sname, p, at in cur.fetchall():
                if kind and p.get("kind") != kind:
                    continue
                if p.get("significance", 0) < min_sig:
                    continue
                for t in p.get("tags", []):
                    tags[t] = tags.get(t, 0) + 1
                if tag and tag not in (p.get("tags") or []):
                    continue
                items.append({
                    "id": did, "title": title, "url": url,
                    "published_at": pub.isoformat() if pub else None,
                    "source": skey, "source_name": sname, **p})
            top_tags = sorted(tags.items(), key=lambda x: -x[1])[:24]
            cur.execute("SELECT document_id FROM reading_digests")
            digested = {r[0] for r in cur.fetchall()}
            for it in items:
                it["has_digest"] = it["id"] in digested
        return {"items": items, "tags": top_tags}

    @app.get("/api/reading/{doc_id}/digest")
    def get_digest(doc_id: int):
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT rd.at, rd.model, rd.payload, d.title, d.url,
                           src.name
                           FROM reading_digests rd
                           JOIN documents d ON d.id=rd.document_id
                           JOIN sources src ON src.id=d.source_id
                           WHERE rd.document_id=%s""", (doc_id,))
            r = cur.fetchone()
        if not r:
            return {"digest": None}
        return {"digest": {"at": r[0].isoformat(), "model": r[1],
                           "doc_title": r[3], "doc_url": r[4],
                           "source_name": r[5], **r[2]}}

    _digest_jobs: set[int] = set()

    @app.post("/api/reading/{doc_id}/digest")
    def gen_digest(doc_id: int):
        """按需生成阅读版本（sonnet，约 2-4 分钟）。"""
        if doc_id in _digest_jobs:
            return {"status": "running"}

        def _run():
            import asyncio
            from . import db as _db
            from .reading import run_digest
            try:
                conn2 = _db.connect(cfg.database_url)
                try:
                    asyncio.run(run_digest(
                        conn2, cfg, doc_id, cfg.stage_model("digest")))
                finally:
                    conn2.close()
            finally:
                _digest_jobs.discard(doc_id)

        import threading
        _digest_jobs.add(doc_id)
        threading.Thread(target=_run, daemon=True).start()
        return {"status": "started"}

    @app.get("/read")
    def read_page():
        from fastapi.responses import FileResponse as _FR
        return _FR(str(Path(__file__).resolve().parent / "web" / "read.html"),
                   media_type="text/html")

    @app.get("/reading")
    def reading_page():
        from fastapi.responses import FileResponse as _FR
        return _FR(str(Path(__file__).resolve().parent / "web" / "reading.html"),
                   media_type="text/html")

    # stage → (llm_calls.purpose, stage_models 的 policy key)；None = 无 LLM
    _STAGE_LLM = {
        "extract": ("extract", "extract"),
        "assign": ("assign", "assign"),
        "resolve-entities": ("resolve_entity", "resolve-entities"),
        "synthesize": ("synthesize", "synthesize"),
        "picture": ("picture", "picture"),
        "wrap": ("wrap", "wrap"),
        "notes": ("stock_note", "note"),
        "reading": ("reading", "reading"),
        "digests": ("digest", "digest"),
    }

    @app.get("/api/admin/routines")
    def admin_routines():
        """Routine 总表：频率（反射自调度定义）× 模型 policy × 24h 实测。"""
        from .pipeline import default_stages
        stages = default_stages(cfg)

        def freq(st):
            if st.at_hour is not None:
                return f"每日 {st.at_hour}:00 锚定"
            h = st.min_interval / 3600
            return f"每 {st.min_interval // 60} 分钟" if h < 1 else f"每 {h:g} 小时"

        with connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT purpose,
                  count(*) FILTER (WHERE output->'usage'->>'input_tokens'
                                   IS NOT NULL) AS calls,
                  count(*) FILTER (WHERE model LIKE 'codex%%') AS codex_rows,
                  round(sum(COALESCE((output->'usage'->>'output_tokens')::int,0))
                        /1000.0) AS out_k,
                  round(sum(COALESCE((output->'usage'->>'cache_creation_input_tokens')::int,0))
                        /1000.0) AS cachew_k
                FROM llm_calls WHERE at > now() - interval '24 hours'
                GROUP BY purpose""")
            spend = {r[0]: {"calls": r[1], "codex_rows": r[2],
                            "out_k": float(r[3] or 0), "cachew_k": float(r[4] or 0)}
                     for r in cur.fetchall()}
            cur.execute("""
                SELECT stage, max(started_at),
                  count(*) FILTER (WHERE started_at > now() - interval '24 hours'
                                   AND finished_at IS NOT NULL),
                  bool_or(error IS NOT NULL AND
                          started_at > now() - interval '24 hours')
                FROM pipeline_runs GROUP BY stage""")
            runs = {r[0]: {"last": r[1].isoformat() if r[1] else None,
                           "runs_24h": r[2], "had_error": r[3]}
                    for r in cur.fetchall()}

        out = []
        for st in stages:
            purpose, policy = _STAGE_LLM.get(st.name) or (None, None)
            model = cfg.stage_model(policy) if policy else None
            out.append({
                "stage": st.name, "freq": freq(st),
                "model": model or "（确定性，无 LLM）",
                **(runs.get(st.name) or {"last": None, "runs_24h": 0,
                                         "had_error": False}),
                **(spend.get(purpose) or {"calls": 0, "codex_rows": 0,
                                          "out_k": 0, "cachew_k": 0}),
            })
        return {"routines": out}

    @app.get("/api/admin/usage")
    def admin_usage():
        """订阅真实占用：当前 5h/7d 窗口百分比 + 最近各阶段的占用增量。"""
        from .usagemeter import fetch_claude_usage
        live = fetch_claude_usage()
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT stage, started_at, finished_at, stats->'sub_usage'
                FROM pipeline_runs
                WHERE stats ? 'sub_usage'
                ORDER BY started_at DESC LIMIT 40""")
            runs = []
            for stage, at, fin, su in cur.fetchall():
                row = {"stage": stage, "at": at.isoformat(),
                       "secs": (fin - at).total_seconds() if fin else None}
                for w in ("five_hour", "seven_day"):
                    b, a = (su.get(w) or {}).get("before"), (su.get(w) or {}).get("after")
                    row[w] = round(a - b, 2) if (a is not None and b is not None
                                                 and a >= b) else None
                runs.append(row)
        return {"live": live, "runs": runs}

    @app.get("/api/admin/sources")
    def admin_sources():
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""
              SELECT s.key, s.name, s.kind, s.enabled,
                count(d.id) AS docs,
                count(d.id) FILTER (WHERE d.status='ok') AS docs_ok,
                max(d.fetched_at) AS last_fetch
              FROM sources s LEFT JOIN documents d ON d.source_id = s.id
              GROUP BY s.id ORDER BY count(d.id) DESC
            """)
            return _rows(cur)

    @app.get("/api/picture")
    def api_picture(desk: str = "general"):
        """指定 desk 的最新态势图；剧场附上引用断言所属的故事（下钻入口）。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, at, model, payload FROM pictures
                           WHERE desk=%s ORDER BY at DESC LIMIT 1""", (desk,))
            r = cur.fetchone()
            if not r:
                return {"picture": None}
            payload = r[3]
            for th in payload.get("theaters", []):
                ids = [i for i in th.get("evidence_claim_ids", [])
                       if isinstance(i, int)][:60]
                if not ids:
                    continue
                cur.execute("""
                    SELECT s.id, s.title, count(*) AS n
                    FROM claims c JOIN stories s ON s.id=c.story_id
                    WHERE c.id = ANY(%s)
                    GROUP BY s.id ORDER BY n DESC LIMIT 5""", (ids,))
                th["stories"] = [{"id": x[0], "title": x[1]} for x in cur.fetchall()]
            return {"picture": {"id": r[0], "at": r[1].isoformat(),
                                "model": r[2], "desk": desk, **payload}}

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    web_dir = Path(__file__).resolve().parent / "web"

    @app.get("/admin")
    def admin_page():
        return FileResponse(str(web_dir / "admin.html"), media_type="text/html")

    @app.get("/picture")
    def picture_page():
        return FileResponse(str(web_dir / "picture.html"), media_type="text/html")

    @app.get("/story")
    def story_page():
        return FileResponse(str(web_dir / "story.html"), media_type="text/html")

    @app.get("/market")
    def market_page():
        return FileResponse(str(web_dir / "market.html"), media_type="text/html")

    @app.get("/wrap")
    def wrap_page():
        return FileResponse(str(web_dir / "wrap.html"), media_type="text/html")

    # 构建期生成的原型页（虚构数据）仍可访问，但不再是产品面
    dash = Path(__file__).resolve().parent.parent / "prototypes" / "dashboard"
    if dash.is_dir():
        app.mount("/prototypes", StaticFiles(directory=str(dash), html=True),
                  name="prototypes")

    # V2 前端（React+Vite 构建产物）优先；构建缺席时回退旧静态页。
    # 旧前端恒挂 /legacy —— 新 UI 出问题时永远有一条能用的路。
    app.mount("/legacy", StaticFiles(directory=str(web_dir), html=True),
              name="legacy")
    dist = Path(__file__).resolve().parent.parent / "web-v2" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="web")
    else:
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")

    return app


def _cycle_in_thread(cfg: Config, model: str | None) -> dict:
    """线程内独立连接：psycopg 连接不是线程安全的，也不该跨 tick 长持。"""
    conn = db.connect(cfg.database_url)
    try:
        return run_cycle(conn, cfg, default_stages(cfg, model=model))
    finally:
        conn.close()


def serve(host: str = "127.0.0.1", port: int = 8787, scheduler: bool = True,
          model: str | None = None) -> None:
    import uvicorn
    uvicorn.run(create_app(scheduler=scheduler, model=model), host=host, port=port)
