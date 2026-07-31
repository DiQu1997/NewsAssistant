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
        return s

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
    def api_picture():
        """最新态势图；?history=1 时另附历史列表（浏览观点账本用）。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, at, model, payload FROM pictures
                           ORDER BY at DESC LIMIT 1""")
            r = cur.fetchone()
            if not r:
                return {"picture": None}
            return {"picture": {"id": r[0], "at": r[1].isoformat(),
                                "model": r[2], **r[3]}}

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    web_dir = Path(__file__).resolve().parent / "web"

    @app.get("/admin")
    def admin_page():
        return FileResponse(str(web_dir / "admin.html"), media_type="text/html")

    @app.get("/picture")
    def picture_page():
        return FileResponse(str(web_dir / "picture.html"), media_type="text/html")

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
