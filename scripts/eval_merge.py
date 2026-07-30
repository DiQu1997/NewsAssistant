#!/usr/bin/env python3
"""归并评估集标注与评分工具（docs/status.md §5 "评估集标注工具"）。

最简可用：CSV + 脚本，不做 web 界面。

    eval_merge.py export --out eval.csv [--limit 200] [--since 2026-07-01]
    # ... 人工在 eval.csv 里填 label_story_id / label_note ...
    eval_merge.py score eval.csv

只读访问 documents / stories / claims / story_documents（以及 merge.recall()
用到的 document_entities / entities / story_entities）。全程无 LLM。

评分口径见 docs/evaluation.md；标注规范必须与 newsassistant/merge.py 的
JUDGE_PROMPT 判断标准一致，否则评估集测的是另一套标准，失去意义。
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict

import psycopg

from newsassistant import db
from newsassistant.config import load
from newsassistant.merge import recall

CSV_FIELDS = [
    "doc_id", "published_date", "source_key", "title",
    "claim_1", "claim_2", "claim_3",
    "current_story_id", "current_story_title",
    "cand1_id", "cand1_title", "cand2_id", "cand2_title", "cand3_id", "cand3_title",
    "label_story_id", "label_note",
]


# ── export ───────────────────────────────────────────────────

def build_export_rows(conn: psycopg.Connection, limit: int = 200,
                       since: str | None = None, source: str | None = None) -> list[dict]:
    """挑已抽取文档，附系统当前归属 + 召回 top-3 候选，label 列留空待人工填。"""
    clauses = ["d.status='ok'", "d.extracted_at IS NOT NULL"]
    params: list = []
    if since:
        clauses.append("d.published_at >= %s")
        params.append(since)
    if source:
        clauses.append("s.key = %s")
        params.append(source)
    where = " AND ".join(clauses)

    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT d.id, d.published_at::date, s.key, d.title
            FROM documents d JOIN sources s ON s.id = d.source_id
            WHERE {where}
            ORDER BY d.published_at DESC NULLS LAST, d.id DESC
            LIMIT %s""", (*params, limit))
        docs = cur.fetchall()

    rows = []
    with conn.cursor() as cur:
        for doc_id, pub_date, source_key, title in docs:
            cur.execute("SELECT text FROM claims WHERE document_id=%s ORDER BY id LIMIT 3",
                        (doc_id,))
            claims = [r[0] for r in cur.fetchall()]
            claims += [""] * (3 - len(claims))

            cur.execute("""SELECT s2.id, s2.title FROM story_documents sd
                           JOIN stories s2 ON s2.id = sd.story_id
                           WHERE sd.document_id=%s LIMIT 1""", (doc_id,))
            r = cur.fetchone()
            cur_story_id, cur_story_title = (r[0], r[1]) if r else ("", "")

            cand_cells: list = []
            for c in recall(conn, doc_id, k=3):
                cand_cells += [c.id, c.title]
            cand_cells += [""] * (6 - len(cand_cells))

            rows.append({
                "doc_id": doc_id,
                "published_date": pub_date.isoformat() if pub_date else "",
                "source_key": source_key,
                "title": title or "",
                "claim_1": claims[0], "claim_2": claims[1], "claim_3": claims[2],
                "current_story_id": cur_story_id, "current_story_title": cur_story_title,
                "cand1_id": cand_cells[0], "cand1_title": cand_cells[1],
                "cand2_id": cand_cells[2], "cand2_title": cand_cells[3],
                "cand3_id": cand_cells[4], "cand3_title": cand_cells[5],
                "label_story_id": "", "label_note": "",
            })
    return rows


def cmd_export(args: argparse.Namespace) -> None:
    cfg = load()
    conn = db.connect(cfg.database_url)
    try:
        rows = build_export_rows(conn, limit=args.limit, since=args.since, source=args.source)
    finally:
        conn.close()
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"exported {len(rows)} rows -> {args.out}")
    print("下一步：人工填 label_story_id（已有故事 id / new / same:<doc_id>）"
          "与 label_note，然后 eval_merge.py score 该文件。")


# ── score（纯函数，见 tests/test_eval_merge.py） ─────────────

class _UnionFind:
    """通用并查集：节点可以是 doc_id（int）或标签内部键（如 ("story", 5)）。"""

    def __init__(self) -> None:
        self._parent: dict = {}

    def add(self, x) -> None:
        self._parent.setdefault(x, x)

    def find(self, x):
        self.add(x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a, b) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def _parse_label(raw: str):
    """label_story_id 原始字符串 → ('existing', story_id) | ('new', None)
    | ('same', ref_doc_id) | None（未标注或非法，调用方区分靠 raw 是否为空）。"""
    s = (raw or "").strip()
    if not s:
        return None
    if s.lower() == "new":
        return ("new", None)
    if s.lower().startswith("same:"):
        ref = s.split(":", 1)[1].strip()
        try:
            return ("same", int(ref))
        except ValueError:
            return None
    try:
        return ("existing", int(s))
    except ValueError:
        return None


def score_rows(rows: list[dict]) -> dict:
    """纯函数：人工标注 + 系统实际归属 → 归并质量统计。不碰数据库/网络。

    row 需要的字段：
        doc_id            int，唯一
        source_key        str，可为空（分桶用）
        published_date    str（YYYY-MM-DD），可为空（分桶用）
        label_story_id    str，人工标注原始值："" | "<story_id>" | "new" | "same:<doc_id>"
        actual_story_id   int | None，系统当前把该文档归进了哪个 story（未归并为 None）

    语义：
        label = 数字      → 人工认为该文档应归入这个 story_id
        label = "new"     → 人工认为该文档应独立成新故事（不与本次标注中任何其它文档同故事，
                             除非有其它行用 same: 指回它）
        label = "same:X"  → 人工认为该文档应与文档 X 同故事（用于两篇都还没被系统归并的情况）

    先用人工标注做并查集得到"应该同故事"的分组（ground truth clusters），
    再枚举所有标注文档两两配对，与系统实际分组（按 actual_story_id 分组，
    None 视为各自独立）比较：
        错并（false merge）：人工认为该分（不同组），系统合到了同一 story
        漏并（missed merge）：人工认为该合（同组），系统分到了不同 story（或还没归并）
    准确率 = 零冲突文档数 / 已标注文档数（该文档参与的所有配对都与人工一致）。
    """
    uf = _UnionFind()
    labeled: list[tuple[dict, tuple]] = []
    skipped_unlabeled = 0
    invalid_labels: list = []

    for r in rows:
        raw = r.get("label_story_id", "")
        parsed = _parse_label(raw)
        if parsed is None:
            if (raw or "").strip():
                invalid_labels.append(r["doc_id"])
            else:
                skipped_unlabeled += 1
            continue
        labeled.append((r, parsed))
        uf.add(r["doc_id"])

    for r, (kind, val) in labeled:
        if kind == "existing":
            key = ("story", val)
            uf.add(key)
            uf.union(r["doc_id"], key)
        elif kind == "same":
            uf.add(val)
            uf.union(r["doc_id"], val)
        # kind == "new"：不 union，独立一组（除非被别的行 same: 回指）

    n = len(labeled)
    false_merges = 0
    missed_merges = 0
    total_pairs = 0
    doc_ok = {r["doc_id"]: True for r, _ in labeled}

    for i in range(n):
        ri, _ = labeled[i]
        for j in range(i + 1, n):
            rj, _ = labeled[j]
            total_pairs += 1
            same_truth = uf.find(ri["doc_id"]) == uf.find(rj["doc_id"])
            ai, aj = ri.get("actual_story_id"), rj.get("actual_story_id")
            same_system = ai is not None and aj is not None and ai == aj
            if same_truth and not same_system:
                missed_merges += 1
                doc_ok[ri["doc_id"]] = False
                doc_ok[rj["doc_id"]] = False
            elif not same_truth and same_system:
                false_merges += 1
                doc_ok[ri["doc_id"]] = False
                doc_ok[rj["doc_id"]] = False

    correct_docs = sum(1 for ok in doc_ok.values() if ok)
    accuracy = (correct_docs / n) if n else None

    def _bucket(key_fn) -> dict:
        agg: dict = defaultdict(lambda: {"n": 0, "correct": 0})
        for r, _ in labeled:
            b = agg[key_fn(r) or "(unknown)"]
            b["n"] += 1
            b["correct"] += 1 if doc_ok[r["doc_id"]] else 0
        return {k: {"n": v["n"], "accuracy": (v["correct"] / v["n"]) if v["n"] else None}
                for k, v in agg.items()}

    return {
        "labeled": n,
        "unlabeled_skipped": skipped_unlabeled,
        "invalid_labels": invalid_labels,
        "accuracy": accuracy,
        "correct_docs": correct_docs,
        "total_pairs": total_pairs,
        "false_merges": false_merges,
        "missed_merges": missed_merges,
        "by_source": _bucket(lambda r: r.get("source_key")),
        "by_date": _bucket(lambda r: r.get("published_date")),
    }


def fetch_actual_story_ids(conn: psycopg.Connection, doc_ids: list[int]) -> dict[int, int]:
    if not doc_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute("SELECT document_id, story_id FROM story_documents WHERE document_id = ANY(%s)",
                    (doc_ids,))
        return {r[0]: r[1] for r in cur.fetchall()}


def print_report(result: dict) -> None:
    acc = result["accuracy"]
    print(f"labeled documents: {result['labeled']} "
          f"(unlabeled skipped: {result['unlabeled_skipped']}, "
          f"invalid labels: {len(result['invalid_labels'])})")
    print(f"accuracy:        {acc*100:.1f}%" if acc is not None else "accuracy:        n/a")
    print(f"pairs compared:  {result['total_pairs']}")
    print(f"false merges (错并, 系统合了人说该分的): {result['false_merges']}")
    print(f"missed merges (漏并, 系统分了人说该合的): {result['missed_merges']}")
    if result["invalid_labels"]:
        print(f"invalid label rows (doc_id): {result['invalid_labels']}")

    print("\nby source:")
    for k, v in sorted(result["by_source"].items()):
        a = f"{v['accuracy']*100:5.1f}%" if v["accuracy"] is not None else "  n/a"
        print(f"  {k:26s} n={v['n']:4d} acc={a}")

    print("\nby date:")
    for k, v in sorted(result["by_date"].items()):
        a = f"{v['accuracy']*100:5.1f}%" if v["accuracy"] is not None else "  n/a"
        print(f"  {k:12s} n={v['n']:4d} acc={a}")


def cmd_score(args: argparse.Namespace) -> None:
    with open(args.csv, newline="", encoding="utf-8") as f:
        csv_rows = list(csv.DictReader(f))
    doc_ids = [int(r["doc_id"]) for r in csv_rows if r.get("doc_id")]

    cfg = load()
    conn = db.connect(cfg.database_url)
    try:
        actual = fetch_actual_story_ids(conn, doc_ids)
    finally:
        conn.close()

    rows = [{
        "doc_id": int(r["doc_id"]),
        "source_key": r.get("source_key", ""),
        "published_date": r.get("published_date", ""),
        "label_story_id": r.get("label_story_id", ""),
        "actual_story_id": actual.get(int(r["doc_id"])),
    } for r in csv_rows if r.get("doc_id")]

    result = score_rows(rows)
    print_report(result)
    if args.json:
        import json
        print("\n" + json.dumps(result, ensure_ascii=False, indent=2, default=str))


# ── CLI ──────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="eval_merge.py", description="归并评估集：标注 CSV 导出与评分")
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("export", help="导出待标注 CSV")
    pe.add_argument("--out", default="eval_merge.csv", help="输出 CSV 路径")
    pe.add_argument("--limit", type=int, default=200,
                     help="导出文档数（默认 200，评估集目标样本量，见 docs/evaluation.md）")
    pe.add_argument("--since", help="只导出 published_at >= 此日期 (YYYY-MM-DD)")
    pe.add_argument("--source", help="只导出指定来源 key 的文档")

    ps = sub.add_parser("score", help="评分：回填好的 CSV vs 系统实际归并结果")
    ps.add_argument("csv", help="回填好的 CSV 路径")
    ps.add_argument("--json", action="store_true", help="额外打印完整 JSON 统计")

    args = p.parse_args(argv)
    if args.cmd == "export":
        cmd_export(args)
    elif args.cmd == "score":
        cmd_score(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
