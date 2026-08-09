"""L4 层级归簇 —— 事件自下而上长成弧/传奇（docs/redesign-hierarchy.md）。

topics.py 涌现归簇模式的晋升版：不再局限于频道内的平面标签，而是全库
范围的**多父 DAG**——event（stories）归入 node，node 可再归入更高的
node，递归深度由 LLM 按需决定。词表（nodes 表）持久化 + reuse-first，
地图不因每轮重聚而漂移。

三条结构性纪律（契约，代码强制，不是判断规则）：
1. 无单子链 —— 新节点必须 ≥2 个成员；只有一个孩子的"归纳"没有信息增量。
2. 无环 —— 写边前 walk 祖先链拒环。
3. 去重上滚 —— 统计走后代闭包 distinct 文档集；importance 上滚取 max。
"""
from __future__ import annotations

import logging
import re

import psycopg

from .config import Config
from .llm_extract import DOMAINS

log = logging.getLogger(__name__)

BATCH = 40              # 每次 LLM 调用带的 event 数
ACTIVE_DAYS = 10        # 只归簇最近活跃的 event
EVENT_CAP = 200         # 单轮最多处理的 event 数
VOCAB_CAP = 60          # 提示词里最多带的现有节点数（按最近活跃排）
MIN_MEMBERS = 2         # 新节点最少成员数（无单子链纪律）

SYSTEM_PROMPT = """你是新闻情报系统的编辑，负责把事件自下而上组织成层级：
相关事件归入"弧"（如"特朗普访华及其成果"），弧可再归入更大的"传奇"
（如"俄乌战争"这种数年尺度）。层级不预设，从数据里长出来。

给定现有节点词表和一批事件，判定归属：
- **优先复用现有节点**，宁可复用近似的也不轻开新节点
- 一个事件可以属于**多个**节点（美日汇率干预既属"汇率干预"也属
  "美日关系"），都给出；最贴切的排最前
- 词表覆盖不了的新现象才开新节点：给 key（小写英文 slug）、名称
  （≤8 个字，中立描述现象本身）、一句话入簇标准、所属域（按贴切度排序）。
  **新节点必须在本批里有至少 2 个成员事件**——单成员的"归纳"没有意义
- 新节点如果本身属于某个现有节点（弧属于传奇），给 parent_keys
- 真正独立的事件就不归属（standalone），不硬塞、不开"其他"类节点
- 节点的检验：入簇标准一句话可判定；"XX相关""其他动态"这种大而无当
  的节点不合格
通过 submit_hierarchy 一次性提交全部结果。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "new_nodes": {"type": "array", "items": {"type": "object", "properties": {
            "key": {"type": "string"},
            "name": {"type": "string"},
            "hint": {"type": "string"},
            "domains": {"type": "array",
                        "items": {"type": "string", "enum": DOMAINS}},
            "parent_keys": {"type": "array", "items": {"type": "string"},
                            "description": "该新节点自身归属的上层节点 key（可空）"},
        }, "required": ["key", "name", "hint", "domains"]}},
        "assignments": {"type": "array", "items": {"type": "object", "properties": {
            "event_id": {"type": "integer"},
            "node_keys": {"type": "array", "items": {"type": "string"},
                          "description": "该事件归属的节点 key，最贴切的在前；"
                                         "standalone 给空数组"},
        }, "required": ["event_id", "node_keys"]}},
    },
    "required": ["new_nodes", "assignments"],
}

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")


# ── 词表与输入 ───────────────────────────────────────────────

def _vocab(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""SELECT id, key, name, hint, domains FROM nodes
                       ORDER BY last_active_at DESC LIMIT %s""", (VOCAB_CAP,))
        return [{"id": i, "key": k, "name": n, "hint": h, "domains": d}
                for i, k, n, h, d in cur.fetchall()]


def _pending_events(conn: psycopg.Connection) -> list[dict]:
    """活跃且需要（重新）归簇的 event：没归过，或归后又有更新。"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.id, s.title, s.importance, s.domains, s.updated_at,
                   (SELECT d.event_signature FROM story_documents sd
                    JOIN documents d ON d.id = sd.document_id
                    WHERE sd.story_id = s.id AND d.event_signature IS NOT NULL
                    ORDER BY sd.added_at DESC LIMIT 1) AS signature,
                   (SELECT max(e.at) FROM node_edges e
                    WHERE e.child_kind='story' AND e.child_id = s.id) AS edged_at
            FROM stories s
            WHERE s.state = 'active'
              AND s.updated_at > now() - make_interval(days => %s)
            ORDER BY s.updated_at DESC LIMIT %s""", (ACTIVE_DAYS, EVENT_CAP))
        rows = [dict(zip(("id", "title", "importance", "domains", "updated_at",
                          "signature", "edged_at"), r)) for r in cur.fetchall()]
    return [r for r in rows
            if r["edged_at"] is None or r["updated_at"] > r["edged_at"]]


def _event_line(r: dict) -> str:
    sig = r["signature"] or r["title"] or ""
    dom = "/".join(r["domains"] or []) or "?"
    imp = r["importance"] or "?"
    return f"[{r['id']}] {sig}（域:{dom} 重要度:{imp}）"


# ── DAG 纪律 ─────────────────────────────────────────────────

def _ancestors(conn: psycopg.Connection, node_id: int) -> set[int]:
    """节点的全部祖先（含自身）。库里保证无环，这里只是有限遍历。"""
    seen = {node_id}
    frontier = [node_id]
    with conn.cursor() as cur:
        while frontier:
            cur.execute("""SELECT parent_id FROM node_edges
                           WHERE child_kind='node' AND child_id = ANY(%s)""",
                        (frontier,))
            parents = {r[0] for r in cur.fetchall()} - seen
            seen |= parents
            frontier = list(parents)
    return seen


def _add_edge(cur: psycopg.Cursor, conn: psycopg.Connection,
              parent_id: int, child_kind: str, child_id: int,
              reason: str | None = None) -> bool:
    """无环写边：parent 的祖先里不能出现 child（node 边才可能成环）。"""
    if child_kind == "node":
        if child_id == parent_id or parent_id in _ancestors(conn, child_id):
            log.warning("edge %s->node %s rejected: would create cycle",
                        parent_id, child_id)
            return False
    cur.execute("""INSERT INTO node_edges (parent_id, child_kind, child_id, reason)
                   VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (parent_id, child_kind, child_id, reason))
    return True


def rollup_node(conn: psycopg.Connection, node_id: int) -> None:
    """去重上滚：后代闭包的 distinct 文档统计 + importance max。"""
    with conn.cursor() as cur:
        cur.execute("""
            WITH RECURSIVE closure AS (
                SELECT child_kind, child_id FROM node_edges WHERE parent_id=%s
                UNION
                SELECT e.child_kind, e.child_id FROM node_edges e
                JOIN closure c ON c.child_kind='node' AND e.parent_id=c.child_id)
            SELECT coalesce(max(s.importance), 0),
                   max(s.updated_at)
            FROM closure c JOIN stories s
              ON c.child_kind='story' AND s.id=c.child_id""", (node_id,))
        imp, last = cur.fetchone()
        cur.execute("""UPDATE nodes SET importance=%s,
                       last_active_at=greatest(coalesce(%s, last_active_at),
                                               last_active_at)
                       WHERE id=%s""", (imp or None, last, node_id))


# ── orchestrator ─────────────────────────────────────────────

async def run_hierarchy(conn: psycopg.Connection, cfg: Config,
                        model: str | None = None) -> dict:
    from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions,
                                  ResultMessage, create_sdk_mcp_server,
                                  query, tool)

    from .llm_extract import DISALLOW_ALL_BUILTIN

    stats = {"events": 0, "assigned": 0, "new_nodes": 0, "errors": 0}
    pending = _pending_events(conn)
    if not pending:
        return stats

    for i in range(0, len(pending), BATCH):
        batch = pending[i:i + BATCH]
        vocab = _vocab(conn)                     # 每批取最新（同轮可能已扩）
        vocab_text = "\n".join(
            f"- {t['key']}：{t['name']}（{'/'.join(t['domains'] or [])}）"
            f" —— {t['hint']}" for t in vocab) or "（词表为空，全部由你涌现）"
        prompt = (f"现有节点词表：\n{vocab_text}\n\n"
                  "事件（[id] 签名（域/重要度））：\n"
                  + "\n".join(_event_line(r) for r in batch))

        captured: dict = {}

        @tool("submit_hierarchy", "一次性提交层级归簇结果", SCHEMA)
        async def submit(args):
            captured.clear()
            captured.update(args)
            return {"content": [{"type": "text", "text": "recorded"}]}

        server = create_sdk_mcp_server(name="hierarchy", version="1.0",
                                       tools=[submit])
        options = ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={"hy": server},
            allowed_tools=["mcp__hy__submit_hierarchy"],
            disallowed_tools=DISALLOW_ALL_BUILTIN,
            model=model, max_turns=4)

        mdl, usage, err = model or "unknown", None, None
        try:
            async for msg in query(prompt=prompt, options=options):
                if isinstance(msg, AssistantMessage):
                    mdl = msg.model or mdl
                elif isinstance(msg, ResultMessage):
                    usage = getattr(msg, "usage", None) or {}
                    if msg.is_error:
                        err = str(msg.result)[:500]
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:500]
        if not captured.get("assignments") and not err:
            err = "model did not call submit_hierarchy"

        batch_ids = {r["id"] for r in batch}
        got = {a["event_id"]: [k for k in a.get("node_keys", [])]
               for a in captured.get("assignments", [])
               if a.get("event_id") in batch_ids}
        new_ok = [t for t in captured.get("new_nodes", [])
                  if _SLUG.match(t.get("key", "")) and t.get("name")]

        with conn.cursor() as cur:
            cur.execute("""INSERT INTO llm_calls (purpose, model, input, output)
                           VALUES ('hierarchy',%s,%s,%s)""",
                        (mdl, psycopg.types.json.Json(
                            {"events": sorted(batch_ids)}),
                         psycopg.types.json.Json(
                            {"n": len(got), "new": len(new_ok),
                             "usage": usage, "error": err})))
            if err:
                conn.commit()
                stats["errors"] += len(batch)
                log.warning("hierarchy batch: %s", err)
                continue

            # 新节点：无单子链纪律 —— 本批内成员数 ≥ MIN_MEMBERS 才落地
            member_count: dict[str, int] = {}
            for keys in got.values():
                for k in keys:
                    member_count[k] = member_count.get(k, 0) + 1
            key_to_id = {t["key"]: t["id"] for t in vocab}
            for t in new_ok:
                if member_count.get(t["key"], 0) < MIN_MEMBERS:
                    log.info("new node %s rejected: %d member(s) < %d",
                             t["key"], member_count.get(t["key"], 0), MIN_MEMBERS)
                    continue
                doms = [d for d in t.get("domains", []) if d in DOMAINS]
                cur.execute("""INSERT INTO nodes (key, name, hint, domains)
                               VALUES (%s,%s,%s,%s)
                               ON CONFLICT (key) DO UPDATE SET
                                 last_active_at=now()
                               RETURNING id""",
                            (t["key"], t["name"], t.get("hint", "")[:200], doms))
                key_to_id[t["key"]] = cur.fetchone()[0]
                stats["new_nodes"] += 1
            conn.commit()
            # 新节点的父链（弧属于传奇）：需要 id 齐了才能做环检查
            for t in new_ok:
                cid = key_to_id.get(t["key"])
                if not cid:
                    continue
                for pk in t.get("parent_keys", []) or []:
                    pid = key_to_id.get(pk)
                    if pid:
                        _add_edge(cur, conn, pid, "node", cid, "sweep:new-node")
            # 事件归属（多父）
            touched: set[int] = set()
            for r in batch:
                keys = got.get(r["id"], [])
                linked = False
                for k in keys:
                    nid = key_to_id.get(k)
                    if nid:
                        _add_edge(cur, conn, nid, "story", r["id"], "sweep")
                        touched.add(nid)
                        linked = True
                stats["events"] += 1
                if linked:
                    stats["assigned"] += 1
        conn.commit()
        # 上滚被触到的节点及其祖先
        all_up: set[int] = set()
        for nid in touched:
            all_up |= _ancestors(conn, nid)
        for nid in all_up:
            rollup_node(conn, nid)
        conn.commit()
    return stats
