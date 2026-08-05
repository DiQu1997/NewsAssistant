"""离线评测：assign 换模型的一致率与准确率估计。

只读 DB + LLM 调用，不写任何表。原理：llm_calls 存了每次裁决的
document_id + 候选故事 id + sonnet 的裁决；文档断言/实体和候选故事
视图都能按裁决时刻（at）从 DB 重建 —— 成员文档按 story_documents.added_at
< at 过滤，排除本文档自身（同事务写入 added_at == at，严格小于即天然排除），
避免"答案泄漏进题面"。

流程：
  1. 抽最近 N 条无错裁决（每 doc 取最新一条，existing/new 各半分层）
  2. 重建 BatchItem，按波重放到 --model（默认 haiku）
  3. 与 sonnet 原裁决对比一致率
  4. 分歧 case 交 --referee（默认 opus）盲裁：不看两方答案独立重判，
     看它站谁 —— 把"一致率"换算成"到底谁错"

用法（在 OCI 上）：
  .venv/bin/python scripts/eval_assign_model.py --sample 100
  .venv/bin/python scripts/eval_assign_model.py --sample 40 --skip-referee
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from newsassistant.config import load                # noqa: E402
from newsassistant.merge import (BatchItem, CandidateView, ClaudeJudge,   # noqa: E402
                                 DocView, Verdict)

REPLAY_BATCH = 5


# ── 样本抽取 ────────────────────────────────────────────────

def sample_decisions(conn: psycopg.Connection, n: int) -> list[dict]:
    """最近的无错裁决，每 doc 只取最新一条，existing/new 各半分层。"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON ((input->>'document_id')::bigint)
                   id, at, (input->>'document_id')::bigint,
                   input->'candidates',
                   output->>'decision', (output->>'story_id')::bigint,
                   output->>'reason', model
            FROM llm_calls
            WHERE purpose='assign' AND output->>'error' IS NULL
              AND jsonb_array_length(input->'candidates') > 0
            ORDER BY (input->>'document_id')::bigint, id DESC""")
        rows = [{"call_id": r[0], "at": r[1], "doc_id": r[2],
                 "cand_ids": r[3], "decision": r[4], "story_id": r[5],
                 "reason": r[6], "model": r[7]} for r in cur.fetchall()]
    rows.sort(key=lambda r: r["call_id"], reverse=True)
    ex = [r for r in rows if r["decision"] == "existing"][: n // 2]
    nw = [r for r in rows if r["decision"] == "new"][: n - len(ex)]
    # existing 不足 n/2 时用 new 补满，反之亦然
    if len(ex) < n // 2:
        nw = [r for r in rows if r["decision"] == "new"][: n - len(ex)]
    return sorted(ex + nw, key=lambda r: r["call_id"])


# ── 裁决时刻的输入重建 ──────────────────────────────────────

def rebuild_doc(cur: psycopg.Cursor, doc_id: int) -> DocView:
    cur.execute("SELECT title, published_at::text FROM documents WHERE id=%s",
                (doc_id,))
    title, pub = cur.fetchone()
    d = DocView(id=doc_id, title=title, published_at=pub)
    cur.execute("SELECT text FROM claims WHERE document_id=%s ORDER BY id LIMIT 8",
                (doc_id,))
    d.claims = [r[0] for r in cur.fetchall()]
    cur.execute("""SELECT DISTINCT e2.canonical_name FROM document_entities de
                   JOIN entities e ON e.id=de.entity_id
                   JOIN entities e2 ON e2.id=coalesce(e.merged_into, e.id)
                   WHERE de.document_id=%s""", (doc_id,))
    d.entities = [r[0] for r in cur.fetchall()]
    return d


def rebuild_candidate(cur: psycopg.Cursor, story_id: int, doc_id: int,
                      cutoff) -> CandidateView | None:
    """按 cutoff 重建候选故事视图，排除评测文档自身的贡献。"""
    cur.execute("SELECT title FROM stories WHERE id=%s", (story_id,))
    row = cur.fetchone()
    if not row:
        return None
    c = CandidateView(id=story_id, title=row[0], doc_count=0)
    cur.execute("""SELECT sd.document_id FROM story_documents sd
                   WHERE sd.story_id=%s AND sd.added_at < %s
                     AND sd.document_id != %s
                   ORDER BY sd.added_at DESC""", (story_id, cutoff, doc_id))
    members = [r[0] for r in cur.fetchall()]
    if not members:
        return None          # 裁决时刻不可能是空故事；时间戳歪了就弃用该样本
    c.doc_count = len(members)
    cur.execute("SELECT title FROM documents WHERE id = ANY(%s)", (members[:3],))
    c.recent_titles = [r[0] for r in cur.fetchall() if r[0]]
    cur.execute("""SELECT text FROM claims WHERE document_id = ANY(%s)
                   ORDER BY id DESC LIMIT 5""", (members,))
    c.recent_claims = [r[0] for r in cur.fetchall()]
    cur.execute("""
        SELECT DISTINCT e2.canonical_name FROM document_entities de
        JOIN entities e ON e.id=de.entity_id
        JOIN entities e2 ON e2.id=coalesce(e.merged_into, e.id)
        WHERE de.document_id = ANY(%s)
        INTERSECT
        SELECT DISTINCT e2.canonical_name FROM document_entities de
        JOIN entities e ON e.id=de.entity_id
        JOIN entities e2 ON e2.id=coalesce(e.merged_into, e.id)
        WHERE de.document_id = %s""", (members, doc_id))
    c.shared_entities = [r[0] for r in cur.fetchall()]
    return c


def rebuild_items(conn: psycopg.Connection,
                  samples: list[dict]) -> list[tuple[dict, BatchItem]]:
    out = []
    with conn.cursor() as cur:
        for s in samples:
            cands = [rebuild_candidate(cur, cid, s["doc_id"], s["at"])
                     for cid in s["cand_ids"]]
            cands = [c for c in cands if c]
            if not cands:
                continue
            # sonnet 选的故事必须仍在重建后的候选里，否则对比无意义
            if s["decision"] == "existing" and s["story_id"] not in {c.id for c in cands}:
                continue
            out.append((s, (rebuild_doc(cur, s["doc_id"]), cands)))
    return out


# ── 重放与对比 ──────────────────────────────────────────────

async def replay(model: str, pairs: list[tuple[dict, BatchItem]],
                 tag: str, lean: bool = False) -> list[Verdict]:
    judge = ClaudeJudge(model=model, lean=lean)
    verdicts: list[Verdict] = []
    usage_tot: dict = {"output_tokens": 0, "input_tokens": 0}
    for i in range(0, len(pairs), REPLAY_BATCH):
        wave = [p[1] for p in pairs[i:i + REPLAY_BATCH]]
        vs = await judge.judge_batch(wave)
        verdicts += vs
        u = vs[0].usage or {}
        for k in usage_tot:
            usage_tot[k] += u.get(k) or 0
        done = min(i + REPLAY_BATCH, len(pairs))
        print(f"  [{tag}] {done}/{len(pairs)}", flush=True)
    print(f"  [{tag}] usage: {usage_tot}", flush=True)
    return verdicts


def agree(s: dict, v: Verdict) -> bool:
    if v.decision != s["decision"]:
        return False
    return v.decision == "new" or v.story_id == s["story_id"]


def vkey(v) -> str:
    d = v.decision if isinstance(v, Verdict) else v["decision"]
    sid = v.story_id if isinstance(v, Verdict) else v["story_id"]
    return f"existing:{sid}" if d == "existing" else "new"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--referee", default="opus")
    ap.add_argument("--sample", type=int, default=100)
    ap.add_argument("--skip-referee", action="store_true")
    ap.add_argument("--lean", action="store_true",
                    help="重放模型用 lean 模式（禁 thinking + 禁正文）")
    ap.add_argument("--out", default="/tmp/eval_assign.jsonl")
    args = ap.parse_args()

    cfg = load()
    conn = psycopg.connect(cfg.database_url)
    samples = sample_decisions(conn, args.sample)
    pairs = rebuild_items(conn, samples)
    n_ex = sum(1 for s, _ in pairs if s["decision"] == "existing")
    print(f"样本 {len(pairs)} 篇（existing {n_ex} / new {len(pairs) - n_ex}），"
          f"重放模型 {args.model}", flush=True)

    verdicts = await replay(args.model, pairs, args.model, lean=args.lean)

    records, dis = [], []
    for (s, item), v in zip(pairs, verdicts):
        rec = {"doc_id": s["doc_id"], "title": item[0].title,
               "sonnet": vkey(s), "sonnet_reason": s["reason"],
               args.model: vkey(v), f"{args.model}_reason": v.reason,
               "error": v.error, "agree": agree(s, v)}
        records.append(rec)
        if not rec["agree"] and not v.error:
            dis.append((s, item, v, rec))

    ok = [r for r in records if not r["error"]]
    n_agree = sum(r["agree"] for r in ok)
    print(f"\n有效 {len(ok)} 篇，一致 {n_agree}（{n_agree / max(len(ok), 1):.0%}），"
          f"错误 {len(records) - len(ok)}")
    for a, b in [("existing", "new"), ("new", "existing")]:
        k = sum(1 for r in ok if r["sonnet"].startswith(a) and r[args.model].startswith(b))
        print(f"  sonnet={a} → {args.model}={b}: {k}")
    both_dif = sum(1 for r in ok if r["sonnet"].startswith("existing")
                   and r[args.model].startswith("existing") and not r["agree"])
    print(f"  都 existing 但故事不同: {both_dif}")

    if dis and not args.skip_referee:
        print(f"\n{len(dis)} 个分歧交 {args.referee} 盲裁（独立重判，不看两方答案）")
        ref = await replay(args.referee, [(s, item) for s, item, _, _ in dis],
                           args.referee)
        score = {"sonnet": 0, args.model: 0, "neither": 0}
        for (s, item, v, rec), rv in zip(dis, ref):
            rec["referee"] = vkey(rv)
            rec["referee_reason"] = rv.reason
            side = ("sonnet" if vkey(rv) == vkey(s)
                    else args.model if vkey(rv) == vkey(v) else "neither")
            rec["referee_sides_with"] = side
            score[side] += 1
        print(f"裁判站队: {score}")

    Path(args.out).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records))
    print(f"\n明细 → {args.out}")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=3600))
