"""合成层测试 —— FakeSynthesizer，重点测引用强制（最高原则 5）与过期判定。"""
from __future__ import annotations

import asyncio

import psycopg
import pytest

from newsassistant import db
from newsassistant.synth import (COOLDOWN_HOURS, StoryView, Synthesis,
                                 run_synthesis)

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


def _seed_story(conn, n_docs=2) -> tuple[int, list[int]]:
    """一个故事、n 篇文档、每篇一条 claim。返回 (story_id, claim_ids)。"""
    claim_ids = []
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO sources (key,name,kind,url,evidence_tier)
                       VALUES ('s','S','rss','http://x',5) RETURNING id""")
        sid = cur.fetchone()[0]
        cur.execute("INSERT INTO stories (title) VALUES ('Quake in region X') RETURNING id")
        st = cur.fetchone()[0]
        for i in range(n_docs):
            cur.execute("""INSERT INTO documents (source_id,url,url_canonical,title,
                           status,extracted_at,published_at)
                           VALUES (%s,%s,%s,%s,'ok',now(), now() - interval '1 hour' * %s)
                           RETURNING id""",
                        (sid, f"http://x/{i}", f"http://x/{i}", f"doc {i}", n_docs - i))
            did = cur.fetchone()[0]
            cur.execute("""INSERT INTO claims (document_id,story_id,text,stance,confidence)
                           VALUES (%s,%s,%s,0,0.9) RETURNING id""",
                        (did, st, f"claim text {i}"))
            claim_ids.append(cur.fetchone()[0])
            cur.execute("INSERT INTO story_documents VALUES (%s,%s)", (st, did))
    conn.commit()
    return st, claim_ids


class FakeSynthesizer:
    """返回预设产物；记录喂进来的 StoryView 供断言。"""

    def __init__(self, make):
        self.make = make
        self.seen: list[StoryView] = []

    async def synthesize(self, story: StoryView) -> Synthesis:
        self.seen.append(story)
        return self.make(story)


def test_citation_enforcement_and_staleness(conn):
    st, cids = _seed_story(conn)

    def make(story):
        return Synthesis(summary=[
            {"text": "Good sentence.", "claim_ids": [cids[0], cids[1]]},
            {"text": "Uncited sentence.", "claim_ids": []},              # 丢
            {"text": "Foreign citation.", "claim_ids": [999999]},        # 丢
        ], timeline=[
            {"when": "2026-07-27", "what": "Toll rose", "claim_ids": [cids[1]]},
            {"when": "?", "what": "No citation", "claim_ids": []},       # 丢
        ], open_questions=["Who pays?"], model="fake-1")

    # 这个用例测引用强制与过期判定，冷却关掉（冷却本身见
    # test_resynthesis_cooldown），否则重合成永远被冷却挡住，测不到过期语义
    stats = asyncio.run(run_synthesis(conn, FakeSynthesizer(make), limit=10,
                                      cooldown_hours=0))
    assert stats == {"stories": 1, "sentences": 1, "dropped": 3, "errors": 0}

    with conn.cursor() as cur:
        cur.execute("""SELECT summary, timeline, open_questions FROM stories
                       WHERE id=%s""", (st,))
        summary, timeline, oq = cur.fetchone()
        assert [s["text"] for s in summary] == ["Good sentence."]
        assert summary[0]["claim_ids"] == [cids[0], cids[1]]
        assert [t["what"] for t in timeline] == ["Toll rose"]
        assert oq == ["Who pays?"]
        cur.execute("SELECT kind FROM story_events WHERE story_id=%s ORDER BY id", (st,))
        assert ("synthesized",) in cur.fetchall()
        cur.execute("SELECT count(*) FROM llm_calls WHERE purpose='synthesize'")
        assert cur.fetchone()[0] == 1

    # 过期判定：合成后未更新 → 不再选中
    fake2 = FakeSynthesizer(make)
    stats2 = asyncio.run(run_synthesis(conn, fake2, limit=10, cooldown_hours=0))
    assert stats2["stories"] == 0 and not fake2.seen

    # 故事又有更新 → 重新过期，且上一版综述喂给模型
    with conn.cursor() as cur:
        cur.execute("UPDATE stories SET updated_at=now() WHERE id=%s", (st,))
    conn.commit()
    fake3 = FakeSynthesizer(make)
    asyncio.run(run_synthesis(conn, fake3, limit=10, cooldown_hours=0))
    assert fake3.seen and fake3.seen[0].prev_summary is not None
    assert fake3.seen[0].prev_summary[0]["text"] == "Good sentence."


def test_all_dropped_keeps_previous_summary(conn):
    st, cids = _seed_story(conn)
    good = FakeSynthesizer(lambda s: Synthesis(
        summary=[{"text": "V1.", "claim_ids": [cids[0]]}], model="fake-1"))
    asyncio.run(run_synthesis(conn, good, limit=10))

    with conn.cursor() as cur:
        cur.execute("UPDATE stories SET updated_at=now() WHERE id=%s", (st,))
    conn.commit()
    bad = FakeSynthesizer(lambda s: Synthesis(
        summary=[{"text": "All invalid.", "claim_ids": [42424242]}], model="fake-1"))
    stats = asyncio.run(run_synthesis(conn, bad, limit=10, cooldown_hours=0))
    assert stats["errors"] == 1 and stats["stories"] == 0

    with conn.cursor() as cur:
        cur.execute("SELECT summary FROM stories WHERE id=%s", (st,))
        assert cur.fetchone()[0][0]["text"] == "V1."   # 旧版未被覆盖


def test_resynthesis_cooldown(conn):
    """重合成冷却：热故事吸新文档就重写，一天能烧掉 synthesize 八成预算。
    冷却窗内的更新一律不重合成，窗外才放行；首次合成不受影响。"""
    st, cids = _seed_story(conn)
    v1 = FakeSynthesizer(lambda s: Synthesis(
        summary=[{"text": "V1.", "claim_ids": [cids[0]]}], model="fake-1"))
    assert asyncio.run(run_synthesis(conn, v1, limit=10))["stories"] == 1

    # 刚合成完就又吸了篇文档 → 过期但在冷却窗内，不重合成
    with conn.cursor() as cur:
        cur.execute("UPDATE stories SET updated_at=now() WHERE id=%s", (st,))
    conn.commit()
    hot = FakeSynthesizer(lambda s: Synthesis(
        summary=[{"text": "V2.", "claim_ids": [cids[0]]}], model="fake-1"))
    assert asyncio.run(run_synthesis(conn, hot, limit=10))["stories"] == 0
    assert not hot.seen

    # 把上次合成推到冷却窗外 → 同样的过期状态，这次放行
    with conn.cursor() as cur:
        cur.execute("""UPDATE stories
                       SET synthesized_at = now() - make_interval(hours => %s),
                           updated_at = now()
                       WHERE id=%s""", (COOLDOWN_HOURS + 1, st))
    conn.commit()
    cool = FakeSynthesizer(lambda s: Synthesis(
        summary=[{"text": "V2.", "claim_ids": [cids[0]]}], model="fake-1"))
    assert asyncio.run(run_synthesis(conn, cool, limit=10))["stories"] == 1

    with conn.cursor() as cur:
        cur.execute("SELECT summary FROM stories WHERE id=%s", (st,))
        assert cur.fetchone()[0][0]["text"] == "V2."


def test_single_doc_story_skipped(conn):
    _seed_story(conn, n_docs=1)
    fake = FakeSynthesizer(lambda s: Synthesis(model="fake-1"))
    stats = asyncio.run(run_synthesis(conn, fake, limit=10))
    assert stats["stories"] == 0 and not fake.seen


def test_error_result_audited_not_applied(conn):
    st, _ = _seed_story(conn)
    fake = FakeSynthesizer(lambda s: Synthesis(error="quota", model="fake-1"))
    stats = asyncio.run(run_synthesis(conn, fake, limit=10))
    assert stats["errors"] == 1

    with conn.cursor() as cur:
        cur.execute("SELECT summary, synthesized_at FROM stories WHERE id=%s", (st,))
        summary, syn_at = cur.fetchone()
        assert summary is None and syn_at is None      # 失败不落产物
        cur.execute("""SELECT output->>'error' FROM llm_calls
                       WHERE purpose='synthesize'""")
        assert cur.fetchone()[0] == "quota"            # 但审计必须在
