"""topics 阶段 —— 把频道内的故事归到子主题（语义纵深的判定层）。

taxonomy 是频道的数据（channels.topics，yaml 里维护）；这里只做判定：
给一批故事选"最合适的一个"子主题，都不合适归 other。haiku 级判断题，
增量跑（新故事 + 打标后又有更新的故事），成本按条数线性且极小。
"""
from __future__ import annotations

import logging

import psycopg

from .channels import channel_stories, list_channels
from .config import Config

log = logging.getLogger(__name__)

BATCH = 25
PER_CHANNEL_LIMIT = 60

SYSTEM_PROMPT = """你是新闻板块的分类编辑。给定一个板块的子主题清单和一批故事，
为每个故事选**最合适的一个**子主题 key。判定依据是故事的主旨，不是提到了什么词。
都不合适就用 "other"。通过 submit_topics 一次性提交全部结果。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "story_id": {"type": "integer"},
            "topic": {"type": "string"},
        }, "required": ["story_id", "topic"]}},
    },
    "required": ["items"],
}


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

    stats = {"channels": 0, "tagged": 0, "errors": 0}
    for ch in list_channels(conn):
        taxonomy = ch.get("topics") or []
        if not taxonomy:
            continue
        stats["channels"] += 1
        valid = {t["key"] for t in taxonomy} | {"other"}
        pending = _pending(conn, ch)
        if not pending:
            continue
        tax_text = "\n".join(f"- {t['key']}：{t['name']} —— {t['hint']}"
                             for t in taxonomy)

        for i in range(0, len(pending), BATCH):
            batch = pending[i:i + BATCH]
            prompt = (f"板块：{ch['name']}\n子主题清单：\n{tax_text}\n\n"
                      "故事（[id] 标题 —— 综述首句）：\n"
                      + "\n".join(_story_line(conn, r) for r in batch))

            captured: dict = {}

            @tool("submit_topics", "一次性提交全部故事的子主题判定", SCHEMA)
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
                                {"n": len(got), "usage": usage, "error": err})))
                if err:
                    conn.commit()
                    stats["errors"] += len(batch)
                    log.warning("topics %s: %s", ch["key"], err)
                    continue
                for r in batch:
                    # 漏答的按 other 落表：下轮不重复送审，故事更新会自然重判
                    topic = got.get(r["id"], "other")
                    if topic not in valid:
                        topic = "other"
                    cur.execute("""INSERT INTO story_topics (story_id, channel, topic)
                                   VALUES (%s,%s,%s)
                                   ON CONFLICT (story_id, channel) DO UPDATE SET
                                     topic=EXCLUDED.topic, at=now()""",
                                (r["id"], ch["key"], topic))
                    stats["tagged"] += 1
            conn.commit()
    return stats
