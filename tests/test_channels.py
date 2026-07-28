"""频道测试 —— 编译器（纯函数，无库）+ 端到端命中（真库）。

编译器测的是"结构在代码里、主题在数据里"这条边界还成不成立：
换个主题只是换 query 里的值，SQL 形状不变；写错键名要立刻炸。
"""
from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from newsassistant import db
from newsassistant.channels import (BadQuery, channel_stories, compile_query,
                                    list_channels, sync_channels)

TEST_DB = "postgresql://postgres:postgres@127.0.0.1:5432/newsassistant_test"


def test_unknown_key_fails_loudly():
    # 拼错的键必须炸 —— 静默忽略会退化成"匹配全部故事"，看起来能用实际全错
    with pytest.raises(BadQuery):
        compile_query({"any_entites": ["X"]})
    with pytest.raises(BadQuery):
        compile_query({"order": "popularity"})
    with pytest.raises(BadQuery):
        compile_query({"any_entities": "NVIDIA"})       # 必须是列表


def test_values_never_inlined():
    """主题只作为参数出现，永不拼进 SQL 字符串。"""
    sql, params = compile_query({"any_entities": ["NVIDIA"], "text": "export",
                                 "min_docs": 2, "order": "velocity"})
    assert "NVIDIA" not in sql and "export" not in sql
    assert ["nvidia"] in params and "%export%" in params and 2 in params
    assert sql.count("%s") == len(params)


@pytest.fixture()
def conn():
    try:
        c = db.connect(TEST_DB)
    except psycopg.OperationalError:
        pytest.skip("no local postgres")
    db.migrate(c)
    with c.cursor() as cur:
        cur.execute("TRUNCATE channels, story_entities, story_documents, claims, "
                    "documents, entities, stories, sources RESTART IDENTITY CASCADE")
    c.commit()
    yield c
    c.close()


def _story(conn, title, ents, scalars, claim=None) -> int:
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO stories (title, scalars) VALUES (%s,%s) RETURNING id""",
                    (title, psycopg.types.json.Jsonb(scalars)))
        sid = cur.fetchone()[0]
        for name in ents:
            cur.execute("SELECT id FROM entities WHERE lower(canonical_name)=lower(%s)",
                        (name,))
            r = cur.fetchone()
            if r:
                eid = r[0]
            else:
                cur.execute("""INSERT INTO entities (canonical_name,kind) VALUES (%s,'org')
                               RETURNING id""", (name,))
                eid = cur.fetchone()[0]
            cur.execute("INSERT INTO story_entities (story_id,entity_id) VALUES (%s,%s)",
                        (sid, eid))
        if claim:
            cur.execute("""INSERT INTO sources (key,name,kind,url,evidence_tier)
                           VALUES (%s,'S','rss','http://x',5)
                           ON CONFLICT (key) DO NOTHING""", (f"s{sid}",))
            cur.execute("SELECT id FROM sources LIMIT 1")
            src = cur.fetchone()[0]
            cur.execute("""INSERT INTO documents (source_id,url,url_canonical,status)
                           VALUES (%s,%s,%s,'ok') RETURNING id""",
                        (src, f"http://x/{sid}", f"http://x/{sid}"))
            did = cur.fetchone()[0]
            cur.execute("""INSERT INTO claims (document_id,story_id,text,confidence)
                           VALUES (%s,%s,%s,0.9)""", (did, sid, claim))
    conn.commit()
    return sid


def test_entity_and_scalar_filters(conn):
    a = _story(conn, "Chip export curbs", ["NVIDIA", "United States"],
               {"docs": 4, "breadth": 3, "consensus": 60, "velocity": 30})
    b = _story(conn, "Bank holds rates", ["Central Bank"],
               {"docs": 2, "breadth": 1, "consensus": 95, "velocity": 5})

    hit = channel_stories(conn, {"any_entities": ["nvidia"]})     # 大小写不敏感
    assert [s["id"] for s in hit] == [a]

    # 元频道：不提任何主题，只按标量 —— 同一个编译器
    meta = channel_stories(conn, {"max_consensus": 80, "min_breadth": 2,
                                  "order": "consensus"})
    assert [s["id"] for s in meta] == [a]
    assert [s["id"] for s in channel_stories(conn, {"min_docs": 1})] == sorted([a, b],
                                                                              reverse=True)


def test_all_entities_requires_every_name(conn):
    a = _story(conn, "Joint venture", ["TSMC", "ASML"], {"docs": 1})
    _story(conn, "Single", ["TSMC"], {"docs": 1})
    assert [s["id"] for s in channel_stories(conn, {"all_entities": ["TSMC", "ASML"]})] == [a]


def test_entity_filter_follows_alias_chain(conn):
    """频道写 United Kingdom，挂在 UK 上的故事也该进来（D22 的读取端穿透）。"""
    sid = _story(conn, "UK budget", ["UK"], {"docs": 1})
    with conn.cursor() as cur:
        cur.execute("INSERT INTO entities (canonical_name,kind) VALUES ('United Kingdom','place') "
                    "RETURNING id")
        canon = cur.fetchone()[0]
        cur.execute("UPDATE entities SET merged_into=%s WHERE canonical_name='UK'", (canon,))
    conn.commit()
    assert [s["id"] for s in channel_stories(conn, {"any_entities": ["United Kingdom"]})] == [sid]


def test_text_matches_title_or_claim(conn):
    a = _story(conn, "Quiet title", ["E1"], {"docs": 1}, claim="An export ban was announced")
    _story(conn, "Other", ["E2"], {"docs": 1}, claim="Unrelated")
    assert [s["id"] for s in channel_stories(conn, {"text": "export ban"})] == [a]


def test_sync_is_idempotent_and_validates(conn, tmp_path: Path):
    f = tmp_path / "ch.yaml"
    f.write_text("""channels:
  - key: k1
    name: 频道一
    query: {min_docs: 1, order: updated}
""", encoding="utf-8")
    assert sync_channels(conn, f) == {"channels": 1, "new": 1}
    assert sync_channels(conn, f) == {"channels": 1, "new": 0}      # 幂等
    assert [c["key"] for c in list_channels(conn)] == ["k1"]

    bad = tmp_path / "bad.yaml"
    bad.write_text("channels:\n  - {key: k2, name: 坏, query: {nope: 1}}\n", encoding="utf-8")
    with pytest.raises(BadQuery):                 # 坏查询在同步时就失败
        sync_channels(conn, bad)


def test_shipped_channels_all_compile():
    """随仓库发的频道定义必须全部可编译 —— 否则用户 sync 时才发现。"""
    import yaml
    spec = yaml.safe_load(Path("sources/channels.yaml").read_text(encoding="utf-8"))
    for ch in spec["channels"]:
        compile_query(ch.get("query", {}))
        assert ch["palette"]["dark"]["accent"].startswith("#")
        assert len(ch["palette"]["dark"]["ramp"]) == 6


def test_missing_scalars_pass_lower_bounds_but_not_upper(conn):
    """标量是归并后才写的。下限缺省按 0 算（刚建的故事不该被无害条件挡住），
    上限不缺省 —— "一致度未知" 不等于 "一致度低"，否则新故事全涌进分歧频道。"""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO stories (title) VALUES ('刚建的故事') RETURNING id")
        fresh = cur.fetchone()[0]
    conn.commit()
    assert fresh in [s["id"] for s in channel_stories(conn, {"min_docs": 0})]
    assert fresh not in [s["id"] for s in channel_stories(conn, {"min_docs": 1})]
    assert fresh not in [s["id"] for s in channel_stories(conn, {"max_consensus": 80})]
