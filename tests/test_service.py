"""服务层测试 —— TestClient，调度器关闭（读接口与调度互不依赖）。"""
from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from newsassistant import db
from newsassistant.config import Config

TEST_DB = "postgresql://postgres:postgres@127.0.0.1:5432/newsassistant_test"


@pytest.fixture()
def client(tmp_path: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from newsassistant.service import create_app
    try:
        c = db.connect(TEST_DB)
    except psycopg.OperationalError:
        pytest.skip("no local postgres")
    db.migrate(c)
    with c.cursor() as cur:
        cur.execute("TRUNCATE llm_calls, document_entities, fetch_log, stories, "
                    "story_documents, story_entities, story_events, claims, "
                    "documents, entities, sources, pipeline_runs, channels "
                    "RESTART IDENTITY CASCADE")
        cur.execute("""INSERT INTO sources (key,name,kind,url,evidence_tier)
                       VALUES ('s1','S1','rss','http://x/1',5) RETURNING id""")
        src = cur.fetchone()[0]
        cur.execute("""INSERT INTO documents (source_id,url,url_canonical,title,
                       status,extracted_at) VALUES (%s,'http://x/d1','http://x/d1',
                       'Quake hits region X','ok',now()) RETURNING id""", (src,))
        did = cur.fetchone()[0]
        cur.execute("""INSERT INTO stories (title, summary, synthesized_at)
                       VALUES ('Region X earthquake',
                               '[{"text":"A quake struck.","claim_ids":[1]}]'::jsonb,
                               now()) RETURNING id""")
        sid = cur.fetchone()[0]
        cur.execute("""INSERT INTO claims (document_id,story_id,text,stance,confidence)
                       VALUES (%s,%s,'A magnitude 6 quake struck Region X',0,0.9)""",
                    (did, sid))
        cur.execute("""INSERT INTO story_documents (story_id,document_id)
                       VALUES (%s,%s)""", (sid, did))
        cur.execute("""INSERT INTO pipeline_runs (cycle,stage,finished_at,stats)
                       VALUES (1,'ingest',now(),'{"new_docs":1}'::jsonb)""")
        cur.execute("""INSERT INTO channels (key,name,query,palette) VALUES
                       ('t-all','全部','{"min_docs":0}'::jsonb,
                        '{"dark":{"accent":"#3987e5","ramp":["#16283f","#1b3a5c","#214d7a","#286098","#2f75b8","#3987e5"]}}'::jsonb)""")
    c.commit()
    c.close()

    app = create_app(Config(database_url=TEST_DB, data_dir=tmp_path), scheduler=False)
    with TestClient(app) as tc:
        tc.story_id = sid
        yield tc


def test_health_reports_last_run(client):
    r = client.get("/health").json()
    assert r["ok"] is True and r["scheduler"] is False
    assert r["last_run"]["stage"] == "ingest"


def test_runs_and_stats(client):
    runs = client.get("/api/runs").json()
    assert runs[0]["stage"] == "ingest" and runs[0]["stats"] == {"new_docs": 1}
    s = client.get("/api/stats").json()
    assert s["docs"] == 1 and s["stories"] == 1 and s["synthesized"] == 1


def test_story_detail_carries_cited_claims(client):
    lst = client.get("/api/stories").json()
    assert [x["id"] for x in lst] == [client.story_id]

    s = client.get(f"/api/stories/{client.story_id}").json()
    assert s["summary"][0]["claim_ids"] == [1]
    # 引用能落到原文（原则 5 的前端面）：断言带来源与立场
    assert s["claims"][0]["source"] == "s1" and s["claims"][0]["stance"] == 0
    assert client.get("/api/stories/999999").status_code == 404


def test_channel_endpoint_serves_query_and_palette(client):
    chans = client.get("/api/channels").json()
    assert [c["key"] for c in chans] == ["t-all"]
    r = client.get("/api/channels/t-all/stories").json()
    # 频道自带查询与标识色 —— 前端不硬编码任何频道
    assert r["channel"]["palette"]["dark"]["accent"] == "#3987e5"
    assert [s["id"] for s in r["stories"]] == [client.story_id]
    assert len(r["stories"][0]["series"]) == 14        # 稀疏日序列，前端画密度带
    assert client.get("/api/channels/nope/stories").status_code == 404


def test_bad_saved_query_is_422_not_500(client, monkeypatch):
    """坏频道是配置错误：报 422 并说清哪个键错了，不是 500。"""
    import psycopg

    from newsassistant import db
    c = db.connect(TEST_DB)
    with c.cursor() as cur:
        cur.execute("""INSERT INTO channels (key,name,query) VALUES
                       ('broken','坏',%s)""", (psycopg.types.json.Jsonb({"nope": 1}),))
    c.commit(); c.close()
    r = client.get("/api/channels/broken/stories")
    assert r.status_code == 422 and "nope" in r.json()["detail"]


def test_dashboard_assets_are_served(client):
    """web/ 必须随包发出去 —— 漏了 package-data 时这条会先炸。"""
    idx = client.get("/")
    assert idx.status_code == 200 and "NEWSASSISTANT" in idx.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/app.css").status_code == 200
