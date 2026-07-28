"""归并层测试 —— FakeJudge，不碰网络/SDK。

场景：docA（新实体）→ 零候选确定性新建；docB（共享实体）→ 召回到 S1 →
裁决 absorbed；docC（无关实体）→ 新建。验证 story_events 判据、
llm_calls 审计（仅 LLM 路径）、标量、幂等。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import psycopg
import pytest

from newsassistant import db
from newsassistant.config import Config
from newsassistant.merge import CandidateView, DocView, Verdict, run_assignment

TEST_DB = "postgresql://postgres:postgres@127.0.0.1:5432/newsassistant_test"


class FakeJudge:
    def __init__(self):
        self.calls: list[list[tuple[int, list[int]]]] = []   # 每批一条

    async def judge_batch(self, items) -> list[Verdict]:
        self.calls.append([(d.id, [c.id for c in cands]) for d, cands in items])
        out = []
        for doc, candidates in items:
            # 共享实体 ≥2 → 归入首个候选；否则新建
            if candidates and len(candidates[0].shared_entities) >= 2:
                out.append(Verdict(decision="existing", story_id=candidates[0].id,
                                   reason="shared entities", confidence=0.9,
                                   model="fake-1"))
            else:
                out.append(Verdict(decision="new", title=f"新故事：{doc.title}",
                                   reason="insufficient overlap", confidence=0.8,
                                   model="fake-1"))
        return out


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


def _seed(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO sources (key,name,kind,url,evidence_tier)
                       VALUES ('s1','S1','rss','http://x/1',5), ('s2','S2','rss','http://x/2',5)
                       RETURNING id""")
        cur.execute("SELECT id FROM sources ORDER BY id")
        s1, s2 = [r[0] for r in cur.fetchall()]
        docs = [  # (source, title, entities, claim)
            (s1, "Earthquake strikes region X", ["Region X", "Geological Survey"],
             "A magnitude 6 earthquake struck Region X on Monday"),
            (s2, "Region X quake death toll rises", ["Region X", "Geological Survey"],
             "The death toll from the Region X earthquake rose to 12"),
            (s1, "Central bank holds rates", ["Central Bank"],
             "The central bank left rates unchanged"),
        ]
        for i, (src, title, ents, claim) in enumerate(docs):
            cur.execute("""INSERT INTO documents (source_id,url,url_canonical,title,
                           status,extracted_at,published_at)
                           VALUES (%s,%s,%s,%s,'ok',now(), now() - interval '1 hour' * %s)
                           RETURNING id""",
                        (src, f"http://x/d{i}", f"http://x/d{i}", title, 3 - i))
            did = cur.fetchone()[0]
            cur.execute("""INSERT INTO claims (document_id,text,stance,confidence)
                           VALUES (%s,%s,0,0.9)""", (did, claim))
            for name in ents:
                cur.execute("""SELECT id FROM entities WHERE lower(canonical_name)=lower(%s)""",
                            (name,))
                r = cur.fetchone()
                eid = r[0] if r else None
                if not eid:
                    cur.execute("INSERT INTO entities (canonical_name,kind) VALUES (%s,'org') "
                                "RETURNING id", (name,))
                    eid = cur.fetchone()[0]
                cur.execute("INSERT INTO document_entities VALUES (%s,%s)", (did, eid))
    conn.commit()


def test_assignment_flow(conn, tmp_path: Path):
    cfg = Config(database_url=TEST_DB, data_dir=tmp_path)
    _seed(conn)
    judge = FakeJudge()

    st = asyncio.run(run_assignment(conn, cfg, judge, limit=10))
    assert st == {"docs": 3, "new_stories": 2, "absorbed": 1, "errors": 0,
                  "batches": 1}
    # 只有 docB 走了 LLM（docA/docC 零候选，确定性新建），一批一篇
    assert judge.calls == [[(2, [1])]]

    with conn.cursor() as cur:
        cur.execute("SELECT id, title FROM stories ORDER BY id")
        stories = cur.fetchall()
        assert len(stories) == 2
        # 地震故事吸收了两篇，标量正确
        cur.execute("SELECT scalars FROM stories WHERE id=%s", (stories[0][0],))
        sc = cur.fetchone()[0]
        assert sc["docs"] == 2 and sc["breadth"] == 2      # 两个独立信源
        # event-sourcing：created + absorbed，absorbed 带判据
        cur.execute("""SELECT kind, payload FROM story_events WHERE story_id=%s
                       ORDER BY id""", (stories[0][0],))
        events = cur.fetchall()
        assert [e[0] for e in events] == ["created", "absorbed"]
        assert events[1][1]["reason"] == "shared entities"
        assert events[1][1]["candidates_considered"] == [stories[0][0]]
        # 审计：仅 LLM 路径落 llm_calls
        cur.execute("SELECT count(*) FROM llm_calls WHERE purpose='assign'")
        assert cur.fetchone()[0] == 1
        # claims 已挂到故事
        cur.execute("SELECT count(*) FROM claims WHERE story_id IS NOT NULL")
        assert cur.fetchone()[0] == 3

    # 幂等：重跑无待归并文档
    st2 = asyncio.run(run_assignment(conn, cfg, FakeJudge(), limit=10))
    assert st2["docs"] == 0


def _seed_docs(conn, docs: list[tuple[str, list[str]]]) -> None:
    """(title, entities) 列表按序入库，published_at 递增。"""
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO sources (key,name,kind,url,evidence_tier)
                       VALUES ('s1','S1','rss','http://x/1',5) RETURNING id""")
        src = cur.fetchone()[0]
        for i, (title, ents) in enumerate(docs):
            cur.execute("""INSERT INTO documents (source_id,url,url_canonical,title,
                           status,extracted_at,published_at)
                           VALUES (%s,%s,%s,%s,'ok',now(), now() - interval '1 hour' * %s)
                           RETURNING id""",
                        (src, f"http://x/d{i}", f"http://x/d{i}", title, len(docs) - i))
            did = cur.fetchone()[0]
            cur.execute("""INSERT INTO claims (document_id,text,stance,confidence)
                           VALUES (%s,%s,0,0.9)""", (did, f"claim of {title}"))
            for name in ents:
                cur.execute("SELECT id FROM entities WHERE canonical_name=%s", (name,))
                r = cur.fetchone()
                eid = r[0] if r else None
                if not eid:
                    cur.execute("INSERT INTO entities (canonical_name,kind) "
                                "VALUES (%s,'org') RETURNING id", (name,))
                    eid = cur.fetchone()[0]
                cur.execute("INSERT INTO document_entities VALUES (%s,%s)", (did, eid))
    conn.commit()


def test_batch_waves_respect_entity_disjointness(conn, tmp_path: Path):
    """实体不相交的文档同批裁决；相交的必须先冲刷（串行语义保全）。"""
    cfg = Config(database_url=TEST_DB, data_dir=tmp_path)
    _seed_docs(conn, [
        ("quake initial", ["Region E", "Survey Org"]),        # d1 零候选 → S1
        ("bank initial", ["Bank F", "Council F"]),            # d2 零候选 → S2
        ("quake update", ["Region E", "Survey Org"]),         # d3 → 候选 S1（共享2）
        ("bank update", ["Bank F", "Council F"]),             # d4 与 d3 不相交 → 同批
        ("quake analysis", ["Region E", "New Angle"]),        # d5 与 d3 相交 → 先冲刷
    ])
    judge = FakeJudge()
    st = asyncio.run(run_assignment(conn, cfg, judge, limit=10, batch_size=6))

    assert st == {"docs": 5, "new_stories": 3, "absorbed": 2, "errors": 0,
                  "batches": 2}
    # 第一批：d3+d4 同批（实体不相交）；第二批：d5 单独（与 d3 相交被冲刷出来）
    assert [len(b) for b in judge.calls] == [2, 1]
    # d5 的召回发生在冲刷之后：能看见已吸收 d3 的 S1（共享 Region E）
    (d5_id, d5_cands), = judge.calls[1]
    assert d5_cands == [1]


def test_retryable_verdict_leaves_doc_unassigned(conn, tmp_path: Path):
    """调用层失败（retryable）：审计落库但不建故事，文档留待下轮。"""
    cfg = Config(database_url=TEST_DB, data_dir=tmp_path)
    _seed_docs(conn, [
        ("event initial", ["Site G", "Agency G"]),
        ("event update", ["Site G", "Agency G"]),
    ])

    class FailingJudge:
        async def judge_batch(self, items):
            return [Verdict(model="fake-1", error="quota exhausted", retryable=True)
                    for _ in items]

    st = asyncio.run(run_assignment(conn, cfg, FailingJudge(), limit=10))
    assert st["errors"] == 1 and st["absorbed"] == 0
    with conn.cursor() as cur:
        # 审计仍然写了
        cur.execute("SELECT count(*) FROM llm_calls WHERE purpose='assign'")
        assert cur.fetchone()[0] == 1
        # 文档未归属 → 下轮可重试
        cur.execute("""SELECT count(*) FROM documents d WHERE d.status='ok'
                       AND NOT EXISTS (SELECT 1 FROM story_documents sd
                                       WHERE sd.document_id=d.id)""")
        assert cur.fetchone()[0] == 1
