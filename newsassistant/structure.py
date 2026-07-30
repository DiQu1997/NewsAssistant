"""结构检测 —— 视图由数据里检测到的结构自动选择（D4，docs/views.md §2）。

这是"硬编码结构，永不硬编码主题"（D2）在展示层的落点：没有任何一处
"半导体用链路图、地缘用阶梯图"的声明。检测器只问结构性的问题 ——
实体间是不是有稳定的有向依赖？共现是不是够稠密？同一件事多个信源立场
是不是打架？——回答由数据给出，新领域自然长出属于它的视图。

两条设计约定：

1. **不触发也要说明理由。** 每个检测器无论触发与否都返回一条记录，带上
   实测值和阈值。"为什么这个频道没有链路图"必须能被回答，否则用户只会
   以为页面坏了 —— 而真实原因往往是"抽取出的 who/whom 还不够多"。
2. **触发条件写成显式阈值，不写成手感。** 阈值都在模块常量里，改一个
   数就能重新校准；评估集到位后它们该被数据校准，而不是靠盯着页面调。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import psycopg

log = logging.getLogger(__name__)

# ── 触发阈值（显式，可校准） ──────────────────────────────
NET_MIN_NODES = 6          # 共现网络：少于这么多节点，画出来不如列清单
NET_MIN_DENSITY = 0.10     # 边数 / 最大可能边数
NET_UBIQUITY = 0.6         # 出现在超过这么大比例故事里的实体不进网络（连一切=无信息）
CHAIN_MIN_EDGES = 3        # 有向链路：稳定边（重复出现的 who→whom）条数
CHAIN_MIN_REPEAT = 2       # 一条边至少被这么多断言支持才算"稳定"
CHAIN_MIN_DEPTH = 3        # 拓扑层数；两层的图是二部关系，不是链路
MATRIX_MIN_ROWS = 3        # 热力矩阵：两个离散维度各自的最小基数
MATRIX_MIN_COLS = 5
COMP_MIN_PARTS = 3         # 构成条：份额分解的最小类别数
COMP_MAX_TOP_SHARE = 0.9   # 一家独占九成时，构成条只是一根长条
DISAGREE_MIN_STORIES = 2   # 分歧矩阵：至少这么多个故事内部存在跨源立场差
GEO_MIN_SHARE = 0.25       # 地理层：带 where 的断言占比


@dataclass
class Detection:
    view: str
    triggered: bool
    reason: str                              # 触发或未触发的实测理由
    weight: float = 0.0                      # 布局用：最重者当主舞台
    evidence: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    renderable: bool = True                  # 检测到了但刻意不渲染（见 D13）


def _canonical_entity_map(conn: psycopg.Connection) -> dict[str, str]:
    """字面 → 规范名（穿透 merged_into）。who/whom 是自由文本，
    要靠它落到已消歧的实体上，否则 'the Fed' 和 'Federal Reserve' 是两个节点。"""
    with conn.cursor() as cur:
        cur.execute("""SELECT lower(e.canonical_name), e2.canonical_name
                       FROM entities e
                       JOIN entities e2 ON e2.id = coalesce(e.merged_into, e.id)""")
        m = dict(cur.fetchall())
        cur.execute("""SELECT lower(a.alias), e2.canonical_name
                       FROM entities e
                       CROSS JOIN LATERAL unnest(e.aliases) AS a(alias)
                       JOIN entities e2 ON e2.id = coalesce(e.merged_into, e.id)""")
        m.update(dict(cur.fetchall()))
    return m


def detect(conn: psycopg.Connection, story_ids: list[int]) -> list[Detection]:
    """对一个数据切片（通常是一个频道的查询结果）跑全部检测器。"""
    if not story_ids:
        return [Detection(v, False, "切片为空") for v in
                ("network", "chain", "matrix", "composition", "disagreement",
                 "open_questions", "geo", "coaxial")]
    dets = [
        _network(conn, story_ids),
        _chain(conn, story_ids),
        _matrix(conn, story_ids),
        _composition(conn, story_ids),
        _disagreement(conn, story_ids),
        _open_questions(conn, story_ids),
        _geo(conn, story_ids),
        _coaxial(conn, story_ids),
    ]
    return sorted(dets, key=lambda d: (d.triggered, d.weight), reverse=True)


# ── 共现网络：实体间无向关系稠密 ──────────────────────────
def _network(conn: psycopg.Connection, sids: list[int]) -> Detection:
    with conn.cursor() as cur:
        cur.execute("""
            WITH se AS (SELECT DISTINCT se.story_id,
                               coalesce(e.merged_into, e.id) AS eid
                        FROM story_entities se JOIN entities e ON e.id=se.entity_id
                        WHERE se.story_id = ANY(%s)),
                 df AS (SELECT eid, count(*) AS n FROM se GROUP BY eid)
            SELECT e.canonical_name, df.n FROM df JOIN entities e ON e.id=df.eid
            ORDER BY df.n DESC""", (sids,))
        ents = cur.fetchall()
        # 出现在过半故事里的实体连接一切，边带不出信息 —— 排除
        cutoff = max(2, len(sids) * NET_UBIQUITY)
        keep = {name for name, n in ents if n < cutoff}
        cur.execute("""
            WITH se AS (SELECT DISTINCT se.story_id, e2.canonical_name AS name
                        FROM story_entities se
                        JOIN entities e ON e.id=se.entity_id
                        JOIN entities e2 ON e2.id = coalesce(e.merged_into, e.id)
                        WHERE se.story_id = ANY(%s))
            SELECT a.name, b.name, count(*) FROM se a JOIN se b
              ON a.story_id=b.story_id AND a.name < b.name
            GROUP BY 1,2 ORDER BY 3 DESC LIMIT 300""", (sids,))
        edges = [{"a": a, "b": b, "w": w} for a, b, w in cur.fetchall()
                 if a in keep and b in keep]

    nodes = sorted({x for e in edges for x in (e["a"], e["b"])})
    n = len(nodes)
    density = len(edges) / (n * (n - 1) / 2) if n > 1 else 0.0
    ev = {"nodes": n, "edges": len(edges), "density": round(density, 3),
          "excluded_ubiquitous": len(ents) - len(keep),
          "thresholds": {"nodes": NET_MIN_NODES, "density": NET_MIN_DENSITY}}
    if n < NET_MIN_NODES or density < NET_MIN_DENSITY:
        return Detection("network", False,
                         f"节点 {n}、密度 {density:.2f} 未达阈值"
                         f"（需 ≥{NET_MIN_NODES} 且 ≥{NET_MIN_DENSITY}）", evidence=ev)
    deg: dict[str, int] = {}
    for e in edges:
        deg[e["a"]] = deg.get(e["a"], 0) + e["w"]
        deg[e["b"]] = deg.get(e["b"], 0) + e["w"]
    top = sorted(deg, key=deg.get, reverse=True)[:26]
    return Detection("network", True, f"{n} 个实体、密度 {density:.2f} 的无向共现",
                     weight=min(1.0, density * 2) * 0.8, evidence=ev,
                     payload={"nodes": [{"name": x, "degree": deg[x]} for x in top],
                              "edges": [e for e in edges
                                        if e["a"] in set(top) and e["b"] in set(top)][:120]})


# ── 有向链路：稳定的上下游依赖，可拓扑排序 ────────────────
def _chain(conn: psycopg.Connection, sids: list[int]) -> Detection:
    canon = _canonical_entity_map(conn)
    with conn.cursor() as cur:
        cur.execute("""SELECT struct->>'who', struct->>'whom', struct->>'did'
                       FROM claims WHERE story_id = ANY(%s)
                         AND struct->>'who' IS NOT NULL
                         AND struct->>'whom' IS NOT NULL""", (sids,))
        raw = cur.fetchall()

    counts: dict[tuple[str, str], int] = {}
    verbs: dict[tuple[str, str], set] = {}
    for who, whom, did in raw:
        a, b = canon.get((who or "").lower()), canon.get((whom or "").lower())
        if not a or not b or a == b:
            continue                      # 落不到已知实体的自由文本不进图
        counts[(a, b)] = counts.get((a, b), 0) + 1
        verbs.setdefault((a, b), set()).add((did or "").strip()[:24])

    stable = {k: v for k, v in counts.items() if v >= CHAIN_MIN_REPEAT}
    ev = {"claims_with_who_whom": len(raw), "resolved_edges": len(counts),
          "stable_edges": len(stable),
          "thresholds": {"stable_edges": CHAIN_MIN_EDGES, "repeat": CHAIN_MIN_REPEAT,
                         "depth": CHAIN_MIN_DEPTH}}
    if len(stable) < CHAIN_MIN_EDGES:
        return Detection("chain", False,
                         f"稳定有向边 {len(stable)} 条（{len(raw)} 条断言带 who/whom，"
                         f"其中 {len(counts)} 条落到已知实体）", evidence=ev)

    layers, cyclic = _topo_layers(stable)
    ev["depth"] = len(layers)
    ev["edges_in_cycles"] = cyclic
    if len(layers) < CHAIN_MIN_DEPTH:
        return Detection("chain", False,
                         f"拓扑只有 {len(layers)} 层 —— 两层是二部关系不是链路",
                         evidence=ev)
    return Detection("chain", True,
                     f"{len(stable)} 条稳定有向边，可排成 {len(layers)} 层",
                     weight=0.95, evidence=ev,
                     payload={"layers": layers,
                              "edges": [{"from": a, "to": b, "w": w,
                                         "kinds": sorted(verbs[(a, b)])[:3]}
                                        for (a, b), w in sorted(stable.items(),
                                                                key=lambda x: -x[1])]})


def _topo_layers(edges: dict[tuple[str, str], int]) -> tuple[list[list[str]], int]:
    """Kahn 分层。环上的边直接丢弃并计数 —— 有环说明它不是依赖链，
    与其画一张缠住的图，不如把丢掉多少条如实报出来。"""
    nodes = {x for e in edges for x in e}
    indeg = {n: 0 for n in nodes}
    out: dict[str, list[str]] = {n: [] for n in nodes}
    for (a, b) in edges:
        out[a].append(b)
        indeg[b] += 1
    layers, placed = [], set()
    frontier = sorted(n for n in nodes if indeg[n] == 0)
    while frontier:
        layers.append(frontier)
        placed |= set(frontier)
        nxt = set()
        for n in frontier:
            for m in out[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    nxt.add(m)
        frontier = sorted(nxt)
    dropped = sum(1 for (a, b) in edges if a not in placed or b not in placed)
    return layers, dropped


# ── 热力矩阵：两个离散维度 + 强度 ─────────────────────────
def _matrix(conn: psycopg.Connection, sids: list[int]) -> Detection:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT src.key, date_trunc('day', sd.added_at)::date, count(*)
            FROM story_documents sd
            JOIN documents d ON d.id=sd.document_id
            JOIN sources src ON src.id=d.source_id
            WHERE sd.story_id = ANY(%s) AND sd.added_at > now() - interval '30 days'
            GROUP BY 1,2 ORDER BY 2""", (sids,))
        cells = [(k, day.isoformat(), n) for k, day, n in cur.fetchall()]
    rows = sorted({c[0] for c in cells})
    cols = sorted({c[1] for c in cells})
    ev = {"rows": len(rows), "cols": len(cols), "cells": len(cells),
          "thresholds": {"rows": MATRIX_MIN_ROWS, "cols": MATRIX_MIN_COLS}}
    if len(rows) < MATRIX_MIN_ROWS or len(cols) < MATRIX_MIN_COLS:
        return Detection("matrix", False,
                         f"源 {len(rows)} × 天 {len(cols)} 未达阈值", evidence=ev)
    return Detection("matrix", True, f"源 × 日 的 {len(rows)}×{len(cols)} 强度矩阵",
                     weight=0.55, evidence=ev,
                     payload={"rows": rows, "cols": cols,
                              "cells": [{"r": r, "c": c, "v": v} for r, c, v in cells]})


# ── 构成条：单维度按份额分解 ──────────────────────────────
def _composition(conn: psycopg.Connection, sids: list[int]) -> Detection:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT src.key, src.evidence_tier, count(*)
            FROM story_documents sd
            JOIN documents d ON d.id=sd.document_id
            JOIN documents orig ON orig.id = coalesce(d.syndication_of, d.id)
            JOIN sources src ON src.id=orig.source_id
            WHERE sd.story_id = ANY(%s)
            GROUP BY 1,2 ORDER BY 3 DESC""", (sids,))
        parts = [{"name": k, "tier": t, "n": n} for k, t, n in cur.fetchall()]
    total = sum(p["n"] for p in parts)
    top = parts[0]["n"] / total if total else 1.0
    ev = {"parts": len(parts), "total": total, "top_share": round(top, 3),
          "thresholds": {"parts": COMP_MIN_PARTS, "max_top_share": COMP_MAX_TOP_SHARE}}
    if len(parts) < COMP_MIN_PARTS or top > COMP_MAX_TOP_SHARE:
        return Detection("composition", False,
                         f"{len(parts)} 个来源、首位占比 {top:.0%} —— 分解不出结构",
                         evidence=ev)
    return Detection("composition", True,
                     f"{len(parts)} 个独立信源的覆盖份额分解（转述已折叠回源头）",
                     weight=0.4, evidence=ev,
                     payload={"parts": parts, "total": total})


# ── 分歧矩阵：同一故事多源立场不一（核心资产） ────────────
def _disagreement(conn: psycopg.Connection, sids: list[int]) -> Detection:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.id, s.title, src.key, avg(c.stance)::numeric(4,2), count(*)
            FROM claims c
            JOIN stories s ON s.id=c.story_id
            JOIN documents d ON d.id=c.document_id
            JOIN sources src ON src.id=d.source_id
            WHERE c.story_id = ANY(%s) AND c.stance IS NOT NULL
            GROUP BY 1,2,3 ORDER BY 1""", (sids,))
        rows = cur.fetchall()
    by_story: dict[int, dict] = {}
    for sid, title, src, avg, n in rows:
        st = by_story.setdefault(sid, {"id": sid, "title": title, "sources": {}})
        st["sources"][src] = {"stance": float(avg), "claims": n}
    split = [s for s in by_story.values() if len(s["sources"]) >= 2
             and (max(x["stance"] for x in s["sources"].values())
                  - min(x["stance"] for x in s["sources"].values())) >= 1.0]
    ev = {"stories_with_stance": len(by_story), "stories_split": len(split),
          "thresholds": {"stories": DISAGREE_MIN_STORIES, "spread": 1.0}}
    if len(split) < DISAGREE_MIN_STORIES:
        return Detection("disagreement", False,
                         f"{len(split)} 个故事存在跨源立场差（需 ≥{DISAGREE_MIN_STORIES}）；"
                         f"立场一致不是缺陷，是这批数据的事实", evidence=ev)
    split.sort(key=lambda s: -(max(x["stance"] for x in s["sources"].values())
                               - min(x["stance"] for x in s["sources"].values())))
    srcs = sorted({k for s in split for k in s["sources"]})
    return Detection("disagreement", True, f"{len(split)} 个故事的信源立场不一致",
                     weight=0.7, evidence=ev,
                     payload={"sources": srcs, "stories": split[:14]})


# ── 未解问题：恒在，位置靠后 ──────────────────────────────
def _open_questions(conn: psycopg.Connection, sids: list[int]) -> Detection:
    with conn.cursor() as cur:
        cur.execute("""SELECT id, title, open_questions FROM stories
                       WHERE id = ANY(%s) AND open_questions IS NOT NULL
                         AND jsonb_array_length(open_questions) > 0""", (sids,))
        items = [{"story_id": i, "title": t, "questions": q} for i, t, q in cur.fetchall()]
    n = sum(len(x["questions"]) for x in items)
    if not n:
        return Detection("open_questions", False, "本切片的故事都没有开放问题",
                         evidence={"questions": 0})
    return Detection("open_questions", True, f"{n} 个开放问题",
                     weight=0.2, evidence={"questions": n, "stories": len(items)},
                     payload={"items": items[:20]})


# ── 地理：检测得到，但刻意不渲染（D13） ───────────────────
def _geo(conn: psycopg.Connection, sids: list[int]) -> Detection:
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) FILTER (WHERE struct->>'where' IS NOT NULL),
                              count(*) FROM claims WHERE story_id = ANY(%s)""", (sids,))
        with_where, total = cur.fetchone()
    share = with_where / total if total else 0.0
    ev = {"claims_with_where": with_where, "claims": total, "share": round(share, 3)}
    if share < GEO_MIN_SHARE:
        return Detection("geo", False, f"带位置的断言占 {share:.0%}，密度不足", evidence=ev)
    return Detection("geo", True,
                     f"带位置的断言占 {share:.0%} —— 结构成立，但按 D13 不画手绘地图，"
                     f"位置先由命名承载，等接真实地理图层",
                     weight=0.0, evidence=ev, renderable=False)


# ── 共轴时间带 / 背离榜：需要外生数值序列 ─────────────────
def _coaxial(conn: psycopg.Connection, sids: list[int]) -> Detection:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.observations') IS NOT NULL")
        has_table = cur.fetchone()[0]
    return Detection("coaxial", False,
                     "没有可与叙事对齐的外生数值序列：L3 数值源尚未入库"
                     "（observations 表未建，见路线图）",
                     evidence={"observations_table": bool(has_table)})
