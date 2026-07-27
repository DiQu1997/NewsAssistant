"""API 类源（阶段 1.5）—— 适配器解析、curl 通道、端到端入库。

不碰外网：适配器测的是真实响应样本（fixtures/edgar_fulltext_8k.json，
2026-07-27 从 efts.sec.gov 实拉后裁到 6 条），HTTP 走本地服务器。
端到端用独立库 newsassistant_test_edgar，连不上则 skip。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg
import pytest

from newsassistant import db
from newsassistant.apisources import ADAPTERS, get_adapter, parse_edgar_fulltext
from newsassistant.config import Config
from newsassistant.fetch import FetchResult, Fetcher
from newsassistant.ingest import run_once

FIX = Path(__file__).parent / "fixtures"
EDGAR_JSON = (FIX / "edgar_fulltext_8k.json").read_bytes()
REQ_URL = "https://efts.sec.gov/LATEST/search-index?q=&forms=8-K"
TEST_DB = "postgresql://postgres:postgres@127.0.0.1:5432/newsassistant_test_edgar"
UA = "NewsAssistantTest/0.1 (test@example.com)"


# ── 适配器注册表 ────────────────────────────────────────────
def test_registry_lookup():
    a = get_adapter("edgar_fulltext")
    assert a is not None and a.parse is parse_edgar_fulltext
    assert a.min_interval >= 1.0                 # SEC 合规：请求间隔 ≥1s
    assert a.headers.get("Accept") == "application/json"
    assert get_adapter("no-such-adapter") is None
    assert get_adapter(None) is None
    assert "edgar_fulltext" in ADAPTERS


def test_adapter_wait_enforces_interval(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("newsassistant.apisources.time.sleep", slept.append)
    clock = iter([100.0, 100.0, 100.2, 100.2])   # 两次调用相隔 0.2s
    monkeypatch.setattr("newsassistant.apisources.time.monotonic", lambda: next(clock))
    a = get_adapter("edgar_fulltext")
    a.wait()
    a.wait()
    assert slept and 0.7 < slept[0] <= 1.0       # 补足到 1s


# ── EDGAR 适配器解析 ────────────────────────────────────────
def test_edgar_parses_real_sample():
    items = parse_edgar_fulltext(EDGAR_JSON, REQ_URL)
    assert len(items) == 6
    assert len({i.url for i in items}) == 6      # 每份备案一个唯一 URL

    it = items[0]
    # _id "0002077096-26-000223:ea0299296-8k_luxfer.htm" + ciks[0] → 归档路径
    assert it.url == ("https://www.sec.gov/Archives/edgar/data/1096056/"
                      "000207709626000223/ea0299296-8k_luxfer.htm")
    assert it.title.startswith("8-K · LUXFER HOLDINGS PLC")
    assert it.author and "LUXFER" in it.author
    assert it.guid == "0002077096-26-000223:ea0299296-8k_luxfer.htm"
    assert it.published_at is not None and it.published_at.tzinfo is not None
    assert (it.published_at.year, it.published_at.month, it.published_at.day) \
        == (2026, 7, 27)
    # 摘要 = 备案的结构化事实（fetch_article=false，这就是全部载荷）
    assert "Form: 8-K" in it.summary
    assert "Items: 1.01, 8.01, 9.01" in it.summary       # 列表字段扁平化
    assert "Accession: 0002077096-26-000223" in it.summary
    assert "Document: CURRENT REPORT — ea0299296-8k_luxfer.htm" in it.summary
    assert "  " not in it.title                          # display_names 的多空格已归一

    # 修订件（8-K/A）不被特殊对待，form 原样带出
    assert any(i.title.startswith("8-K/A · ") for i in items)


def test_edgar_multi_cik_uses_first_and_strips_leading_zeros():
    items = parse_edgar_fulltext(EDGAR_JSON, REQ_URL)
    multi = [i for i in items if "brx-20260727.htm" in i.url]
    assert len(multi) == 1
    assert multi[0].url.startswith(
        "https://www.sec.gov/Archives/edgar/data/1581068/000158106826000027/")


def test_edgar_skips_malformed_hits_and_handles_xsl():
    payload = {"hits": {"hits": [
        {"_id": "no-colon-id", "_source": {"adsh": "x", "ciks": ["1"]}},   # 无文件名
        {"_id": "0000000000-26-000001:doc.htm", "_source": {"ciks": []}},  # 无 cik
        {"_id": "0000000000-26-000002:doc.htm",
         "_source": {"adsh": "0000000000-26-000002", "ciks": ["0000000009"],
                     "form": "8-K", "xsl": "xslF345X03"}},                 # 有 xsl 变换
    ]}}
    items = parse_edgar_fulltext(json.dumps(payload).encode(), REQ_URL)
    assert len(items) == 1
    assert items[0].url == ("https://www.sec.gov/Archives/edgar/data/9/"
                            "000000000026000002/xslF345X03/doc.htm")
    assert items[0].published_at is None          # 缺 file_date 不臆造时间
    assert items[0].title == "8-K 0000000000-26-000002"   # 缺 filer 时退回 accession


def test_edgar_empty_response():
    assert parse_edgar_fulltext(b'{"hits": {"hits": []}}', REQ_URL) == []
    assert parse_edgar_fulltext(b"{}", REQ_URL) == []


# ── 本地 HTTP 服务器（curl 通道与端到端共用）────────────────
class _Handler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[str, bytes]] = {}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path not in self.routes:
            self.send_response(404); self.end_headers(); return
        ctype, raw = self.routes[path]
        if self.headers.get("If-None-Match") == '"v1"':
            self.send_response(304)
            self.send_header("ETag", '"v1"')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("ETag", '"v1"')
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    _Handler.routes = {
        "/robots.txt": ("text/plain", b"User-agent: *\nAllow: /\n"),
        "/edgar.json": ("application/json", EDGAR_JSON),
    }
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


# ── curl 通道：与 httpx 通道语义一致 ─────────────────────────
def test_curl_channel_matches_httpx(server):
    f = Fetcher(UA, timeout=15)
    try:
        a = f.get(server + "/edgar.json", via="httpx")
        b = f.get(server + "/edgar.json", via="curl")
    finally:
        f.close()
    assert a.ok and b.ok
    assert a.body == b.body == EDGAR_JSON
    assert b.etag == a.etag == '"v1"'
    assert b.final_url == server + "/edgar.json"


def test_curl_channel_conditional_and_errors(server):
    f = Fetcher(UA, timeout=15)
    try:
        assert f.get(server + "/edgar.json", etag='"v1"', via="curl").not_modified
        missing = f.get(server + "/nope", via="curl")
        assert missing.status == 404 and missing.body is None
        dead = f.get("http://127.0.0.1:1/x", via="curl")
        assert dead.status == 0 and dead.error.startswith("curl:")
        with pytest.raises(ValueError):
            f.get(server + "/edgar.json", via="telepathy")
    finally:
        f.close()


def test_via_auto_falls_back_to_curl(monkeypatch, server):
    """auto 的意义：部署环境是否被 TLS 指纹拦截无法预知，被拦就换通道。"""
    calls: list[str] = []

    def fake_raw(self, url, headers, via):
        calls.append(via)
        if via == "httpx":
            return FetchResult(status=403, body=None, error="blocked")
        return FetchResult(status=200, body=b"via-curl")

    monkeypatch.setattr(Fetcher, "_raw", fake_raw)
    f = Fetcher(UA)
    assert f.get("https://blocked.example/x", via="auto").body == b"via-curl"
    assert calls == ["httpx", "curl"]

    calls.clear()
    assert f.get("https://blocked.example/x", via="httpx").status == 403
    assert calls == ["httpx"]                    # 显式 httpx 不回退


def test_via_auto_keeps_httpx_result_when_ok(monkeypatch):
    monkeypatch.setattr(Fetcher, "_raw",
                        lambda self, u, h, via: FetchResult(200, b"via-" + via.encode()))
    f = Fetcher(UA)
    assert f.get("https://ok.example/x", via="auto").body == b"via-httpx"


# ── 端到端：kind=api 走完整管线 ──────────────────────────────
@pytest.fixture()
def conn():
    try:
        admin = psycopg.connect(
            "postgresql://postgres:postgres@127.0.0.1:5432/postgres", autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("no local postgres")
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname='newsassistant_test_edgar'")
        if not cur.fetchone():
            cur.execute("CREATE DATABASE newsassistant_test_edgar")
    admin.close()
    c = db.connect(TEST_DB)
    db.migrate(c)
    with c.cursor() as cur:
        cur.execute("TRUNCATE fetch_log, story_documents, story_events, claims, "
                    "documents, sources RESTART IDENTITY CASCADE")
    c.commit()
    yield c
    c.close()


def test_api_source_end_to_end(conn, server, tmp_path: Path):
    cfg = Config(database_url=TEST_DB, data_dir=tmp_path)
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO sources (key, name, kind, url, evidence_tier,
                         adapter, fetch_article, fetch_via)
                       VALUES ('edgar-test','EDGAR test','api',%s,2,
                         'edgar_fulltext', false, 'httpx')""",
                    (server + "/edgar.json",))
    conn.commit()

    stats = run_once(conn, cfg, only_key="edgar-test")
    assert stats.errors == 0
    assert stats.new_docs + stats.near_dup + stats.dup_exact == 6

    with conn.cursor() as cur:
        cur.execute("SELECT url_canonical, title, content_ref, published_at, status "
                    "FROM documents ORDER BY id")
        rows = cur.fetchall()
    assert len(rows) == 6
    assert all(r[0].startswith("https://www.sec.gov/Archives/edgar/data/") for r in rows)
    assert all(r[1] and r[2] and r[3] for r in rows)   # 标题/正文指针/时间齐全
    # 条目摘要即正文，落盘可回读
    body = (tmp_path / rows[0][2]).read_text()
    assert "Accession:" in body and "Filer:" in body

    # 幂等：条件请求命中 ETag → 第二轮 304，零新增
    again = run_once(conn, cfg, only_key="edgar-test")
    assert (again.new_docs, again.errors) == (0, 0)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM documents")
        assert cur.fetchone()[0] == 6
        cur.execute("SELECT outcome, count(*) FROM fetch_log GROUP BY outcome")
        assert dict(cur.fetchall()) == {"ok": 1, "not_modified": 1}


def test_api_source_unknown_adapter_is_isolated(conn, server, tmp_path: Path):
    """错字不该炸整轮，而应记成该源的一条 error。"""
    cfg = Config(database_url=TEST_DB, data_dir=tmp_path)
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO sources (key, name, kind, url, evidence_tier,
                         adapter, fetch_article)
                       VALUES ('bad-adapter','Bad','api',%s,2,'nope',false)""",
                    (server + "/edgar.json",))
    conn.commit()

    stats = run_once(conn, cfg, only_key="bad-adapter")
    assert (stats.errors, stats.new_docs) == (1, 0)
    with conn.cursor() as cur:
        cur.execute("SELECT outcome, note FROM fetch_log ORDER BY id DESC LIMIT 1")
        outcome, note = cur.fetchone()
    assert outcome == "error" and "nope" in note
