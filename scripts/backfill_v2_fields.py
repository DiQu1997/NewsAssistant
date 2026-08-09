"""一次性回填 V2 字段（summary/event_signature/importance/domains）。

只更新 documents 的四个新字段与所属故事的聚合，不碰 claims/entities ——
它们已在首次抽取时落库且与故事绑定，重插会造成重复与孤儿。

用法：NA_DATABASE_URL=... python scripts/backfill_v2_fields.py [--hours 72] [--model haiku]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from newsassistant.config import load as load_config  # noqa: E402
from newsassistant.contentstore import ContentStore  # noqa: E402
from newsassistant.llm_extract import ClaudeExtractor  # noqa: E402
from newsassistant.merge import _update_scalars  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=72)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--concurrency", type=int, default=3)
    args = ap.parse_args()

    cfg = load_config()
    conn = psycopg.connect(cfg.database_url)
    store = ContentStore(cfg.data_dir, cfg.drive_remote)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.id, d.title, d.content_ref FROM documents d
            JOIN sources s ON s.id=d.source_id
            WHERE d.status='ok' AND s.section='news'
              AND d.extracted_at IS NOT NULL AND d.importance IS NULL
              AND d.content_ref IS NOT NULL
              AND d.fetched_at > now() - make_interval(hours => %s)
            ORDER BY d.id DESC""", (args.hours,))
        rows = cur.fetchall()
    print(f"{len(rows)} docs to backfill", flush=True)

    docs = []
    for doc_id, title, ref in rows:
        try:
            docs.append((doc_id, title, store.get(ref)))
        except OSError:
            pass

    ex = ClaudeExtractor(model=args.model)
    batches = [docs[i:i + args.batch] for i in range(0, len(docs), args.batch)]
    sem = asyncio.Semaphore(args.concurrency)
    done = [0]

    async def one(batch):
        async with sem:
            try:
                res = await ex.extract_batch([(t, ti) for _, ti, t in batch])
            except Exception as e:
                print(f"batch failed: {e}", flush=True)
                return []
        return list(zip(batch, res))

    results = await asyncio.gather(*(one(b) for b in batches))
    touched_stories: set[int] = set()
    with conn.cursor() as cur:
        for pairs in results:
            for (doc_id, _t, _x), r in pairs:
                if r.error:
                    continue
                cur.execute("""UPDATE documents SET summary=%s, event_signature=%s,
                               importance=%s, domains=%s WHERE id=%s""",
                            (r.summary, r.event_signature, r.importance,
                             r.domains or [], doc_id))
                cur.execute("SELECT story_id FROM story_documents WHERE document_id=%s",
                            (doc_id,))
                for (sid,) in cur.fetchall():
                    touched_stories.add(sid)
                done[0] += 1
        conn.commit()
        print(f"updated {done[0]} docs; refreshing {len(touched_stories)} stories",
              flush=True)
        for sid in touched_stories:
            _update_scalars(cur, sid)
        conn.commit()
    print("backfill done", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
