"""archive 阶段 —— 冷热分层与 Drive 归档，全程无 LLM。

设计约束：PG 与本地盘只保留热数据与指针，大块/历史数据归 rclone 远端。
每天一次做四件事：
  1. 正文冷迁：本地 content/ 里 mtime 超过 content_cold_days 的文件批量
     rclone move 到 <drive_remote>/content/（目录结构不变，ref 不变）；
     读取端 ContentStore.get() 冷层回落，上层无感。
  1b. 原始层出货：采集暂存的 raw/（gzip 的原始 HTML/PDF）整体迁
     <drive_remote>/raw/ —— 写后不读，不设热窗口。
  2. llm_calls 保留期：超过 llm_calls_keep_days 的行导出 JSONL.gz
     （按 id 区间命名，天然幂等）推 <drive_remote>/llm_calls/ 后删行。
  3. 每日备份：pg_dump -Fc 推 <drive_remote>/backup/，保留 backup_keep_days 天。

drive_remote 未配置、rclone 缺失或远端未登记 → 整阶段跳过（本地开发机）。
三件事各自捕获错误：备份失败不该拦住冷迁，反之亦然。
"""
from __future__ import annotations

import gzip
import json
import logging
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

import psycopg

from .config import Config

log = logging.getLogger(__name__)

# 单轮冷迁文件数上限：首次启用时存量上万，分几天消化，别让一轮跑几小时
_TIER_BATCH = 5000
_RCLONE_TIMEOUT = 1800


def _remote_ready(remote: str) -> bool:
    """rclone 在且远端已配置。纯本地路径远端（测试用）不查 listremotes。"""
    if not remote or not shutil.which("rclone"):
        return False
    if ":" not in remote:
        return True                     # rclone 本地后端，路径即远端
    name = remote.split(":", 1)[0] + ":"
    try:
        p = subprocess.run(["rclone", "listremotes"], capture_output=True,
                           timeout=30, text=True)
        return name in p.stdout.split()
    except Exception:
        return False


def _rclone(*args: str, timeout: int = _RCLONE_TIMEOUT) -> None:
    p = subprocess.run(["rclone", *args], capture_output=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(
            f"rclone {args[0]} failed: "
            f"{p.stderr.decode('utf-8', 'replace').strip()[:300]}")


# ── 1. 正文冷迁 ─────────────────────────────────────────────
def tier_content(data_dir: Path, remote: str, cold_days: int) -> dict:
    root = data_dir / "content"
    if not root.is_dir():
        return {"moved": 0}
    cutoff = time.time() - cold_days * 86400
    refs = sorted(
        str(f.relative_to(data_dir))
        for f in root.rglob("*.txt") if f.stat().st_mtime < cutoff
    )[:_TIER_BATCH]
    if not refs:
        return {"moved": 0}
    with tempfile.NamedTemporaryFile("w", suffix=".list", delete=False) as tf:
        tf.write("\n".join(refs))
        listfile = tf.name
    try:
        # move = 校验后删本地；失败则文件原地不动，无丢失窗口
        _rclone("move", str(data_dir), remote, "--files-from", listfile)
    finally:
        Path(listfile).unlink(missing_ok=True)
    # 清掉搬空的分桶目录，防其累积成千个空壳
    for d in root.iterdir():
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return {"moved": len(refs), "truncated": len(refs) == _TIER_BATCH}


# ── 1b. 原始层出货 ───────────────────────────────────────────
def ship_raw(data_dir: Path, remote: str) -> dict:
    """把暂存的原始 HTML/PDF 全部迁去远端。原始层生来就是冷的（写后不读），
    不设热窗口；--min-age 避开正在进行的采集轮的写入沿。"""
    root = data_dir / "raw"
    if not root.is_dir():
        return {"shipped": 0}
    cutoff = time.time() - 3600
    n = sum(1 for f in root.rglob("*.gz") if f.stat().st_mtime < cutoff)
    if not n:
        return {"shipped": 0}
    _rclone("move", str(root), f"{remote}/raw",
            "--min-age", "1h", "--delete-empty-src-dirs")
    return {"shipped": n}


# ── 2. llm_calls 归档 ────────────────────────────────────────
def archive_llm_calls(conn: psycopg.Connection, remote: str,
                      keep_days: int) -> dict:
    with conn.cursor() as cur:
        cur.execute("""SELECT id, purpose, model, input, output,
                              tokens_in, tokens_out, at
                       FROM llm_calls
                       WHERE at < now() - make_interval(days => %s)
                       ORDER BY id""", (keep_days,))
        rows = cur.fetchall()
    if not rows:
        return {"archived": 0}
    lo, hi = rows[0][0], rows[-1][0]
    name = f"llm_calls-{lo:08d}-{hi:08d}.jsonl.gz"
    with tempfile.NamedTemporaryFile(suffix=".jsonl.gz", delete=False) as tf:
        tmp = Path(tf.name)
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            for (rid, purpose, model, inp, out, tin, tout, at) in rows:
                f.write(json.dumps({
                    "id": rid, "purpose": purpose, "model": model,
                    "input": inp, "output": out,
                    "tokens_in": tin, "tokens_out": tout,
                    "at": at.isoformat()}, ensure_ascii=False) + "\n")
        _rclone("copyto", str(tmp), f"{remote}/llm_calls/{name}")
    finally:
        tmp.unlink(missing_ok=True)
    # 先上传成功才删行；按已导出的 id 区间删，与查询窗口漂移无关
    with conn.cursor() as cur:
        cur.execute("DELETE FROM llm_calls WHERE id BETWEEN %s AND %s", (lo, hi))
    conn.commit()
    return {"archived": len(rows), "file": name}


# ── 3. 每日 pg_dump ──────────────────────────────────────────
def backup_db(database_url: str, remote: str, keep_days: int) -> dict:
    name = f"na-{datetime.now():%Y%m%d}.dump"
    with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as tf:
        tmp = Path(tf.name)
    try:
        p = subprocess.run(["pg_dump", "-Fc", "-f", str(tmp), database_url],
                           capture_output=True, timeout=1800)
        if p.returncode != 0:
            raise RuntimeError(
                f"pg_dump failed: "
                f"{p.stderr.decode('utf-8', 'replace').strip()[:300]}")
        size = tmp.stat().st_size
        _rclone("copyto", str(tmp), f"{remote}/backup/{name}")
    finally:
        tmp.unlink(missing_ok=True)
    try:
        _rclone("delete", f"{remote}/backup", "--min-age", f"{keep_days}d")
    except RuntimeError as e:
        log.warning("backup prune: %s", e)   # 清旧失败只是多占空间，不算失败
    return {"backup": name, "bytes": size}


def run_archive(conn: psycopg.Connection, cfg: Config) -> dict:
    if not cfg.drive_remote:
        return {"skipped": "drive_remote 未配置"}
    if not _remote_ready(cfg.drive_remote):
        log.warning("archive: rclone 或远端 %r 不可用，跳过", cfg.drive_remote)
        return {"skipped": f"rclone/{cfg.drive_remote} 不可用"}

    stats: dict = {"errors": 0}
    for key, fn in (
            ("tier", lambda: tier_content(
                cfg.data_dir, cfg.drive_remote, cfg.content_cold_days)),
            ("raw", lambda: ship_raw(cfg.data_dir, cfg.drive_remote)),
            ("llm_calls", lambda: archive_llm_calls(
                conn, cfg.drive_remote, cfg.llm_calls_keep_days)),
            ("backup", lambda: backup_db(
                cfg.database_url, cfg.drive_remote, cfg.backup_keep_days))):
        try:
            stats[key] = fn()
        except Exception as e:
            conn.rollback()
            log.exception("archive %s failed", key)
            stats[key] = {"error": f"{type(e).__name__}: {e}"[:200]}
            stats["errors"] += 1
    return stats
