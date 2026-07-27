"""归并评估打分逻辑测试 —— 只测纯函数 score_rows，不碰数据库。

scripts/ 不是 newsassistant 包的一部分（有意：评估工具与生产代码解耦），
所以直接按文件路径加载模块。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "eval_merge.py"
_spec = importlib.util.spec_from_file_location("eval_merge", SCRIPT)
eval_merge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_merge)  # type: ignore[union-attr]

score_rows = eval_merge.score_rows


def _row(doc_id, label, actual=None, source="s1", date="2026-07-01"):
    return {"doc_id": doc_id, "source_key": source, "published_date": date,
            "label_story_id": label, "actual_story_id": actual}


# ── 基本语义：existing / new ───────────────────────────────

def test_existing_label_matches_system_is_correct():
    rows = [_row(1, "10", actual=10), _row(2, "10", actual=10)]
    r = score_rows(rows)
    assert r["labeled"] == 2
    assert r["accuracy"] == 1.0
    assert r["false_merges"] == 0
    assert r["missed_merges"] == 0


def test_new_label_alone_is_correct_regardless_of_actual_story():
    # 两篇都标 new，各自新建了不同 story：符合"应各自独立"
    rows = [_row(1, "new", actual=101), _row(2, "new", actual=102)]
    r = score_rows(rows)
    assert r["accuracy"] == 1.0
    assert r["false_merges"] == 0
    assert r["missed_merges"] == 0


def test_new_label_but_system_merged_them_is_false_merge():
    # 两篇都标 new（应各自独立），系统却合并到同一个 story → 错并
    rows = [_row(1, "new", actual=99), _row(2, "new", actual=99)]
    r = score_rows(rows)
    assert r["false_merges"] == 1
    assert r["missed_merges"] == 0
    assert r["accuracy"] == 0.0


# ── same: 语义 ──────────────────────────────────────────────

def test_same_ref_correct_when_system_merged():
    rows = [_row(1, "same:2", actual=50), _row(2, "10", actual=50)]
    r = score_rows(rows)
    assert r["accuracy"] == 1.0
    assert r["false_merges"] == 0
    assert r["missed_merges"] == 0


def test_same_ref_is_missed_merge_when_system_has_not_merged():
    # 两篇都还没被系统归并（actual=None），人工说应同故事 → 漏并
    rows = [_row(1, "same:2", actual=None), _row(2, "new", actual=None)]
    r = score_rows(rows)
    assert r["missed_merges"] == 1
    assert r["false_merges"] == 0
    assert r["accuracy"] == 0.0


def test_same_ref_transitive_chain():
    # 1 same:2, 2 same:3 → 1/2/3 应同组；系统三篇归到同一 story 即全对
    rows = [_row(1, "same:2", actual=7), _row(2, "same:3", actual=7),
            _row(3, "new", actual=7)]
    r = score_rows(rows)
    assert r["accuracy"] == 1.0
    assert r["total_pairs"] == 3


# ── 混合场景：错并与漏并同时出现 ───────────────────────────

def test_mixed_false_and_missed_merge():
    rows = [
        _row(1, "10", actual=10),       # 与 2 同组(人工)，系统分开 → 漏并
        _row(2, "10", actual=20),
        _row(3, "new", actual=30),      # 与 4 应各自独立(人工)，系统合并 → 错并
        _row(4, "new", actual=30),
        _row(5, "50", actual=50),       # 独立且正确，作为对照
    ]
    r = score_rows(rows)
    assert r["missed_merges"] == 1
    assert r["false_merges"] == 1
    assert r["labeled"] == 5
    # 1/2/3/4 都卷入了冲突配对，只有 5 全对：accuracy = 1/5
    assert r["accuracy"] == 1 / 5


# ── 未标注 / 非法标注 ───────────────────────────────────────

def test_unlabeled_rows_are_skipped():
    rows = [_row(1, "10", actual=10), _row(2, "", actual=None)]
    r = score_rows(rows)
    assert r["labeled"] == 1
    assert r["unlabeled_skipped"] == 1


def test_invalid_label_is_reported_not_silently_dropped():
    rows = [_row(1, "not-a-valid-label", actual=10)]
    r = score_rows(rows)
    assert r["labeled"] == 0
    assert r["invalid_labels"] == [1]


def test_no_labeled_rows_gives_none_accuracy():
    r = score_rows([_row(1, "", actual=None)])
    assert r["labeled"] == 0
    assert r["accuracy"] is None
    assert r["total_pairs"] == 0


# ── 分桶 ─────────────────────────────────────────────────────

def test_buckets_by_source_and_date():
    rows = [
        _row(1, "10", actual=10, source="a", date="2026-07-01"),
        _row(2, "10", actual=20, source="a", date="2026-07-01"),  # 漏并，两篇都标坏
        _row(3, "5", actual=5, source="b", date="2026-07-02"),
    ]
    r = score_rows(rows)
    assert r["by_source"]["a"]["n"] == 2
    assert r["by_source"]["a"]["accuracy"] == 0.0
    assert r["by_source"]["b"]["n"] == 1
    assert r["by_source"]["b"]["accuracy"] == 1.0
    assert r["by_date"]["2026-07-01"]["n"] == 2
    assert r["by_date"]["2026-07-02"]["accuracy"] == 1.0
