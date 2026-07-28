"""转述溯源（确定性部分，零 LLM）—— docs/architecture.md §2。

breadth（独立信源数）的命门：50 家转发同一通稿，广度是 1 不是 50。

采集层已经把 simhash 汉明距离 ≤3 的文档标成 status='near_dup'，
near_dup_of 指向组内最早那篇 ok 文档（_find_near 只扫 ok，所以组是星形，
不存在链）。这里做的判决是把"近重"细分为两类：

- **跨源近重 = 转述**：syndication_of ← near_dup_of（组 origin）。
- **同源近重 = 更新/更正**：同一家媒体改三个词重发不是转述，syndication_of 留空。

阈值之外的宽松转述（改写幅度大、跨语言）需要 LLM 判决 —— 留在路线图，
本模块只做零成本、可反复重跑的确定性部分。幂等：UPDATE 带 IS DISTINCT FROM 守卫。
"""
from __future__ import annotations

import logging

import psycopg

log = logging.getLogger(__name__)


def run_syndication(conn: psycopg.Connection) -> dict:
    """近重组内跨源判转述。返回 {marked, same_source, total_near}。"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT count(*),
                   count(*) FILTER (WHERE d.source_id = o.source_id)
            FROM documents d JOIN documents o ON o.id = d.near_dup_of
            WHERE d.status = 'near_dup'""")
        total, same = cur.fetchone()
        cur.execute("""
            UPDATE documents d SET syndication_of = d.near_dup_of
            FROM documents o
            WHERE o.id = d.near_dup_of
              AND d.status = 'near_dup'
              AND d.source_id <> o.source_id
              AND d.syndication_of IS DISTINCT FROM d.near_dup_of""")
        marked = cur.rowcount
    conn.commit()
    stats = {"marked": marked, "same_source": same, "total_near": total}
    log.info("syndication: %s", stats)
    return stats
