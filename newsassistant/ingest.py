"""采集一轮 —— 阶段 1 的主干。全程无 LLM。

每个到期的 RSS/Atom 源：
  条件请求拉 feed → 解析条目 → URL 规范化（第一道去重闸）
  → 新 URL 才抓正文页（robots 感知）→ trafilatura 抽正文
  → sha256 精确去重 → simhash 近重标记 → 内容落文件、指针入库

失败按源隔离：一个源坏了不影响其余。每轮每源写一条 fetch_log。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import psycopg

from .config import Config
from .contentstore import ContentStore
from .extract import extract_article
from .feeds import parse_feed
from .fetch import Fetcher
from .simhash import from_signed, hamming, simhash64, to_signed
from .urlnorm import canonical_url

log = logging.getLogger(__name__)


@dataclass
class SourceRow:
    id: int
    key: str
    kind: str
    url: str
    etag: str | None
    last_modified: str | None


@dataclass
class RoundStats:
    sources: int = 0
    new_docs: int = 0
    dup_exact: int = 0
    near_dup: int = 0
    errors: int = 0


def _due_sources(conn: psycopg.Connection, only_key: str | None) -> list[SourceRow]:
    sql = """SELECT id, key, kind, url, etag, last_modified FROM sources
             WHERE enabled AND (last_fetch_at IS NULL
                OR last_fetch_at < now() - make_interval(mins => cadence_minutes))"""
    args: tuple = ()
    if only_key:
        sql = "SELECT id, key, kind, url, etag, last_modified FROM sources WHERE key = %s"
        args = (only_key,)
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return [SourceRow(*r) for r in cur.fetchall()]


def _url_known(conn: psycopg.Connection, url_canonical: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM documents WHERE url_canonical = %s", (url_canonical,))
        return cur.fetchone() is not None


def _find_exact(conn: psycopg.Connection, sha: str) -> int | None:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM documents WHERE content_sha256 = %s LIMIT 1", (sha,))
        r = cur.fetchone()
        return r[0] if r else None


def _find_near(conn: psycopg.Connection, sh: int, cfg: Config) -> int | None:
    """近重候选：回看窗口内逐条比汉明距离。
    线性扫在 10^5 量级毫无压力；到 10^6 再换 bit-band 索引，不提前优化。"""
    with conn.cursor() as cur:
        cur.execute("""SELECT id, simhash FROM documents
                       WHERE simhash IS NOT NULL AND status = 'ok'
                         AND fetched_at > now() - make_interval(days => %s)""",
                    (cfg.near_dup_days,))
        best, best_d = None, cfg.near_dup_hamming + 1
        for doc_id, other in cur.fetchall():
            d = hamming(sh, from_signed(other))
            if d < best_d:
                best, best_d = doc_id, d
    return best


def _ingest_source(conn: psycopg.Connection, cfg: Config, fetcher: Fetcher,
                   store: ContentStore, src: SourceRow, stats: RoundStats) -> None:
    if src.kind not in ("rss", "atom"):
        _log_fetch(conn, src.id, None, "error", note=f"kind {src.kind} not supported in phase 1")
        return

    res = fetcher.get(src.url, etag=src.etag, last_modified=src.last_modified)
    if res.not_modified:
        _touch(conn, src.id, "not_modified")
        _log_fetch(conn, src.id, res.status, "not_modified")
        return
    if not res.ok:
        stats.errors += 1
        _touch(conn, src.id, f"error:{res.error or res.status}")
        _log_fetch(conn, src.id, res.status, "error", note=res.error)
        return

    items = parse_feed(res.body)[: cfg.max_items_per_source]
    new = dup = 0
    for it in items:
        try:
            u = canonical_url(it.url)
        except Exception:
            continue
        if _url_known(conn, u):
            continue

        page = fetcher.get(it.url, check_robots=True)
        text = title = author = None
        status, meta = "ok", {}
        if page.ok:
            ex = extract_article(page.body, url=it.url)
            text, title, author = ex.text, ex.title or it.title, ex.author or it.author
        if not text or len(text) < 200:
            # 抽取失败或过短 → 回退 feed 摘要（部分 L1/L3 源 feed 本身就是全文）
            if it.summary and len(it.summary) >= 80:
                text, meta["extracted"] = it.summary, False
            else:
                status = "fetch_failed" if not page.ok else "extract_failed"
                meta["fetch_error"] = page.error or page.status
        title = title or it.title

        sha = ref = None
        sh_signed = None
        if text:
            sha, ref = store.put(text)
            exact = _find_exact(conn, sha)
            if exact:
                status, meta["dup_of"] = "dup_exact", exact
                stats.dup_exact += 1
                dup += 1
            else:
                sh = simhash64(text)
                sh_signed = to_signed(sh)
                near = _find_near(conn, sh, cfg)
                if near:
                    status, meta["near_of"] = "near_dup", near
                    stats.near_dup += 1
                    dup += 1

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO documents (source_id, url, url_canonical, title, author,
                    published_at, content_ref, content_sha256, simhash, status,
                    near_dup_of, meta)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (url_canonical) DO NOTHING""",
                (src.id, it.url, u, title, author, it.published_at, ref, sha,
                 sh_signed, status,
                 meta.get("dup_of") or meta.get("near_of"),
                 psycopg.types.json.Json(meta)))
        conn.commit()
        if status == "ok":
            new += 1
            stats.new_docs += 1

    with conn.cursor() as cur:
        cur.execute("""UPDATE sources SET etag=%s, last_modified=%s,
                       last_fetch_at=now(), last_status='ok' WHERE id=%s""",
                    (res.etag, res.last_modified, src.id))
    conn.commit()
    _log_fetch(conn, src.id, res.status, "ok", new, dup)
    log.info("source %s: %d new, %d dup", src.key, new, dup)


def _touch(conn: psycopg.Connection, source_id: int, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE sources SET last_fetch_at=now(), last_status=%s WHERE id=%s",
                    (status, source_id))
    conn.commit()


def _log_fetch(conn: psycopg.Connection, source_id: int, http_status: int | None,
               outcome: str, new_docs: int = 0, dup_docs: int = 0,
               note: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO fetch_log (source_id, http_status, outcome,
                       new_docs, dup_docs, note) VALUES (%s,%s,%s,%s,%s,%s)""",
                    (source_id, http_status, outcome, new_docs, dup_docs, note))
    conn.commit()


def run_once(conn: psycopg.Connection, cfg: Config,
             only_key: str | None = None) -> RoundStats:
    stats = RoundStats()
    store = ContentStore(cfg.data_dir)
    fetcher = Fetcher(cfg.user_agent, cfg.http_timeout, cfg.respect_robots)
    try:
        for src in _due_sources(conn, only_key):
            stats.sources += 1
            try:
                _ingest_source(conn, cfg, fetcher, store, src, stats)
            except Exception:
                conn.rollback()
                stats.errors += 1
                log.exception("source %s failed", src.key)
                _touch(conn, src.id, "error:exception")
                _log_fetch(conn, src.id, None, "error", note="exception")
    finally:
        fetcher.close()
    return stats
