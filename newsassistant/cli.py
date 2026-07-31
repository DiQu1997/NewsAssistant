"""CLI：na init-db | na sources sync/list | na ingest | na stats"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

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
    pe.add_argument("--concurrency", type=int, default=2)
    pe.add_argument("--batch-size", type=int, default=8,
                    help="每次 SDK 调用打包的文档数（会话底盘 ~40k tokens 摊薄）")
    pa = sub.add_parser("assign", help="归并：把已抽取文档归档进故事（Agent SDK 裁决）")
    pa.add_argument("--limit", type=int, default=50)
    pa.add_argument("--model", help="裁决模型（默认由 CLI 配置决定）")
    pa.add_argument("--batch-size", type=int, default=6,
                    help="每波上限；只有 IDF 合格实体不相交的文档才会同波")
    sub.add_parser("stories", help="列活跃故事及标量")
    pr = sub.add_parser("resolve-entities", help="实体消歧（确定性候选 + LLM 裁决）")
    pr.add_argument("--limit", type=int, default=40)
    pr.add_argument("--model", help="裁决模型（默认由 CLI 配置决定）")
    py = sub.add_parser("synthesize", help="合成：活跃故事的综述/时间线/开放问题（每句带引用）")
    py.add_argument("--limit", type=int, default=10)
    py.add_argument("--min-docs", type=int, default=2)
    py.add_argument("--model", help="合成模型（默认由 CLI 配置决定）")
    pp = sub.add_parser("picture", help="态势图：分析员读近 48h 素材产出剧场/观点/复盘")
    pp.add_argument("--model", help="分析模型（默认由 policy 决定）")
    pp.add_argument("--desk", default="all",
                    help="general | markets | all（默认全跑）")
    sub.add_parser("syndicate", help="转述溯源（确定性：近重组内跨源 → syndication_of）")
    sub.add_parser("lifecycle", help="故事生命周期推进（active→dormant→archived）")
    pv = sub.add_parser("story", help="看单个故事：综述（带引用）、时间线、开放问题")
    pv.add_argument("id", type=int)
    pn = sub.add_parser("snapshot", help="导出 dashboard 数据快照（Postgres → JSON）")
    pn.add_argument("--out", default="prototypes/dashboard/data/snapshot.json")
    pch = sub.add_parser("channels", help="频道（保存的查询）")
    pch.add_argument("action", choices=["sync", "list"])
    pch.add_argument("--file", default="sources/channels.yaml")
    pc = sub.add_parser("run-cycle", help="推进一轮管线（阶段按各自节奏，整轮互斥）")
    pc.add_argument("--force", action="store_true", help="忽略节奏，全阶段跑一遍")
    pc.add_argument("--stage", help="只跑指定阶段（同样忽略节奏）")
    pc.add_argument("--model", help="LLM 阶段用的模型")
    pw = sub.add_parser("serve", help="常驻服务：读接口 + 进程内调度器")
    pw.add_argument("--host", default="127.0.0.1")
    pw.add_argument("--port", type=int, default=8787)
    pw.add_argument("--no-scheduler", action="store_true",
                    help="只提供读接口，不推进管线")
    pw.add_argument("--model", help="LLM 阶段用的模型")
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
            from .llm_extract import make_extractor, run_extraction
            st = asyncio.run(run_extraction(
                conn, cfg,
                make_extractor(args.model or cfg.stage_model("extract")),
                limit=args.limit,
                concurrency=args.concurrency, batch_size=args.batch_size))
            print(f"docs={st['docs']} claims={st['claims']} "
                  f"entities={st['entities']} errors={st['errors']}")

        elif args.cmd == "assign":
            import asyncio
            from .merge import ClaudeJudge, run_assignment
            st = asyncio.run(run_assignment(
                conn, cfg,
                ClaudeJudge(model=args.model or cfg.stage_model("assign")),
                limit=args.limit,
                batch_size=args.batch_size))
            print(f"docs={st['docs']} new_stories={st['new_stories']} "
                  f"absorbed={st['absorbed']} waves={st['waves']} "
                  f"errors={st['errors']}")

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

        elif args.cmd == "resolve-entities":
            import asyncio
            from .entity_resolve import ClaudeResolver, run_resolution
            st = asyncio.run(run_resolution(
                conn,
                ClaudeResolver(model=args.model
                               or cfg.stage_model("resolve-entities")),
                limit=args.limit))
            print(f"pairs={st['pairs']} merged={st['merged']} "
                  f"kept={st['kept']} errors={st['errors']}")

        elif args.cmd == "synthesize":
            import asyncio
            from .synth import ClaudeSynthesizer, run_synthesis
            st = asyncio.run(run_synthesis(
                conn,
                ClaudeSynthesizer(model=args.model
                                  or cfg.stage_model("synthesize")),
                limit=args.limit, min_docs=args.min_docs))
            print(f"stories={st['stories']} sentences={st['sentences']} "
                  f"dropped={st['dropped']} errors={st['errors']}")

        elif args.cmd == "picture":
            import asyncio
            from .analyst import ClaudeAnalyst, run_all_desks, run_picture
            an = ClaudeAnalyst(model=args.model or cfg.stage_model("picture"))
            if args.desk == "all":
                st = asyncio.run(run_all_desks(conn, an))
            else:
                st = asyncio.run(run_picture(conn, an, args.desk))
            print(st)

        elif args.cmd == "syndicate":
            from .syndicate import run_syndication
            st = run_syndication(conn)
            print(f"marked={st['marked']} same_source={st['same_source']} "
                  f"total_near={st['total_near']}")

        elif args.cmd == "lifecycle":
            from .lifecycle import run_lifecycle
            st = run_lifecycle(conn)
            print(f"dormant={st['dormant']} archived={st['archived']} "
                  f"total_active={st['total_active']}")

        elif args.cmd == "story":
            with conn.cursor() as cur:
                cur.execute("""SELECT title, summary, timeline, open_questions,
                               scalars, synthesized_at FROM stories WHERE id=%s""",
                            (args.id,))
                row = cur.fetchone()
                if not row:
                    print(f"story {args.id} not found")
                    return 1
                title, summary, timeline, oq, sc, syn_at = row
                sc = sc or {}
                print(f"#{args.id} {title}")
                print(f"  docs={sc.get('docs')} breadth={sc.get('breadth')} "
                      f"consensus={sc.get('consensus')}% "
                      f"synthesized={syn_at or '(never)'}\n")
                for s in (summary or []):
                    cites = ",".join(str(i) for i in s["claim_ids"])
                    print(f"  {s['text']}  [{cites}]")
                if timeline:
                    print("\n  时间线：")
                    for t in timeline:
                        print(f"    {t['when']}: {t['what']}  "
                              f"[{','.join(str(i) for i in t['claim_ids'])}]")
                if oq:
                    print("\n  开放问题：")
                    for q in oq:
                        print(f"    - {q}")

        elif args.cmd == "channels":
            from .channels import list_channels, sync_channels
            if args.action == "sync":
                st = sync_channels(conn, Path(args.file))
                print(f"channels={st['channels']} new={st['new']}")
            else:
                for c in list_channels(conn):
                    print(f"{c['key']:20s} {c['name']:10s} {json.dumps(c['query'], ensure_ascii=False)}")

        elif args.cmd == "run-cycle":
            from .pipeline import default_stages, run_cycle
            r = run_cycle(conn, cfg, default_stages(cfg, model=args.model),
                          force=args.force, only=args.stage)
            if r.get("skipped"):
                print(f"cycle skipped: {r['skipped']}")
                return 1
            print(f"cycle {r['cycle']}")
            for name, s in r["stages"].items():
                print(f"  {name:18s} {s}")

        elif args.cmd == "serve":
            try:
                from .service import serve
            except ImportError as exc:      # fastapi/uvicorn 是可选依赖
                print(f"serve 需要额外依赖：pip install -e '.[serve]'（{exc}）")
                return 1
            print(f"serving on http://{args.host}:{args.port}"
                  f"{'（调度器关闭）' if args.no_scheduler else ''}")
            serve(host=args.host, port=args.port,
                  scheduler=not args.no_scheduler, model=args.model)

        elif args.cmd == "snapshot":
            from pathlib import Path as _P

            from .snapshot import write_snapshot
            path = write_snapshot(conn, _P(args.out))
            print(f"snapshot written: {path}")

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
