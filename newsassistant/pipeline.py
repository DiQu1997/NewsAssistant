"""管线编排 —— 一轮 = 按依赖顺序推进各阶段（006_pipeline_runs.sql）。

编排属于代码，不属于 crontab：
  - **互斥**：整轮持 Postgres advisory lock。上一轮 extract 还在跑时，
    下一轮（或手敲的 `na assign`）拿不到锁直接跳过。cron 做不到这件事 ——
    它到点就起新进程，不管上一个死没死。
  - **节奏**：每个阶段自带 min_interval，是否到期查 `pipeline_runs`（落库
    而非进程内存，所以重启后节奏不丢，不会每次启动全跑一遍）。
  - **失败隔离**：一个阶段抛异常只记录并继续下一个 —— 一个源抓挂了不该
    拖垮 synthesize。异常落 pipeline_runs.error，不吞。
  - **可观测**：每阶段的返回统计原样入库，"这一轮做了什么"可查。

阶段函数就是 CLI 用的那些 run_*，服务只调度不重新实现（主干是可重放的
pipeline，见 architecture.md §5）。CLI 仍然是同一批函数的另一个入口，
用于回填、重放、单阶段调试。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass

import psycopg

from .config import Config

log = logging.getLogger(__name__)

# 单实例互斥用的 advisory lock key（任意常数，全库唯一即可）
CYCLE_LOCK_KEY = 0x4E415031          # 'NAP1'


@dataclass
class Stage:
    """一个管线阶段。fn 可以是同步或 async，返回统计 dict。"""
    name: str
    min_interval: int                      # 秒；距上次**开始**多久后才再跑
    fn: Callable[[psycopg.Connection, Config], object]
    only_if_work: bool = False             # 仅当本轮前序阶段有产出时才跑


def _last_start(conn: psycopg.Connection, stage: str) -> float | None:
    """距上次开始的秒数（无记录返回 None）。用开始时间而非结束时间：
    长任务不该因为自己跑得久就把下一次挤到更晚。"""
    with conn.cursor() as cur:
        cur.execute("""SELECT extract(epoch FROM now() - max(started_at))
                       FROM pipeline_runs WHERE stage=%s""", (stage,))
        r = cur.fetchone()[0]
    return float(r) if r is not None else None


def _work_done(stats: dict) -> bool:
    """阶段是否真的产出了东西 —— 决定 only_if_work 的阶段跑不跑。
    统计里的计数字段任一非零即算有产出（errors 不算产出）。"""
    return any(v for k, v in stats.items()
               if k != "errors" and isinstance(v, (int, float)))


def run_cycle(conn: psycopg.Connection, cfg: Config, stages: list[Stage],
              force: bool = False, only: str | None = None) -> dict:
    """推进一轮。拿不到锁直接返回（不排队、不等待：下一 tick 自然重试）。"""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (CYCLE_LOCK_KEY,))
        if not cur.fetchone()[0]:
            log.info("cycle skipped: another run holds the lock")
            return {"cycle": None, "skipped": "locked", "stages": {}}
        cur.execute("SELECT nextval('pipeline_cycle_seq')")
        cycle = cur.fetchone()[0]
    conn.commit()

    out: dict[str, object] = {"cycle": cycle, "stages": {}}
    produced = False
    try:
        for st in stages:
            if only and st.name != only:
                continue
            if not force and not only:
                age = _last_start(conn, st.name)
                if age is not None and age < st.min_interval:
                    out["stages"][st.name] = {"skipped": "not due"}
                    continue
                if st.only_if_work and not produced:
                    out["stages"][st.name] = {"skipped": "no work this cycle"}
                    continue
            stats, err = _run_stage(conn, cfg, cycle, st)
            out["stages"][st.name] = stats if err is None else {"error": err}
            if err is None and _work_done(stats):
                produced = True
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (CYCLE_LOCK_KEY,))
        conn.commit()
    return out


def _run_stage(conn: psycopg.Connection, cfg: Config, cycle: int,
               st: Stage) -> tuple[dict, str | None]:
    """单阶段执行：先落 started 行（崩溃也留痕），再按结果补 finished/error。"""
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO pipeline_runs (cycle, stage) VALUES (%s,%s)
                       RETURNING id""", (cycle, st.name))
        run_id = cur.fetchone()[0]
    conn.commit()

    stats: dict = {}
    err: str | None = None
    try:
        r = st.fn(conn, cfg)
        if inspect.isawaitable(r):
            r = asyncio.run(_await(r))
        stats = dict(r) if isinstance(r, dict) else {"result": str(r)}
        log.info("stage %s: %s", st.name, stats)
    except Exception as exc:                      # 阶段级隔离：记录，不中断整轮
        conn.rollback()
        err = f"{type(exc).__name__}: {exc}"[:1000]
        log.exception("stage %s failed", st.name)

    with conn.cursor() as cur:
        cur.execute("""UPDATE pipeline_runs SET finished_at=now(), stats=%s, error=%s
                       WHERE id=%s""",
                    (psycopg.types.json.Jsonb(stats), err, run_id))
    conn.commit()
    return stats, err


async def _await(x):
    return await x


# ── 默认阶段表 ─────────────────────────────────────────────
# 顺序即依赖：采集 → 抽取 → 归并 → 消歧 → 转述 → 合成 → 快照。
# 间隔是各阶段"值得再看一次"的节奏，不是它们的耗时。无待办时这些函数
# 本来就是一条查询后立即返回，所以宁可勤跑也不要攒着。

def default_stages(cfg: Config, model: str | None = None) -> list[Stage]:
    """构造默认阶段表。LLM 客户端在阶段内部惰性构造 —— 不装 Agent SDK
    也能跑纯确定性的阶段（ingest / syndicate / lifecycle）。"""

    def ingest(conn, cfg):
        from dataclasses import asdict

        from .ingest import run_once
        return asdict(run_once(conn, cfg))

    def extract(conn, cfg):
        from .llm_extract import ClaudeExtractor, run_extraction
        return run_extraction(conn, cfg, ClaudeExtractor(model=model), limit=40)

    def assign(conn, cfg):
        from .merge import ClaudeJudge, run_assignment
        return run_assignment(conn, cfg, ClaudeJudge(model=model), limit=50)

    def resolve(conn, cfg):
        from .entity_resolve import ClaudeResolver, run_resolution
        return run_resolution(conn, ClaudeResolver(model=model), limit=40)

    def syndicate(conn, cfg):
        from .syndicate import run_syndication
        return run_syndication(conn)

    def synthesize(conn, cfg):
        from .synth import ClaudeSynthesizer, run_synthesis
        return run_synthesis(conn, ClaudeSynthesizer(model=model), limit=10)

    def lifecycle(conn, cfg):
        from .lifecycle import run_lifecycle
        return run_lifecycle(conn)

    return [
        Stage("ingest", 3600, ingest),
        Stage("extract", 600, extract),
        Stage("assign", 600, assign),
        # 消歧改的是实体表，影响召回质量而非时效；跑太勤是浪费
        Stage("resolve-entities", 6 * 3600, resolve),
        Stage("syndicate", 3600, syndicate),
        Stage("synthesize", 1800, synthesize),
        # 生命周期：本轮有动静才值得看谁该休眠（没动静不可能有新的休眠触发）
        Stage("lifecycle", 3600, lifecycle, only_if_work=True),
    ]
