"""端到端集成测试 —— 本地 HTTP 服务器 + 本地 Postgres，验证完整链路：

feed 拉取 → 解析 → URL 规范化去重 → 抓正文（robots）→ trafilatura 抽取
→ sha256 精确去重 → simhash 近重标记 → 内容落盘 → 指针入库 → 幂等重跑

需要本地 Postgres（NA_TEST_DATABASE_URL 或默认 dev 库同机的 *_test 库）；
连不上则整组 skip。不碰外网 —— localhost 在 no_proxy 里，不走代理。
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg
import pytest

from newsassistant import db
from newsassistant.config import Config
from newsassistant.ingest import run_once

TEST_DB = "postgresql://postgres:postgres@127.0.0.1:5432/newsassistant_test"

BODY_A = " ".join(
    f"Sentence {i} of the article explains clause {i} of the proposed rule "
    f"and what it means for filers and their compliance teams."
    for i in range(15))
BODY_B = BODY_A.replace("clause 7", "provision 7")   # 转述：一词之差 → 近重
BODY_C = " ".join(
    f"Chapter {i} covers an entirely different subject: harvest yields, "
    f"rainfall statistics and the outlook for storage levels in region {i}."
    for i in range(15))

def _page(title: str, body: str) -> str:
    return (f"<!DOCTYPE html><html lang='en'><head><title>{title}</title></head>"
            f"<body><nav><a href='/'>Home</a></nav><article><h1>{title}</h1>"
            f"<p>{body}</p></article><footer>footer text</footer></body></html>")

def _feed(base: str) -> str:
    items = "".join(
        f"<item><title>{t}</title><link>{base}{p}</link><guid>{p}</guid>"
        f"<pubDate>Mon, 27 Jul 2026 08:0{i}:00 GMT</pubDate></item>"
        for i, (t, p) in enumerate([
            ("Rule proposed", "/a1"),
            ("Rule proposed (tracking link)", "/a1?utm_source=feed"),  # 规范化后同 URL
            ("Rule proposed, syndicated copy", "/a2"),
            ("Harvest outlook", "/a3"),
        ]))
    return (f"<?xml version='1.0'?><rss version='2.0'><channel>"
            f"<title>T</title><link>{base}</link>{items}</channel></rss>")


class _Handler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[str, str]] = {}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in self.routes:
            ctype, body = self.routes[path]
            raw = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *a):  # 静音
        pass


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    base = f"http://127.0.0.1:{srv.server_port}"
    _Handler.routes = {
        "/robots.txt": ("text/plain", "User-agent: *\nAllow: /\n"),
        "/feed.xml": ("application/rss+xml", _feed(base)),
        "/a1": ("text/html", _page("Rule proposed", BODY_A)),
        "/a2": ("text/html", _page("Rule proposed syndicated", BODY_B)),
        "/a3": ("text/html", _page("Harvest outlook", BODY_C)),
    }
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield base
    srv.shutdown()


@pytest.fixture()
def conn():
    try:
        admin = psycopg.connect(
            "postgresql://postgres:postgres@127.0.0.1:5432/postgres", autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("no local postgres")
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname='newsassistant_test'")
        if not cur.fetchone():
            cur.execute("CREATE DATABASE newsassistant_test")
    admin.close()
    c = db.connect(TEST_DB)
    db.migrate(c)
    with c.cursor() as cur:
        cur.execute("TRUNCATE fetch_log, stories, story_documents, story_entities, story_events, claims, "
                    "documents, sources RESTART IDENTITY CASCADE")
    c.commit()
    yield c
    c.close()


def _add_source(conn, base):
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO sources (key, name, kind, url, evidence_tier)
                       VALUES ('local-test','Local','rss',%s,5)""", (base + "/feed.xml",))
    conn.commit()


def test_full_ingest_round(conn, server, tmp_path: Path):
    cfg = Config(database_url=TEST_DB, data_dir=tmp_path)
    _add_source(conn, server)

    stats = run_once(conn, cfg, only_key="local-test")
    assert stats.errors == 0
    assert stats.new_docs == 2          # a1 + a3
    assert stats.near_dup == 1          # a2 ≈ a1

    with conn.cursor() as cur:
        cur.execute("SELECT url_canonical, status, content_ref, near_dup_of "
                    "FROM documents ORDER BY id")
        rows = cur.fetchall()
    # utm 变体被 URL 规范化折叠：4 个 feed 条目 → 3 行文档
    assert len(rows) == 3
    by_url = {u.rsplit("/", 1)[-1]: (st, ref, nd) for u, st, ref, nd in rows}
    assert by_url["a1"][0] == "ok"
    assert by_url["a3"][0] == "ok"
    assert by_url["a2"][0] == "near_dup"
    assert by_url["a2"][2] is not None            # near_dup_of 指向 a1
    # 内容真实落盘且可回读
    ref = by_url["a1"][1]
    assert (tmp_path / ref).exists()
    assert "clause 7" in (tmp_path / ref).read_text()

    # 幂等：重跑一轮，URL 已知 → 零新增
    stats2 = run_once(conn, cfg, only_key="local-test")
    assert (stats2.new_docs, stats2.near_dup, stats2.errors) == (0, 0, 0)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM documents")
        assert cur.fetchone()[0] == 3
        cur.execute("SELECT count(*) FROM fetch_log WHERE outcome='ok'")
        assert cur.fetchone()[0] == 2
