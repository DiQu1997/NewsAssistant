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
