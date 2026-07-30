"""管线编排测试 —— 假阶段，不碰网络/SDK/LLM。

验证的是编排本身的四条承诺：顺序、节奏、失败隔离、互斥。
"""
from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from newsassistant import db
from newsassistant.config import Config
from newsassistant.pipeline import CYCLE_LOCK_KEY, Stage, run_cycle

TEST_DB = "postgresql://postgres:postgres@127.0.0.1:5432/newsassistant_test"


@pytest.fixture()
def conn():
    try:
        c = db.connect(TEST_DB)
    except psycopg.OperationalError:
        pytest.skip("no local postgres")
    db.migrate(c)
    with c.cursor() as cur:
        cur.execute("TRUNCATE pipeline_runs RESTART IDENTITY")
    c.commit()
    yield c
    c.close()


@pytest.fixture()
def cfg(tmp_path: Path):
    return Config(database_url=TEST_DB, data_dir=tmp_path)


def _stages(order: list[str], **kw) -> list[Stage]:
    def make(name, result):
        def fn(conn, cfg):
            order.append(name)
            if isinstance(result, Exception):
                raise result
            return result
        return fn
    return [Stage(name, kw.get(f"{name}_interval", 0), make(name, res),
                  only_if_work=kw.get(f"{name}_only_if_work", False))
            for name, res in kw["specs"]]


def test_order_and_recording(conn, cfg):
    order: list[str] = []
    stages = _stages(order, specs=[("a", {"new_docs": 2}), ("b", {"docs": 0})])
    r = run_cycle(conn, cfg, stages)

    assert order == ["a", "b"]                  # 顺序即依赖
    assert r["stages"]["a"] == {"new_docs": 2}
    with conn.cursor() as cur:
        cur.execute("""SELECT stage, stats, error, finished_at IS NOT NULL
                       FROM pipeline_runs ORDER BY id""")
        rows = cur.fetchall()
    assert [x[0] for x in rows] == ["a", "b"]
    assert rows[0][1] == {"new_docs": 2} and rows[0][2] is None and rows[0][3]
    # 同一轮的阶段共享 cycle 号
    with conn.cursor() as cur:
        cur.execute("SELECT count(DISTINCT cycle) FROM pipeline_runs")
        assert cur.fetchone()[0] == 1


def test_interval_skips_until_due(conn, cfg):
    order: list[str] = []
    stages = _stages(order, specs=[("a", {"n": 1})], a_interval=3600)
    run_cycle(conn, cfg, stages)
    run_cycle(conn, cfg, stages)                # 立刻再跑：未到期
    assert order == ["a"]

    # force 无视节奏；--stage 同理（单阶段是人工干预，不该被节奏挡住）
    run_cycle(conn, cfg, stages, force=True)
    run_cycle(conn, cfg, stages, only="a")
    assert order == ["a", "a", "a"]


def test_failure_is_isolated_and_recorded(conn, cfg):
    order: list[str] = []
    stages = _stages(order, specs=[("a", RuntimeError("boom")), ("b", {"n": 1})])
    r = run_cycle(conn, cfg, stages)

    assert order == ["a", "b"]                  # a 炸了不挡 b
    assert "RuntimeError: boom" in r["stages"]["a"]["error"]
    with conn.cursor() as cur:
        cur.execute("SELECT error FROM pipeline_runs WHERE stage='a'")
        assert "boom" in cur.fetchone()[0]      # 异常落库，不吞


def test_only_if_work_needs_upstream_output(conn, cfg):
    order: list[str] = []
    # 前序阶段零产出（errors 不算产出）→ 快照不跑
    stages = _stages(order, specs=[("a", {"docs": 0, "errors": 3}), ("snap", {"ok": 1})],
                     snap_only_if_work=True)
    run_cycle(conn, cfg, stages)
    assert order == ["a"]

    order.clear()
    stages = _stages(order, specs=[("a", {"docs": 5}), ("snap", {"ok": 1})],
                     snap_only_if_work=True)
    run_cycle(conn, cfg, stages)
    assert order == ["a", "snap"]


def test_cycle_is_mutually_exclusive(conn, cfg):
    """互斥靠 Postgres advisory lock：另一个连接持锁时整轮跳过，
    不排队也不等待 —— 下一 tick 自然重试。"""
    other = db.connect(TEST_DB)
    with other.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", (CYCLE_LOCK_KEY,))
    other.commit()
    try:
        order: list[str] = []
        r = run_cycle(conn, cfg, _stages(order, specs=[("a", {"n": 1})]))
        assert r["skipped"] == "locked" and order == []
    finally:
        with other.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (CYCLE_LOCK_KEY,))
        other.commit()
        other.close()

    # 锁释放后照常推进（且上一次跳过没有留下半截记录）
    order2: list[str] = []
    run_cycle(conn, cfg, _stages(order2, specs=[("a", {"n": 1})]))
    assert order2 == ["a"]
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pipeline_runs")
        assert cur.fetchone()[0] == 1


def test_async_stage_is_awaited(conn, cfg):
    """阶段函数可以是 async（抽取/归并/合成都是）—— 编排层负责跑完它。"""
    async def afn(conn, cfg):
        return {"docs": 7}

    r = run_cycle(conn, cfg, [Stage("a", 0, afn)])
    assert r["stages"]["a"] == {"docs": 7}
