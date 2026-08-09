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
        self.calls: list[tuple[int, list[int]]] = []
        self.batches: list[list[int]] = []          # 每波的文档 id，验证波次划分

    async def judge_batch(
            self, items: list[tuple[DocView, list[CandidateView]]]) -> list[Verdict]:
        self.batches.append([d.id for d, _ in items])
        out = []
        for doc, candidates in items:
            self.calls.append((doc.id, [c.id for c in candidates]))
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
    assert st == {"docs": 3, "new_stories": 2, "absorbed": 1, "errors": 0, "waves": 1}
    # 只有 docB 走了 LLM（docA/docC 零候选，确定性新建）
    assert len(judge.calls) == 1

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM stories")
        assert len(cur.fetchall()) == 2
        # 队列是**新→旧**（_unassigned_docs），所以先到的死亡人数那篇建故事、
        # 地震那篇被吸收 —— 故事按内容找，不按 id 顺序猜，免得再被队列方向绊倒
        cur.execute("""SELECT sd.story_id FROM story_documents sd
                       JOIN documents d ON d.id=sd.document_id
                       WHERE d.title=%s""", ("Earthquake strikes region X",))
        quake = cur.fetchone()[0]
        # 地震故事吸收了两篇，标量正确
        cur.execute("SELECT scalars FROM stories WHERE id=%s", (quake,))
        sc = cur.fetchone()[0]
        assert sc["docs"] == 2 and sc["breadth"] == 2      # 两个独立信源
        # event-sourcing：created + absorbed，absorbed 带判据
        cur.execute("""SELECT kind, payload FROM story_events WHERE story_id=%s
                       ORDER BY id""", (quake,))
        events = cur.fetchall()
        assert [e[0] for e in events] == ["created", "absorbed"]
        assert events[1][1]["reason"] == "shared entities"
        assert events[1][1]["candidates_considered"] == [quake]
        # 审计：仅 LLM 路径落 llm_calls
        cur.execute("SELECT count(*) FROM llm_calls WHERE purpose='assign'")
        assert cur.fetchone()[0] == 1
        # claims 已挂到故事
        cur.execute("SELECT count(*) FROM claims WHERE story_id IS NOT NULL")
        assert cur.fetchone()[0] == 3

    # 幂等：重跑无待归并文档
    st2 = asyncio.run(run_assignment(conn, cfg, FakeJudge(), limit=10))
    assert st2["docs"] == 0


def _add_doc(conn, source_key: str, title: str, ents: list[str], claim: str,
             hours_ago: int) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM sources WHERE key=%s", (source_key,))
        src = cur.fetchone()[0]
        cur.execute("""INSERT INTO documents (source_id,url,url_canonical,title,
                       status,extracted_at,published_at)
                       VALUES (%s,%s,%s,%s,'ok',now(), now() - interval '1 hour' * %s)
                       RETURNING id""",
                    (src, f"http://x/{title}", f"http://x/{title}", title, hours_ago))
        did = cur.fetchone()[0]
        cur.execute("INSERT INTO claims (document_id,text,stance,confidence) "
                    "VALUES (%s,%s,0,0.9)", (did, claim))
        for name in ents:
            cur.execute("SELECT id FROM entities WHERE lower(canonical_name)=lower(%s)",
                        (name,))
            r = cur.fetchone()
            if r:
                eid = r[0]
            else:
                cur.execute("INSERT INTO entities (canonical_name,kind) VALUES (%s,'org') "
                            "RETURNING id", (name,))
                eid = cur.fetchone()[0]
            cur.execute("INSERT INTO document_entities VALUES (%s,%s)", (did, eid))
    conn.commit()
    return did


def test_waves_split_on_salient_entity_overlap(conn, tmp_path: Path):
    """波次划分：合格实体不相交的文档同波，相交的必须先冲刷。

    冲刷的必要性在于顺序 —— 后一篇的召回要看得见前一篇裁决产生的故事，
    否则同一事件的两篇会各建一个重复故事（串行存在的唯一理由）。
    """
    cfg = Config(database_url=TEST_DB, data_dir=tmp_path)
    _seed(conn)
    asyncio.run(run_assignment(conn, cfg, FakeJudge(), limit=10))   # 建起两个故事

    # D：地震簇；E：央行簇（与 D 实体不相交）；F：回到地震簇（与 D 相交）
    d = _add_doc(conn, "s2", "Region X quake aftershock",
                 ["Region X", "Geological Survey"], "An aftershock hit Region X", 3)
    e = _add_doc(conn, "s1", "Central bank signals cut", ["Central Bank"],
                 "The central bank signalled a cut", 2)
    f = _add_doc(conn, "s1", "Region X quake damage survey",
                 ["Region X", "Geological Survey"], "Damage in Region X was surveyed", 1)

    judge = FakeJudge()
    st = asyncio.run(run_assignment(conn, cfg, judge, limit=10))

    # 队列新→旧，进队顺序是 F、E、D：F 与 E 打包同波（实体不相交）；
    # D 与 F 相交 → 另起一波。波次判据只看实体是否相交，与新旧方向无关
    assert judge.batches == [[f, e], [d]]
    assert st["waves"] == 2 and st["errors"] == 0
    # 每篇仍拿到自己的候选，没有被跨文档串味
    assert dict((doc_id, len(cands)) for doc_id, cands in judge.calls)[e] == 1
