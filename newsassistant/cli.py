"""CLI：na init-db | na sources sync/list | na ingest | na stats"""
from __future__ import annotations

import argparse
import logging
import sys

from . import db
from .config import load
from .ingest import run_once
from .sources import load_specs, sync_sources


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="na", description="NewsAssistant 采集层")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="建库表（幂等迁移）")
    ps = sub.add_parser("sources", help="源注册表")
    ps.add_argument("action", choices=["sync", "list"])
    pi = sub.add_parser("ingest", help="采集一轮（只处理到期的源）")
    pi.add_argument("--source", help="只跑指定 key 的源（忽略到期判断）")
    pe = sub.add_parser("extract", help="抽取待处理文档（Claude Agent SDK，走订阅登录态）")
    pe.add_argument("--limit", type=int, default=20)
    pe.add_argument("--model", help="模型别名或 ID（默认由 CLI 配置决定）")
    pe.add_argument("--concurrency", type=int, default=4)
    pa = sub.add_parser("assign", help="归并：把已抽取文档归档进故事（Agent SDK 裁决）")
    pa.add_argument("--limit", type=int, default=50)
    pa.add_argument("--model", help="裁决模型（默认由 CLI 配置决定）")
    sub.add_parser("stories", help="列活跃故事及标量")
    sub.add_parser("stats", help="库存统计")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s")
    for noisy in ("httpx", "httpcore", "trafilatura", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    cfg = load()
    conn = db.connect(cfg.database_url)
    try:
        if args.cmd == "init-db":
            applied = db.migrate(conn)
            print(f"migrations applied: {applied or '(none, up to date)'}")

        elif args.cmd == "sources" and args.action == "sync":
            n = sync_sources(conn, load_specs(cfg.sources_dir))
            print(f"synced {n} sources")

        elif args.cmd == "sources" and args.action == "list":
            with conn.cursor() as cur:
                cur.execute("""SELECT key, kind, evidence_tier, enabled,
                               coalesce(last_status,'-'), last_fetch_at
                               FROM sources ORDER BY evidence_tier, key""")
                for k, kind, tier, en, st, at in cur.fetchall():
                    print(f"L{tier} {'✓' if en else '✗'} {k:26s} {kind:5s} "
                          f"{st:14s} {at or '(never)'}")

        elif args.cmd == "extract":
            import asyncio
            from .llm_extract import ClaudeExtractor, run_extraction
            st = asyncio.run(run_extraction(
                conn, cfg, ClaudeExtractor(model=args.model), limit=args.limit,
                concurrency=args.concurrency))
            print(f"docs={st['docs']} claims={st['claims']} "
                  f"entities={st['entities']} errors={st['errors']}")

        elif args.cmd == "assign":
            import asyncio
            from .merge import ClaudeJudge, run_assignment
            st = asyncio.run(run_assignment(
                conn, cfg, ClaudeJudge(model=args.model), limit=args.limit))
            print(f"docs={st['docs']} new_stories={st['new_stories']} "
                  f"absorbed={st['absorbed']} errors={st['errors']}")

        elif args.cmd == "stories":
            with conn.cursor() as cur:
                cur.execute("""SELECT id, title, scalars, state,
                               to_char(updated_at,'MM-DD HH24:MI')
                               FROM stories ORDER BY updated_at DESC LIMIT 40""")
                for sid, t, sc, state, at in cur.fetchall():
                    sc = sc or {}
                    print(f"#{sid:<4d} docs={sc.get('docs',0):<3} "
                          f"src={sc.get('breadth',0):<2} cons={sc.get('consensus','-'):>3}% "
                          f"[{state}] {at}  {t[:64]}")

        elif args.cmd == "ingest":
            s = run_once(conn, cfg, only_key=args.source)
            print(f"sources={s.sources} new={s.new_docs} "
                  f"dup_exact={s.dup_exact} near_dup={s.near_dup} errors={s.errors}")

        elif args.cmd == "stats":
            with conn.cursor() as cur:
                cur.execute("""SELECT s.key, count(d.id),
                                 count(*) FILTER (WHERE d.status='ok'),
                                 count(*) FILTER (WHERE d.status IN ('dup_exact','near_dup'))
                               FROM sources s LEFT JOIN documents d ON d.source_id=s.id
                               GROUP BY s.key ORDER BY 2 DESC""")
                total = ok = dup = 0
                for k, n, n_ok, n_dup in cur.fetchall():
                    total += n; ok += n_ok; dup += n_dup
                    print(f"{k:26s} docs={n:5d} ok={n_ok:5d} dup={n_dup:4d}")
                print(f"{'TOTAL':26s} docs={total:5d} ok={ok:5d} dup={dup:4d}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
