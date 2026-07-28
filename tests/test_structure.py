"""结构检测测试 —— 同一批检测器，喂不同**结构**的数据得到不同视图。

这正是 D4 要证明的事：换的是数据的形状，不是代码里的领域分支。
所以下面的样例故意用抽象命名（A/B/C、供应商/客户），不带任何领域词。
"""
from __future__ import annotations

import psycopg
import pytest

from newsassistant import db
from newsassistant.structure import _topo_layers, detect

TEST_DB = "postgresql://postgres:postgres@127.0.0.1:5432/newsassistant_test"


@pytest.fixture()
def conn():
    try:
        c = db.connect(TEST_DB)
    except psycopg.OperationalError:
        pytest.skip("no local postgres")
    db.migrate(c)
    with c.cursor() as cur:
        cur.execute("TRUNCATE story_entities, story_documents, claims, documents, "
                    "entities, stories, sources RESTART IDENTITY CASCADE")
        cur.execute("""INSERT INTO sources (key,name,kind,url,evidence_tier) VALUES
                       ('s1','S1','rss','http://a',3),('s2','S2','rss','http://b',3),
                       ('s3','S3','rss','http://c',1)""")
    c.commit()
    yield c
    c.close()


def _ent(cur, name: str) -> int:
    cur.execute("SELECT id FROM entities WHERE lower(canonical_name)=lower(%s)", (name,))
    r = cur.fetchone()
    if r:
        return r[0]
    cur.execute("INSERT INTO entities (canonical_name,kind) VALUES (%s,'org') RETURNING id",
                (name,))
    return cur.fetchone()[0]


def _story(conn, title: str, ents: list[str], claims: list[dict] | None = None,
           questions: list[str] | None = None) -> int:
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO stories (title, open_questions) VALUES (%s,%s)
                       RETURNING id""",
                    (title, psycopg.types.json.Jsonb(questions) if questions else None))
        sid = cur.fetchone()[0]
        for e in ents:
            cur.execute("""INSERT INTO story_entities (story_id,entity_id) VALUES (%s,%s)
                           ON CONFLICT DO NOTHING""", (sid, _ent(cur, e)))
        for i, cl in enumerate(claims or []):
            cur.execute("SELECT id FROM sources WHERE key=%s", (cl.get("source", "s1"),))
            src = cur.fetchone()[0]
            cur.execute("""INSERT INTO documents (source_id,url,url_canonical,status)
                           VALUES (%s,%s,%s,'ok') RETURNING id""",
                        (src, f"http://x/{sid}/{i}", f"http://x/{sid}/{i}"))
            did = cur.fetchone()[0]
            cur.execute("""INSERT INTO story_documents (story_id,document_id)
                           VALUES (%s,%s)""", (sid, did))
            cur.execute("""INSERT INTO claims (document_id,story_id,text,struct,stance,
                           confidence) VALUES (%s,%s,%s,%s,%s,0.9)""",
                        (did, sid, cl.get("text", "t"),
                         psycopg.types.json.Jsonb(cl.get("struct", {})), cl.get("stance")))
    conn.commit()
    return sid


def _get(dets, view):
    return next(d for d in dets if d.view == view)


def test_directed_chain_emerges_from_who_whom(conn):
    """稳定的 who→whom 重复出现 → 有向链路。层数是从数据里排出来的。"""
    edge = lambda a, b: {"struct": {"who": a, "whom": b, "did": "supplies"},
                         "text": f"{a} supplies {b}"}
    for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
        _story(conn, f"{a}→{b}", [a, b], [edge(a, b), edge(a, b)])   # 每条边两次 = 稳定
    sids = _all_ids(conn)

    d = _get(detect(conn, sids), "chain")
    assert d.triggered, d.reason
    assert [l for l in d.payload["layers"]] == [["A"], ["B"], ["C"], ["D"]]
    assert d.evidence["stable_edges"] == 3


def test_single_mention_edges_are_not_stable(conn):
    """出现一次的 who→whom 是轶事不是依赖 —— 不该触发链路。"""
    for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
        _story(conn, f"{a}→{b}", [a, b],
               [{"struct": {"who": a, "whom": b, "did": "x"}}])
    d = _get(detect(conn, _all_ids(conn)), "chain")
    assert not d.triggered and d.evidence["stable_edges"] == 0
    assert "稳定有向边" in d.reason        # 未触发也说明理由


def test_unresolvable_names_are_reported_not_guessed(conn):
    """who/whom 是自由文本：落不到已知实体的不进图，且如实计数。"""
    _story(conn, "s", ["A"], [{"struct": {"who": "some unnamed official",
                                          "whom": "another party"}}] * 3)
    d = _get(detect(conn, _all_ids(conn)), "chain")
    assert d.evidence["claims_with_who_whom"] == 3
    assert d.evidence["resolved_edges"] == 0 and not d.triggered


def test_cycles_are_dropped_and_counted():
    """有环说明它不是依赖链。丢掉的边要报出来，不能画一张缠住的图。"""
    layers, dropped = _topo_layers({("A", "B"): 2, ("B", "C"): 2, ("C", "A"): 2})
    assert layers == [] and dropped == 3
    layers, dropped = _topo_layers({("A", "B"): 2, ("B", "C"): 2, ("X", "Y"): 2})
    assert layers == [["A", "X"], ["B", "Y"], ["C"]] and dropped == 0


def test_dense_cooccurrence_gives_network_and_drops_ubiquitous(conn):
    """共现稠密 → 网络；出现在过半故事里的实体连接一切，要被排除。"""
    groups = [["A", "B", "C"], ["B", "C", "D"], ["C", "D", "E"], ["D", "E", "F"],
              ["E", "F", "G"], ["F", "G", "A"]]
    for i, g in enumerate(groups):
        _story(conn, f"story {i}", g + ["EVERYWHERE"])
    d = _get(detect(conn, _all_ids(conn)), "network")
    assert d.triggered, d.reason
    names = {n["name"] for n in d.payload["nodes"]}
    assert "EVERYWHERE" not in names and {"A", "B", "C"} <= names
    assert d.evidence["excluded_ubiquitous"] >= 1


def test_sparse_slice_gets_no_network(conn):
    _story(conn, "lonely", ["A", "B"])
    d = _get(detect(conn, _all_ids(conn)), "network")
    assert not d.triggered and "未达阈值" in d.reason


def test_cross_source_stance_split_triggers_disagreement(conn):
    """同一故事、不同信源、立场差 ≥1 → 分歧矩阵（核心资产）。"""
    for i in range(2):
        _story(conn, f"contested {i}", ["A"],
               [{"source": "s1", "stance": 2, "text": "claims it worked"},
                {"source": "s2", "stance": -2, "text": "disputes the figure"}])
    _story(conn, "agreed", ["B"],
           [{"source": "s1", "stance": 1}, {"source": "s2", "stance": 1}])
    d = _get(detect(conn, _all_ids(conn)), "disagreement")
    assert d.triggered and d.evidence["stories_split"] == 2
    assert set(d.payload["sources"]) == {"s1", "s2"}


def test_agreement_is_a_fact_not_a_failure(conn):
    _story(conn, "agreed", ["A"], [{"source": "s1", "stance": 1},
                                   {"source": "s2", "stance": 1}])
    d = _get(detect(conn, _all_ids(conn)), "disagreement")
    assert not d.triggered and "不是缺陷" in d.reason


def test_geo_detected_but_deliberately_not_rendered(conn):
    """结构成立也不画手绘地图（D13）—— 检测与渲染是两件事。"""
    _story(conn, "located", ["A"],
           [{"struct": {"where": "somewhere"}} for _ in range(4)])
    d = _get(detect(conn, _all_ids(conn)), "geo")
    assert d.triggered and d.renderable is False and "D13" in d.reason


def test_coaxial_says_what_is_missing(conn):
    _story(conn, "s", ["A"])
    d = _get(detect(conn, _all_ids(conn)), "coaxial")
    assert not d.triggered and "外生数值序列" in d.reason


def test_open_questions_surface(conn):
    _story(conn, "s", ["A"], questions=["谁在为此付钱？", "数字来自哪里？"])
    d = _get(detect(conn, _all_ids(conn)), "open_questions")
    assert d.triggered and d.evidence["questions"] == 2


def test_empty_slice_is_answered_not_crashed(conn):
    dets = detect(conn, [])
    assert dets and all(not d.triggered for d in dets)
    assert all(d.reason == "切片为空" for d in dets)


def _all_ids(conn) -> list[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM stories ORDER BY id")
        return [r[0] for r in cur.fetchall()]
