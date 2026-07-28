"""转述溯源（syndication tracing）—— 纯确定性，零 LLM。

为什么存在：breadth（独立信源数）是广度指标的命门 —— 50 家转发同一通稿，
独立信源数是 1 不是 50（docs/architecture.md §2、sources.md「独立性」）。

信号已在采集层备好：simhash 近重标记（documents.near_dup_of，汉明距 ≤3）。
本模块把近重边聚成组，按时间定出源头，把**跨源**的成员标为
syndication_of = 源头 —— 同源近重是更正/更新，不是转述，不标。

规则（确定性，可重放）：
- 组内源头 = 最早者（published_at 优先，NULL 最后；再看 fetched_at、id）
- syndication_of 永远指向组源头（扁平，不成链 —— 同 merged_into 树高 ≤1）
- 幂等：期望值与现值一致则不写；规则变化时会自动改写/清除旧标记
"""
from __future__ import annotations

import logging

import psycopg

log = logging.getLogger(__name__)


def find_groups(rows: list[tuple[int, int | None]]) -> list[list[int]]:
    """near_dup_of 边 → 连通分量（并查集）。rows: (id, near_dup_of)。

    传递闭包是必须的：A→B、C→B 是一组 {A,B,C}；C→A→B 的链也是一组。
    """
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]        # 路径减半
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    ids = {r[0] for r in rows}
    for doc_id, dup_of in rows:
        if dup_of is not None and dup_of in ids:
            union(doc_id, dup_of)
    groups: dict[int, list[int]] = {}
    for doc_id in ids:
        groups.setdefault(find(doc_id), []).append(doc_id)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def pick_origin(members: list[dict]) -> dict:
    """组源头 = 最早发布者。published_at 缺失排最后，再比 fetched_at、id。"""
    return min(members, key=lambda m: (
        m["published_at"] is None, m["published_at"] or m["fetched_at"],
        m["fetched_at"], m["id"]))


def run_syndication(conn: psycopg.Connection) -> dict:
    stats = {"groups": 0, "marked": 0, "cleared": 0, "unchanged": 0}
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, near_dup_of, source_id, published_at, fetched_at,
                   syndication_of
            FROM documents
            WHERE status='ok' AND (near_dup_of IS NOT NULL
               OR id IN (SELECT near_dup_of FROM documents
                         WHERE status='ok' AND near_dup_of IS NOT NULL))""")
        docs = {r[0]: {"id": r[0], "near_dup_of": r[1], "source_id": r[2],
                       "published_at": r[3], "fetched_at": r[4],
                       "syndication_of": r[5]} for r in cur.fetchall()}

        for group in find_groups([(d["id"], d["near_dup_of"])
                                  for d in docs.values()]):
            members = [docs[i] for i in group]
            origin = pick_origin(members)
            stats["groups"] += 1
            for m in members:
                # 同源近重 = 更正/更新，不是转述；源头自身也不标
                want = (origin["id"]
                        if m["id"] != origin["id"]
                           and m["source_id"] != origin["source_id"]
                        else None)
                if m["syndication_of"] == want:
                    stats["unchanged"] += 1
                    continue
                cur.execute("UPDATE documents SET syndication_of=%s WHERE id=%s",
                            (want, m["id"]))
                stats["marked" if want is not None else "cleared"] += 1
                if want:
                    log.info("syndication: doc %s ← origin %s", m["id"], want)
        conn.commit()
    return stats
