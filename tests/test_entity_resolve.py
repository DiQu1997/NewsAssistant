"""实体消歧测试 —— 候选发现纯函数 + FakeResolver 编排（含召回联动）。"""
from __future__ import annotations

import asyncio

import psycopg
import pytest

from newsassistant import db
from newsassistant.entity_resolve import (Resolution, ResolveResult,
                                          is_candidate_pair, run_resolution)
from newsassistant.merge import recall

TEST_DB = "postgresql://postgres:postgres@127.0.0.1:5432/newsassistant_test"


# ── 候选发现（纯函数，无 DB） ───────────────────────────────
def test_candidate_signals():
    assert is_candidate_pair("United Kingdom", "UK")            # 缩写
    assert is_candidate_pair("United States", "U.S.")           # 带点缩写
    assert is_candidate_pair("united kingdom", "United Kingdom")  # 字面归一
    assert is_candidate_pair("United States Department of Commerce",
                             "U.S. Department of Commerce")     # 变体
    assert is_candidate_pair("Reuters", "Thomson Reuters")      # 候选（裁决层否）
    assert not is_candidate_pair("France", "Germany")
    assert not is_candidate_pair("Donald Trump", "Emmanuel Macron")


class FakeResolver:
    """UK 对 → 合并；Reuters 对 → 否。"""

    async def resolve(self, pairs):
        out = []
        for i, p in enumerate(pairs):
            names = {p["a_name"], p["b_name"]}
            if names == {"United Kingdom", "UK"}:
                out.append(Resolution(pair_index=i, same=True,
                                      canonical="United Kingdom",
                                      reason="abbreviation", confidence=0.98))
            else:
                out.append(Resolution(pair_index=i, same=False,
                                      reason="different entities", confidence=0.9))
        return ResolveResult(resolutions=out, model="fake-1")


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


def _seed(conn):
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO sources (key,name,kind,url,evidence_tier)
                       VALUES ('s','S','rss','http://x',5) RETURNING id""")
        sid = cur.fetchone()[0]
        for i, (title, ents) in enumerate([
            ("PM speech", ["United Kingdom", "Reuters"]),
            ("Election poll", ["UK", "Thomson Reuters"]),
        ]):
            cur.execute("""INSERT INTO documents (source_id,url,url_canonical,title,
                           status,extracted_at) VALUES (%s,%s,%s,%s,'ok',now())
                           RETURNING id""", (sid, f"http://x/{i}", f"http://x/{i}", title))
            did = cur.fetchone()[0]
            for name in ents:
                cur.execute("SELECT id FROM entities WHERE canonical_name=%s", (name,))
                r = cur.fetchone()
                eid = r[0] if r else None
                if not eid:
                    cur.execute("INSERT INTO entities (canonical_name,kind) "
                                "VALUES (%s,'org') RETURNING id", (name,))
                    eid = cur.fetchone()[0]
                cur.execute("INSERT INTO document_entities VALUES (%s,%s)", (did, eid))
        # doc0 建一个故事，让召回联动可测
        cur.execute("INSERT INTO stories (title) VALUES ('UK politics') RETURNING id")
        st = cur.fetchone()[0]
        cur.execute("INSERT INTO story_documents VALUES (%s,1)", (st,))
        cur.execute("""INSERT INTO story_entities (story_id, entity_id)
                       SELECT %s, entity_id FROM document_entities WHERE document_id=1""",
                    (st,))
    conn.commit()
    return st


def test_resolution_merges_and_recall_sees_through(conn):
    story_id = _seed(conn)

    # 合并前：doc2 挂的是 "UK"，与故事的 "United Kingdom" 配不上 → 召回空
    assert recall(conn, 2) == [] or all(c.id != story_id for c in recall(conn, 2))

    st = asyncio.run(run_resolution(conn, FakeResolver(), limit=10))
    assert st["merged"] == 1 and st["errors"] == 0
    assert st["kept"] >= 1                       # Reuters 对被正确拒绝

    with conn.cursor() as cur:
        cur.execute("""SELECT e.canonical_name, e2.canonical_name FROM entities e
                       JOIN entities e2 ON e2.id=e.merged_into
                       WHERE e.merged_into IS NOT NULL""")
        assert cur.fetchall() == [("UK", "United Kingdom")]
        cur.execute("""SELECT aliases FROM entities WHERE canonical_name='United Kingdom'""")
        assert "UK" in cur.fetchone()[0]
        # 审计
        cur.execute("SELECT count(*) FROM llm_calls WHERE purpose='resolve_entity'")
        assert cur.fetchone()[0] == 1

    # 合并后：doc2 的召回能穿透别名命中故事
    cands = recall(conn, 2)
    assert any(c.id == story_id for c in cands)
    # 幂等：再跑一轮不再产生合并
    st2 = asyncio.run(run_resolution(conn, FakeResolver(), limit=10))
    assert st2["merged"] == 0
