"""故事生命周期 —— active → dormant → archived。

规则很简单：
  - 连续 N 天没有新文档归入 → dormant（休眠）
  - 休眠 M 天后仍无动静 → archived（归档）
  - 新文档归入时自动唤醒回 active（在 merge.py _apply_verdict 里做）

archived 故事不出现在默认频道查询里（channels.py 只查 active），
但数据完整保留，唤醒后综述/时间线/标量全部继续。
"""
from __future__ import annotations

import logging

import psycopg

log = logging.getLogger(__name__)

DORMANT_AFTER_DAYS = 7
ARCHIVE_AFTER_DAYS = 30


def run_lifecycle(conn: psycopg.Connection) -> dict:
    stats = {"dormant": 0, "archived": 0, "total_active": 0}

    with conn.cursor() as cur:
        # active → dormant：最后一次文档归入距今超过 N 天
        cur.execute("""
            UPDATE stories SET state='dormant', dormant_at=now()
            WHERE state='active'
              AND updated_at < now() - make_interval(days => %s)
            RETURNING id""", (DORMANT_AFTER_DAYS,))
        dormant_ids = [r[0] for r in cur.fetchall()]
        stats["dormant"] = len(dormant_ids)

        for sid in dormant_ids:
            cur.execute("""INSERT INTO story_events (story_id, kind, payload)
                           VALUES (%s, 'dormant', %s)""",
                        (sid, psycopg.types.json.Jsonb(
                            {"reason": f"no new documents for {DORMANT_AFTER_DAYS} days"})))

        # dormant → archived：休眠超过 M 天仍无动静
        cur.execute("""
            UPDATE stories SET state='archived'
            WHERE state='dormant'
              AND dormant_at < now() - make_interval(days => %s)
            RETURNING id""", (ARCHIVE_AFTER_DAYS,))
        archived_ids = [r[0] for r in cur.fetchall()]
        stats["archived"] = len(archived_ids)

        for sid in archived_ids:
            cur.execute("""INSERT INTO story_events (story_id, kind, payload)
                           VALUES (%s, 'archived', %s)""",
                        (sid, psycopg.types.json.Jsonb(
                            {"reason": f"dormant for {ARCHIVE_AFTER_DAYS} days"})))

        cur.execute("SELECT count(*) FROM stories WHERE state='active'")
        stats["total_active"] = cur.fetchone()[0]

    conn.commit()

    if dormant_ids:
        log.info("lifecycle: %d stories → dormant", len(dormant_ids))
    if archived_ids:
        log.info("lifecycle: %d stories → archived", len(archived_ids))

    return stats
