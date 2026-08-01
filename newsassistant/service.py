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
                           open_questions, updated_at, synthesized_at
                           FROM stories WHERE id=%s""", (story_id,))
            rows = _rows(cur)
            if not rows:
                raise HTTPException(404, f"story {story_id} not found")
            s = rows[0]
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
                        conn2, sym, cfg.stage_model("wrap")))
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

    # 真正的 dashboard：运行时向上面这些接口取数（频道=保存的查询必须
    # 在请求时执行，烘进构建期就不是查询了 —— D3 在静态生成下不成立）
    app.mount("/", StaticFiles(directory=str(Path(__file__).resolve().parent / "web"),
                               html=True), name="web")

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
