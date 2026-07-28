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
                (SELECT count(*) FROM stories WHERE synthesized_at IS NOT NULL)""")
            d, e, c, ent, st, syn = cur.fetchone()
        return {"docs": d, "extracted": e, "claims": c, "entities": ent,
                "stories": st, "synthesized": syn}

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

    # 已生成的静态页（build-real.mjs 的产物）挂在 / 下，服务同时是它的宿主
    dash = Path(__file__).resolve().parent.parent / "prototypes" / "dashboard"
    if dash.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/dashboard", StaticFiles(directory=str(dash), html=True),
                  name="dashboard")

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
