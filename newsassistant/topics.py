"""topics 阶段 —— 频道子主题自下而上涌现，词表持久化保稳定。

与实体消歧同构的设计：簇不是预定义的格子，是从故事里长出来的；
但词表（channel_topics）持久化 + "优先复用现有簇"约束，让地图不因
每轮重聚而漂移。yaml 里的清单只是冷启动种子。

判定给 LLM 两样东西：现有簇词表 + 一批故事。能归入就归入；这批里
确有词表覆盖不了的新现象才开新簇（key/名称/一句话入簇标准）；
相关故事同批判定自然聚进同一簇 —— 这正是 predefined 做不到的。
"""
from __future__ import annotations

import logging
import re

import psycopg

from .channels import channel_stories, list_channels
from .config import Config

log = logging.getLogger(__name__)

BATCH = 25
PER_CHANNEL_LIMIT = 60
VOCAB_CAP = 24          # 提示词里最多带多少个现有簇（按最近使用排）

SYSTEM_PROMPT = """你是新闻板块的分类编辑。板块的子主题簇是自下而上长出来的。
给定现有簇词表和一批故事，为每个故事选**最合适的一个**簇 key：
- 能归入现有簇就归入（优先复用，宁可复用近似的也不轻开新簇）
- 这批故事里确有词表覆盖不了的新现象时才开新簇：给 key（小写英文
  slug，如 yen-intervention）、名称（不超过 8 个字）、一句话入簇标准；
  同一现象的相关故事必须归入同一个簇，不许拆散
- 簇的检验：入簇标准必须一句话说清且可判定；"XX相关""其他动态"
  这种大而无当的簇不合格
- 板块有主旨。主旨之外的串台故事（因提到大实体被宽泛匹配进来，
  如地缘政治板块里的央行决议、纯市场行情）一律归 "other"，
  **不许为它们开簇** —— 开簇等于给串台发户口
- 实在归不进任何簇的孤例也用 "other"
通过 submit_topics 一次性提交全部结果。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "new_topics": {"type": "array", "items": {"type": "object", "properties": {
            "key": {"type": "string"},
            "name": {"type": "string"},
            "hint": {"type": "string"},
        }, "required": ["key", "name", "hint"]}},
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "story_id": {"type": "integer"},
            "topic": {"type": "string"},
        }, "required": ["story_id", "topic"]}},
    },
    "required": ["new_topics", "items"],
}

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")


def _vocab(conn: psycopg.Connection, channel: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""SELECT key, name, hint FROM channel_topics
                       WHERE channel=%s ORDER BY last_used_at DESC
                       LIMIT %s""", (channel, VOCAB_CAP))
        return [{"key": k, "name": n, "hint": h} for k, n, h in cur.fetchall()]


def _pending(conn: psycopg.Connection, channel: dict) -> list[dict]:
    """该频道需要（重新）打标的故事：没标过，或打标后故事又有更新。"""
    rows = channel_stories(conn, channel["query"], limit=PER_CHANNEL_LIMIT)
    if not rows:
        return []
    with conn.cursor() as cur:
        cur.execute("""SELECT story_id, at FROM story_topics WHERE channel=%s
                       AND story_id = ANY(%s)""",
                    (channel["key"], [r["id"] for r in rows]))
        tagged = dict(cur.fetchall())
    return [r for r in rows
            if r["id"] not in tagged or r["updated_at"] > tagged[r["id"]]]


def _story_line(conn: psycopg.Connection, row: dict) -> str:
    first = ""
    with conn.cursor() as cur:
        cur.execute("SELECT summary FROM stories WHERE id=%s", (row["id"],))
        summ = cur.fetchone()[0] or []
    if summ:
        first = (summ[0].get("text") or "")[:200]
    return f"[{row['id']}] {row['title']}" + (f" —— {first}" if first else "")


async def run_topics(conn: psycopg.Connection, cfg: Config,
                     model: str | None = None) -> dict:
    from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions,
                                  ResultMessage, create_sdk_mcp_server,
                                  query, tool)

    from .llm_extract import DISALLOW_ALL_BUILTIN

    stats = {"channels": 0, "tagged": 0, "new_topics": 0, "errors": 0}
    for ch in list_channels(conn):
        # 有词表（种子或已涌现）的频道才做子主题层；全库/分歧频道没有
        vocab = _vocab(conn, ch["key"])
        if not vocab and not (ch.get("topics") or []):
            continue
        stats["channels"] += 1
        pending = _pending(conn, ch)
        if not pending:
            continue

        for i in range(0, len(pending), BATCH):
            batch = pending[i:i + BATCH]
            vocab = _vocab(conn, ch["key"])          # 每批取最新（同轮可能已扩）
            vocab_text = "\n".join(f"- {t['key']}：{t['name']} —— {t['hint']}"
                                   for t in vocab) or "（词表为空，全部由你涌现）"
            prompt = (f"板块：{ch['name']}\n现有簇词表：\n{vocab_text}\n\n"
                      "故事（[id] 标题 —— 综述首句）：\n"
                      + "\n".join(_story_line(conn, r) for r in batch))

            captured: dict = {}

            @tool("submit_topics", "一次性提交簇判定（含新开的簇）", SCHEMA)
            async def submit(args):
                captured.clear()
                captured.update(args)
                return {"content": [{"type": "text", "text": "recorded"}]}

            server = create_sdk_mcp_server(name="topics", version="1.0",
                                           tools=[submit])
            options = ClaudeAgentOptions(
                system_prompt=SYSTEM_PROMPT,
                mcp_servers={"tp": server},
                allowed_tools=["mcp__tp__submit_topics"],
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
            if not captured.get("items") and not err:
                err = "model did not call submit_topics"

            new_ok = [t for t in captured.get("new_topics", [])
                      if _SLUG.match(t.get("key", "")) and t.get("name")]
            valid = {t["key"] for t in vocab} | {t["key"] for t in new_ok} \
                | {"other"}
            got = {it["story_id"]: it["topic"]
                   for it in captured.get("items", [])
                   if it.get("story_id") in {r["id"] for r in batch}}
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO llm_calls (purpose, model, input, output)
                               VALUES ('topics',%s,%s,%s)""",
                            (mdl, psycopg.types.json.Json(
                                {"channel": ch["key"],
                                 "stories": [r["id"] for r in batch]}),
                             psycopg.types.json.Json(
                                {"n": len(got), "new": len(new_ok),
                                 "usage": usage, "error": err})))
                if err:
                    conn.commit()
                    stats["errors"] += len(batch)
                    log.warning("topics %s: %s", ch["key"], err)
                    continue
                # 只登记真被用上的新簇 —— 提了名字却没归任何故事的不进词表
                used = set(got.values())
                for t in new_ok:
                    if t["key"] in used:
                        cur.execute("""INSERT INTO channel_topics
                                       (channel, key, name, hint)
                                       VALUES (%s,%s,%s,%s)
                                       ON CONFLICT (channel, key) DO NOTHING""",
                                    (ch["key"], t["key"], t["name"],
                                     t.get("hint", "")[:200]))
                        stats["new_topics"] += 1
                for r in batch:
                    topic = got.get(r["id"], "other")
                    if topic not in valid:
                        topic = "other"
                    cur.execute("""INSERT INTO story_topics (story_id, channel, topic)
                                   VALUES (%s,%s,%s)
                                   ON CONFLICT (story_id, channel) DO UPDATE SET
                                     topic=EXCLUDED.topic, at=now()""",
                                (r["id"], ch["key"], topic))
                    stats["tagged"] += 1
                cur.execute("""UPDATE channel_topics SET last_used_at=now()
                               WHERE channel=%s AND key = ANY(%s)""",
                            (ch["key"], list(used)))
            conn.commit()
    return stats
