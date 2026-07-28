"""转述溯源测试 —— 纯函数（分组/源头挑选）+ DB 编排（跨源标记、同源豁免、幂等、
breadth 坍缩）。零 LLM、零网络。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

from newsassistant import db
from newsassistant.syndicate import find_groups, pick_origin, run_syndication

TEST_DB = "postgresql://postgres:postgres@127.0.0.1:5432/newsassistant_test"

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


# ── 纯函数 ──────────────────────────────────────────────────

def test_find_groups_transitive():
    # A→B、C→B 一组；C→A→B 链也一组；孤立点不出现
    assert find_groups([(1, None), (2, 1), (3, 1)]) == [[1, 2, 3]]
    assert find_groups([(1, None), (2, 1), (3, 2)]) == [[1, 2, 3]]
    assert find_groups([(1, None), (2, None)]) == []
    # 指向组外（状态非 ok 被过滤掉的目标）不成边
    assert find_groups([(2, 99)]) == []
    # 两个独立组
    got = find_groups([(1, None), (2, 1), (10, None), (11, 10)])
    assert sorted(got) == [[1, 2], [10, 11]]


def test_pick_origin_prefers_published_at():
    mk = lambda i, pub, fet: {"id": i, "published_at": pub, "fetched_at": fet}
    a = mk(1, T0, T0 + timedelta(hours=9))
    b = mk(2, T0 + timedelta(hours=1), T0 + timedelta(hours=1))
    assert pick_origin([b, a])["id"] == 1          # published_at 早者胜
    # published_at 缺失排最后，哪怕 fetched_at 更早
    c = mk(3, None, T0 - timedelta(days=1))
    assert pick_origin([c, a])["id"] == 1
    # 全缺失 → fetched_at 定序
    d = mk(4, None, T0 + timedelta(hours=2))
    assert pick_origin([c, d])["id"] == 3


# ── DB 编排 ─────────────────────────────────────────────────

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
    """三源转发组（s1 原发 + s2/s3 转发 + s1 自家更新）+ 无关单篇。"""
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO sources (key,name,kind,url,evidence_tier) VALUES
                       ('s1','S1','rss','http://a',5), ('s2','S2','rss','http://b',5),
                       ('s3','S3','rss','http://c',5)""")
        cur.execute("SELECT id FROM sources ORDER BY id")
        s1, s2, s3 = [r[0] for r in cur.fetchall()]
        rows = [  # (source, url, published_offset_h, near_dup_of)
            (s1, "http://a/origin", 0, None),       # id 1：源头
            (s2, "http://b/copy", 1, 1),            # id 2：跨源转发
            (s3, "http://c/copy", 2, 1),            # id 3：跨源转发
            (s1, "http://a/update", 3, 1),          # id 4：同源更新，不是转述
            (s2, "http://b/other", 0, None),        # id 5：无关
        ]
        for src, url, off, dup in rows:
            cur.execute("""INSERT INTO documents (source_id,url,url_canonical,status,
                           published_at,fetched_at,near_dup_of)
                           VALUES (%s,%s,%s,'ok',%s,%s,%s)""",
                        (src, url, url, T0 + timedelta(hours=off),
                         T0 + timedelta(hours=off, minutes=5), dup))
    conn.commit()
    return s1, s2, s3


def test_syndication_marks_cross_source_only(conn):
    _seed(conn)
    st = run_syndication(conn)
    assert st["groups"] == 1 and st["marked"] == 2 and st["cleared"] == 0

    with conn.cursor() as cur:
        cur.execute("SELECT id, syndication_of FROM documents ORDER BY id")
        assert cur.fetchall() == [
            (1, None),     # 源头自身不标
            (2, 1), (3, 1),
            (4, None),     # 同源近重 = 更新，不是转述
            (5, None)]

    # 幂等：再跑无写入
    st2 = run_syndication(conn)
    assert st2["marked"] == 0 and st2["cleared"] == 0 and st2["unchanged"] == 4


def test_breadth_collapses_syndicated_copies(conn):
    """故事里 s1 原发 + s2/s3 转发 + s1 更新 → breadth 1 不是 3。"""
    from newsassistant.merge import _update_scalars
    _seed(conn)
    run_syndication(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO stories (title) VALUES ('wire story') RETURNING id")
        sid = cur.fetchone()[0]
        for did in (1, 2, 3, 4):
            cur.execute("INSERT INTO story_documents VALUES (%s,%s)", (sid, did))
        _update_scalars(cur, sid)
        cur.execute("SELECT scalars FROM stories WHERE id=%s", (sid,))
        sc = cur.fetchone()[0]
    conn.commit()
    assert sc["docs"] == 4 and sc["breadth"] == 1
