"""转述溯源测试 —— 跨源近重判转述，同源近重不判，幂等。"""
from __future__ import annotations

import psycopg
import pytest

from newsassistant import db
from newsassistant.syndicate import run_syndication

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


def test_cross_source_marked_same_source_not(conn):
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO sources (key,name,kind,url,evidence_tier) VALUES
                       ('a','A','rss','http://a',5), ('b','B','rss','http://b',5),
                       ('c','C','rss','http://c',5)""")
        cur.execute("SELECT id FROM sources ORDER BY id")
        sa, sb, sc_ = [r[0] for r in cur.fetchall()]

        def doc(src, url, status, near=None):
            cur.execute("""INSERT INTO documents (source_id,url,url_canonical,
                           status,near_dup_of) VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                        (src, url, url, status, near))
            return cur.fetchone()[0]

        origin = doc(sa, "http://a/1", "ok")                 # 组 origin（通稿）
        d_b = doc(sb, "http://b/1", "near_dup", origin)      # 跨源转发 → 转述
        d_c = doc(sc_, "http://c/1", "near_dup", origin)     # 跨源转发 → 转述
        d_a2 = doc(sa, "http://a/2", "near_dup", origin)     # 同源改稿 → 不是转述
        doc(sb, "http://b/9", "ok")                          # 无关 ok 文档
    conn.commit()

    st = run_syndication(conn)
    assert st == {"marked": 2, "same_source": 1, "total_near": 3}

    with conn.cursor() as cur:
        cur.execute("""SELECT id, syndication_of FROM documents
                       WHERE syndication_of IS NOT NULL ORDER BY id""")
        assert cur.fetchall() == [(d_b, origin), (d_c, origin)]
        cur.execute("SELECT syndication_of FROM documents WHERE id=%s", (d_a2,))
        assert cur.fetchone()[0] is None

    # 幂等：重跑不再改动
    st2 = run_syndication(conn)
    assert st2["marked"] == 0
