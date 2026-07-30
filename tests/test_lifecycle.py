"""故事生命周期测试 —— active → dormant → archived。"""
from __future__ import annotations

import psycopg
import pytest

from newsassistant import db
from newsassistant.lifecycle import run_lifecycle

TEST_DB = "postgresql://postgres:postgres@127.0.0.1:5432/newsassistant_test"


@pytest.fixture()
def conn():
    try:
        c = db.connect(TEST_DB)
    except psycopg.OperationalError:
        pytest.skip("no local postgres")
    db.migrate(c)
    with c.cursor() as cur:
        cur.execute("TRUNCATE llm_calls, document_entities, fetch_log, stories, story_documents, "
                    "story_entities, story_events, claims, documents, entities, sources "
                    "RESTART IDENTITY CASCADE")
    c.commit()
    yield c
    c.close()


def _seed_story(conn, title, days_ago_updated, state="active"):
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO stories (title, state, updated_at)
                       VALUES (%s, %s, now() - make_interval(days => %s))
                       RETURNING id""", (title, state, days_ago_updated))
        sid = cur.fetchone()[0]
        if state == "dormant":
            cur.execute("UPDATE stories SET dormant_at = now() - make_interval(days => %s) "
                        "WHERE id=%s", (days_ago_updated, sid))
    conn.commit()
    return sid


def test_active_to_dormant(conn):
    """7+ 天无动静 → dormant。"""
    fresh = _seed_story(conn, "Fresh story", 2)
    stale = _seed_story(conn, "Stale story", 10)

    st = run_lifecycle(conn)
    assert st["dormant"] == 1
    assert st["archived"] == 0

    with conn.cursor() as cur:
        cur.execute("SELECT state FROM stories WHERE id=%s", (fresh,))
        assert cur.fetchone()[0] == "active"
        cur.execute("SELECT state, dormant_at FROM stories WHERE id=%s", (stale,))
        state, dormant_at = cur.fetchone()
        assert state == "dormant"
        assert dormant_at is not None
        cur.execute("SELECT kind FROM story_events WHERE story_id=%s", (stale,))
        assert cur.fetchone()[0] == "dormant"


def test_dormant_to_archived(conn):
    """休眠 30+ 天 → archived。"""
    _seed_story(conn, "Recently dormant", 10, state="dormant")
    old = _seed_story(conn, "Long dormant", 40, state="dormant")

    st = run_lifecycle(conn)
    assert st["archived"] == 1

    with conn.cursor() as cur:
        cur.execute("SELECT state FROM stories WHERE id=%s", (old,))
        assert cur.fetchone()[0] == "archived"
        cur.execute("SELECT kind FROM story_events WHERE story_id=%s ORDER BY id DESC LIMIT 1",
                    (old,))
        assert cur.fetchone()[0] == "archived"


def test_idempotent(conn):
    """已经 dormant 的不会重新标 dormant。"""
    _seed_story(conn, "Already dormant", 10, state="dormant")
    st = run_lifecycle(conn)
    assert st["dormant"] == 0


def test_full_lifecycle(conn):
    """active → dormant → archived 的完整路径。"""
    sid = _seed_story(conn, "Lifecycle test", 10)
    st1 = run_lifecycle(conn)
    assert st1["dormant"] == 1

    with conn.cursor() as cur:
        cur.execute("UPDATE stories SET dormant_at = now() - interval '35 days' WHERE id=%s",
                    (sid,))
    conn.commit()

    st2 = run_lifecycle(conn)
    assert st2["archived"] == 1

    with conn.cursor() as cur:
        cur.execute("SELECT state FROM stories WHERE id=%s", (sid,))
        assert cur.fetchone()[0] == "archived"
        cur.execute("SELECT kind FROM story_events WHERE story_id=%s ORDER BY id", (sid,))
        events = [r[0] for r in cur.fetchall()]
        assert events == ["dormant", "archived"]
