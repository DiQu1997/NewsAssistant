"""频道 = 保存的查询（D3，007_channels.sql）。

这个模块只有一件事：把一行 JSON 查询编译成一条参数化 SQL。它**不认识任何
主题** —— 认识的是"实体命中""文本匹配""标量阈值""时间窗""排序"这些结构。
主题（哪些实体、哪些关键词）是 channels 表里的数据。所以新增频道是插一行，
不是改代码；一个频道能问出什么，取决于系统有什么结构，而不是谁写过哪段 if。

未知的查询键一律报错而不是忽略：一个拼错键名的频道应该立刻暴露，
而不是安静地退化成"匹配全部故事"——后者看起来能用，实际全错。
"""
from __future__ import annotations

import logging
from pathlib import Path

import psycopg

log = logging.getLogger(__name__)

# 允许的查询键 —— 白名单即契约
QUERY_KEYS = {
    "any_entities",    # 命中任一实体（穿透 merged_into 别名）
    "all_entities",    # 命中全部实体
    "text",            # 标题或断言全文匹配（大小写不敏感）
    "min_docs",        # 标量阈值
    "min_breadth",
    "max_consensus",   # 分歧度频道：一致度上限
    "min_velocity",
    "window_days",     # 只看这么多天内有更新的故事
    "order",           # updated | velocity | docs | breadth | consensus
    "limit",
}

ORDERS = {
    "updated":   "s.updated_at DESC",
    "velocity":  "(s.scalars->>'velocity')::numeric DESC NULLS LAST",
    "docs":      "(s.scalars->>'docs')::numeric DESC NULLS LAST",
    "breadth":   "(s.scalars->>'breadth')::numeric DESC NULLS LAST",
    # 分歧优先：一致度低的在前
    "consensus": "(s.scalars->>'consensus')::numeric ASC NULLS LAST",
    # 分量 = 体量 × 信源广度：持续的大事压过一日爆点。velocity 是导数，
    # 适合"现在什么在动"；weight 是积分，适合"这个板块什么重要"。
    "weight": "(coalesce((s.scalars->>'docs')::numeric, 0)"
              " * (1 + coalesce((s.scalars->>'breadth')::numeric, 0)))"
              " DESC NULLS LAST",
}


class BadQuery(ValueError):
    """频道查询非法 —— 拼错的键、未知的排序、类型不对。"""


def compile_query(query: dict, limit: int | None = None,
                  offset: int = 0) -> tuple[str, list]:
    """(SQL, params)。只产出参数化 SQL，值永不拼进字符串。"""
    unknown = set(query) - QUERY_KEYS
    if unknown:
        raise BadQuery(f"unknown query keys: {sorted(unknown)}")

    where = ["s.state = 'active'"]
    params: list = []

    # 下限缺省按 0 算：标量是归并后才写的，刚建的故事 scalars 为空，
    # 不该因为"还没算过"就被 min_docs:0 这种无害条件挡在门外。
    def scalar_at_least(key: str, field: str) -> None:
        if key in query:
            where.append(f"coalesce((s.scalars->>'{field}')::numeric, 0) >= %s")
            params.append(query[key])

    scalar_at_least("min_docs", "docs")
    scalar_at_least("min_breadth", "breadth")
    scalar_at_least("min_velocity", "velocity")
    # 上限不缺省：一致度未知 ≠ 一致度低。否则每个刚建的故事都会涌进分歧频道。
    if "max_consensus" in query:
        where.append("(s.scalars->>'consensus')::numeric <= %s")
        params.append(query["max_consensus"])
    if "window_days" in query:
        where.append("s.updated_at > now() - make_interval(days => %s)")
        params.append(query["window_days"])

    # 实体命中走 story_entities，并用 COALESCE 穿透别名链（D22）——
    # 频道写 "United Kingdom" 时 UK 的故事也该进来
    for key, need_all in (("any_entities", False), ("all_entities", True)):
        names = query.get(key)
        if not names:
            continue
        if not isinstance(names, list):
            raise BadQuery(f"{key} must be a list of entity names")
        hit = """SELECT count(DISTINCT lower(e2.canonical_name))
                 FROM story_entities se
                 JOIN entities e ON e.id = se.entity_id
                 JOIN entities e2 ON e2.id = coalesce(e.merged_into, e.id)
                 WHERE se.story_id = s.id AND lower(e2.canonical_name) = ANY(%s)"""
        where.append(f"({hit}) >= %s")
        params.append([n.lower() for n in names])
        params.append(len(set(n.lower() for n in names)) if need_all else 1)

    if query.get("text"):
        where.append("""(s.title ILIKE %s OR EXISTS (
                          SELECT 1 FROM claims c WHERE c.story_id = s.id
                            AND c.text ILIKE %s))""")
        params += [f"%{query['text']}%"] * 2

    order = query.get("order", "updated")
    if order not in ORDERS:
        raise BadQuery(f"unknown order: {order}")

    sql = f"""SELECT s.id, s.title, s.state, s.scalars, s.updated_at, s.synthesized_at
              FROM stories s
              WHERE {' AND '.join(where)}
              ORDER BY {ORDERS[order]}, s.id DESC
              LIMIT %s OFFSET %s"""
    params += [min(limit or query.get("limit") or 50, 200), offset]
    return sql, params


def channel_stories(conn: psycopg.Connection, query: dict, limit: int | None = None,
                    offset: int = 0) -> list[dict]:
    sql, params = compile_query(query, limit=limit, offset=offset)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def list_channels(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""SELECT key, name, query, palette, topics FROM channels
                       WHERE enabled ORDER BY position, key""")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_channel(conn: psycopg.Connection, key: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("""SELECT key, name, query, palette, topics FROM channels
                       WHERE key=%s AND enabled""", (key,))
        r = cur.fetchone()
        if not r:
            return None
        return dict(zip([d[0] for d in cur.description], r))


def sync_channels(conn: psycopg.Connection, path: Path) -> dict:
    """把 YAML 里的频道定义同步进库（幂等，同 sources sync 的形状）。
    编译一遍每个 query —— 坏查询在同步时就该失败，而不是等用户点开频道。"""
    import yaml

    spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = spec.get("channels", [])
    added = updated = 0
    for i, ch in enumerate(rows):
        compile_query(ch.get("query", {}))           # 提前失败
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO channels (key,name,query,palette,topics,position)
                           VALUES (%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (key) DO UPDATE SET
                             name=EXCLUDED.name, query=EXCLUDED.query,
                             palette=EXCLUDED.palette, topics=EXCLUDED.topics,
                             position=EXCLUDED.position
                           RETURNING (xmax = 0) AS inserted""",
                        (ch["key"], ch["name"],
                         psycopg.types.json.Jsonb(ch.get("query", {})),
                         psycopg.types.json.Jsonb(ch.get("palette", {})),
                         psycopg.types.json.Jsonb(ch.get("topics", [])), i))
            added += cur.fetchone()[0]
            updated += 1
    conn.commit()
    log.info("channels sync: %d rows (%d new)", updated, added)
    return {"channels": updated, "new": added}
