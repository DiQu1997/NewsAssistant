"""合成层测试 —— FakeSynthesizer。核心：引用强制（最高原则 5）——
无引用/伪引用的句子在写入前被结构性丢弃，绝不落库。"""
from __future__ import annotations

import asyncio

import psycopg
import pytest

from newsassistant import db
from newsassistant.synth import StoryView, SynthResult, run_synthesis

TEST_DB = "postgresql://postgres:postgres@127.0.0.1:5432/newsassistant_test"


@pytest.fixture()
def conn():
    try:
        c = db.connect(TEST_DB)
    except psycopg.OperationalError:
        pytest.skip("no local postgres")
    db.migrate(c)
    with c.cursor() as cur:
        cur.execute("TRUNCATE llm_calls, document_entities, fetch_log, stories, "
                    "story_documents, story_entities, story_events, claims, documents, "
                    "entities, sources RESTART IDENTITY CASCADE")
    c.commit()
    yield c
    c.close()


def _seed(conn, n_docs=3) -> tuple[int, list[int]]:
    """一个 n 篇文档的故事，每篇一条 claim。返回 (story_id, claim_ids)。"""
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO sources (key,name,kind,url,evidence_tier)
                       VALUES ('s','S','rss','http://x',5) RETURNING id""")
        src = cur.fetchone()[0]
        cur.execute("INSERT INTO stories (title) VALUES ('evolving event') RETURNING id")
        sid = cur.fetchone()[0]
        claim_ids = []
        for i in range(n_docs):
            cur.execute("""INSERT INTO documents (source_id,url,url_canonical,status,
                           extracted_at,published_at)
                           VALUES (%s,%s,%s,'ok',now(),now() - interval '1 hour' * %s)
                           RETURNING id""",
                        (src, f"http://x/{i}", f"http://x/{i}", n_docs - i))
            did = cur.fetchone()[0]
            cur.execute("INSERT INTO story_documents VALUES (%s,%s)", (sid, did))
            cur.execute("""INSERT INTO claims (document_id,story_id,text,stance,confidence)
                           VALUES (%s,%s,%s,0,0.9) RETURNING id""",
                        (did, sid, f"observed state change {i}"))
            claim_ids.append(cur.fetchone()[0])
    conn.commit()
    return sid, claim_ids


class FakeSynthesizer:
    """两句合法 + 一句无引用 + 一句伪引用；时间线一条合法一条伪引用。"""

    def __init__(self):
        self.seen: list[StoryView] = []

    async def synthesize(self, story: StoryView) -> SynthResult:
        self.seen.append(story)
        ids = [c.id for c in story.claims]
        return SynthResult(
            sentences=[
                {"text": "The event began.", "claim_ids": [ids[0]]},
                {"text": "It then escalated.", "claim_ids": [ids[1], ids[2]]},
                {"text": "UNSUPPORTED speculation.", "claim_ids": []},
                {"text": "FAKE citation.", "claim_ids": [999999]},
            ],
            timeline=[
                {"when": "2026-07-01", "what": "initial report", "claim_ids": [ids[0]]},
                {"when": "2026-07-02", "what": "fabricated", "claim_ids": [888888]},
            ],
            open_questions=[{"question": "What caused it?", "why": "no claim covers cause"}],
            model="fake-synth-1")


def test_citation_enforcement_and_writes(conn):
    sid, claim_ids = _seed(conn)
    fake = FakeSynthesizer()
    st = asyncio.run(run_synthesis(conn, fake, limit=10, min_docs=2))
    assert st == {"stories": 1, "sentences": 2, "dropped": 3, "errors": 0}

    with conn.cursor() as cur:
        cur.execute("""SELECT summary, timeline, open_questions, synthesized_at
                       FROM stories WHERE id=%s""", (sid,))
        summary, timeline, oq, syn_at = cur.fetchone()
        # 只有带合法引用的两句活下来
        assert [s["text"] for s in summary["sentences"]] == \
            ["The event began.", "It then escalated."]
        assert summary["sentences"][1]["claim_ids"] == [claim_ids[1], claim_ids[2]]
        assert [t["what"] for t in timeline] == ["initial report"]
        assert oq[0]["question"] == "What caused it?"
        assert syn_at is not None
        # 审计 + 事件
        cur.execute("SELECT count(*) FROM llm_calls WHERE purpose='synthesize'")
        assert cur.fetchone()[0] == 1
        cur.execute("""SELECT payload FROM story_events
                       WHERE story_id=%s AND kind='synthesized'""", (sid,))
        payload = cur.fetchone()[0]
        assert payload["sentences"] == 2 and payload["dropped_uncited"] == 3

    # 幂等：没有新文档 → 不再合成
    st2 = asyncio.run(run_synthesis(conn, FakeSynthesizer(), limit=10, min_docs=2))
    assert st2["stories"] == 0

    # 故事有新动静（updated_at 前进）→ 重新入队，且上一版综述传给合成器
    with conn.cursor() as cur:
        cur.execute("UPDATE stories SET updated_at=now() + interval '1 second' "
                    "WHERE id=%s", (sid,))
    conn.commit()
    fake3 = FakeSynthesizer()
    st3 = asyncio.run(run_synthesis(conn, fake3, limit=10, min_docs=2))
    assert st3["stories"] == 1
    assert [s["text"] for s in fake3.seen[0].prev_sentences] == \
        ["The event began.", "It then escalated."]


def test_min_docs_skips_single_doc_stories(conn):
    _seed(conn, n_docs=1)
    st = asyncio.run(run_synthesis(conn, FakeSynthesizer(), limit=10, min_docs=2))
    assert st == {"stories": 0, "sentences": 0, "dropped": 0, "errors": 0}


def test_synthesis_error_keeps_story_pending(conn):
    sid, _ = _seed(conn)

    class ErrJudge:
        async def synthesize(self, story):
            return SynthResult(model="fake-synth-1", error="quota exhausted")

    st = asyncio.run(run_synthesis(conn, ErrJudge(), limit=10, min_docs=2))
    assert st["errors"] == 1 and st["stories"] == 0
    with conn.cursor() as cur:
        # 审计写了，但故事仍待合成（synthesized_at 未置）
        cur.execute("SELECT count(*) FROM llm_calls WHERE purpose='synthesize'")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT synthesized_at FROM stories WHERE id=%s", (sid,))
        assert cur.fetchone()[0] is None
