"""采集一轮 —— 阶段 1 的主干。全程无 LLM。

每个到期的源：
  条件请求拉清单（RSS/Atom feed，或 kind=api 的 JSON 响应经适配器解析）
  → 统一的条目列表 → URL 规范化（第一道去重闸）
  → 新 URL 才抓正文页（robots 感知）→ trafilatura 抽正文
  → sha256 精确去重 → simhash 近重标记 → 内容落文件、指针入库

feed 与 api 只在"怎么拿到条目列表"这一步不同，之后的管线一字不差地共用。

失败按源隔离：一个源坏了不影响其余。每轮每源写一条 fetch_log。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import psycopg

from .apisources import get_adapter
from .config import Config
from .contentstore import ContentStore
from .extract import extract_article
from .feeds import FeedItem, parse_feed, parse_sitemap, strip_html
from .fetch import FetchResult, Fetcher
from .simhash import from_signed, hamming, simhash64, to_signed
from .urlnorm import canonical_url

log = logging.getLogger(__name__)

_COLUMNS = "id, key, kind, url, etag, last_modified, fetch_article, adapter, fetch_via"


@dataclass
class SourceRow:
    id: int
    key: str
    kind: str
    url: str
    etag: str | None
    last_modified: str | None
    fetch_article: bool
    adapter: str | None
    fetch_via: str


@dataclass
class RoundStats:
    sources: int = 0
    new_docs: int = 0
    dup_exact: int = 0
    near_dup: int = 0
    errors: int = 0


def _due_sources(conn: psycopg.Connection, only_key: str | None) -> list[SourceRow]:
    sql = f"""SELECT {_COLUMNS} FROM sources
              WHERE enabled AND (last_fetch_at IS NULL
                 OR last_fetch_at < now() - make_interval(mins => cadence_minutes))"""
    args: tuple = ()
    if only_key:
        sql = f"SELECT {_COLUMNS} FROM sources WHERE key = %s"
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


def _collect_items(fetcher: Fetcher, src: SourceRow
                   ) -> tuple[FetchResult, list[FeedItem] | None, str | None]:
    """拿到该源本轮的条目列表 —— feed 与 api 的唯一分岔点。

    返回 (拉取结果, 条目 or None, 出错说明)；条目为 None 表示本轮没有可处理的条目
    （未改变、拉取失败或解析失败），由调用方按 res 决定记哪种 outcome。
    """
    if src.kind in ("rss", "atom", "sitemap"):
        res = fetcher.get(src.url, etag=src.etag, last_modified=src.last_modified,
                          via=src.fetch_via)

        def parse(body: bytes) -> list[FeedItem]:
            return parse_sitemap(body) if src.kind == "sitemap" else parse_feed(body)
    elif src.kind == "api":
        adapter = get_adapter(src.adapter)
        if adapter is None:
            return (FetchResult(status=0, body=None, error="unknown_adapter"), None,
                    f"unknown adapter {src.adapter!r}")
        adapter.wait()                       # 源站速率合规由适配器声明
        res = fetcher.get(src.url, etag=src.etag, last_modified=src.last_modified,
                          headers=adapter.headers, via=src.fetch_via)

        def parse(body: bytes) -> list[FeedItem]:
            return adapter.parse(body, src.url)
    else:
        return (FetchResult(status=0, body=None, error="unsupported_kind"), None,
                f"kind {src.kind} not supported")

    if not res.ok:
        return res, None, None
    try:
        return res, parse(res.body), None
    except Exception as e:      # 畸形响应不该拖垮整轮
        log.warning("source %s: 解析失败 %s: %s", src.key, type(e).__name__, e)
        return (FetchResult(status=res.status, body=None, error="parse_failed"), None,
                f"parse failed: {type(e).__name__}: {e}")


def _ingest_source(conn: psycopg.Connection, cfg: Config, fetcher: Fetcher,
                   store: ContentStore, src: SourceRow, stats: RoundStats) -> None:
    res, items, note = _collect_items(fetcher, src)
    if res.not_modified:
        _touch(conn, src.id, "not_modified")
        _log_fetch(conn, src.id, res.status, "not_modified")
        return
    if items is None:
        stats.errors += 1
        _touch(conn, src.id, f"error:{res.error or res.status}")
        _log_fetch(conn, src.id, res.status, "error", note=note or res.error)
        return

    items = items[: cfg.max_items_per_source]
    new = dup = 0
    for it in items:
        try:
            u = canonical_url(it.url)
        except Exception:
            continue
        if _url_known(conn, u):
            continue

        text = title = author = None
        status, meta = "ok", {}
        if src.fetch_article:
            page = fetcher.get(it.url, check_robots=True, via=src.fetch_via)
            if page.ok:
                ex = extract_article(page.body, url=it.url)
                text, title, author = ex.text, ex.title or it.title, ex.author or it.author
            if not text or len(text) < 200:
                # 抽取失败或过短 → 回退 feed 摘要
                if it.summary and len(strip_html(it.summary)) >= 80:
                    text, meta["extracted"] = strip_html(it.summary), False
                else:
                    status = "fetch_failed" if not page.ok else "extract_failed"
                    meta["fetch_error"] = page.error or page.status
        else:
            # feed 条目即全部载荷（fetch_article=false）：不抓页面，直接用摘要
            if it.summary and strip_html(it.summary):
                text, meta["extracted"] = strip_html(it.summary), False
            else:
                status, meta["fetch_error"] = "extract_failed", "empty feed summary"
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
