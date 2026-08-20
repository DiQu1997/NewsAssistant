"""合成层测试 —— FakeSynthesizer，重点测引用强制（最高原则 5）与过期判定。"""
from __future__ import annotations

import asyncio

import psycopg
import pytest

from newsassistant import db
from newsassistant.synth import (COOLDOWN_HOURS, StoryView, Synthesis,
                                 run_synthesis)

TEST_DB = "postgresql://postgres:postgres@127.0.0.1:5432/newsassistant_test"


@pytest.fixture()
def conn():
    try:
        c = db.connect(TEST_DB)
    except psycopg.OperationalError:
        pytest.skip("no local postgres")
    db.migrate(c)
    with c.cursor() as cur:
        cur.execute("TRUNCATE llm_calls, document_entities, fetch_log, stories, "
                    "story_documents, story_entities, story_events, claims, documents, "
                    "entities, sources RESTART IDENTITY CASCADE")
    c.commit()
    yield c
    c.close()


def _seed_story(conn, n_docs=2) -> tuple[int, list[int]]:
    """一个故事、n 篇文档、每篇一条 claim。返回 (story_id, claim_ids)。"""
    claim_ids = []
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO sources (key,name,kind,url,evidence_tier)
                       VALUES ('s','S','rss','http://x',5) RETURNING id""")
        sid = cur.fetchone()[0]
        cur.execute("INSERT INTO stories (title) VALUES ('Quake in region X') RETURNING id")
        st = cur.fetchone()[0]
        for i in range(n_docs):
            cur.execute("""INSERT INTO documents (source_id,url,url_canonical,title,
                           status,extracted_at,published_at)
                           VALUES (%s,%s,%s,%s,'ok',now(), now() - interval '1 hour' * %s)
                           RETURNING id""",
                        (sid, f"http://x/{i}", f"http://x/{i}", f"doc {i}", n_docs - i))
            did = cur.fetchone()[0]
            cur.execute("""INSERT INTO claims (document_id,story_id,text,stance,confidence)
                           VALUES (%s,%s,%s,0,0.9) RETURNING id""",
                        (did, st, f"claim text {i}"))
            claim_ids.append(cur.fetchone()[0])
            cur.execute("INSERT INTO story_documents VALUES (%s,%s)", (st, did))
    conn.commit()
    return st, claim_ids


class FakeSynthesizer:
    """返回预设产物；记录喂进来的 StoryView 供断言。"""

    def __init__(self, make):
        self.make = make
        self.seen: list[StoryView] = []

    async def synthesize(self, story: StoryView) -> Synthesis:
        self.seen.append(story)
        return self.make(story)


def test_citation_enforcement_and_staleness(conn):
    st, cids = _seed_story(conn)

    def make(story):
        return Synthesis(summary=[
            {"text": "Good sentence.", "claim_ids": [cids[0], cids[1]]},
            {"text": "Uncited sentence.", "claim_ids": []},              # 丢
            {"text": "Foreign citation.", "claim_ids": [999999]},        # 丢
        ], timeline=[
            {"when": "2026-07-27", "what": "Toll rose", "claim_ids": [cids[1]]},
            {"when": "?", "what": "No citation", "claim_ids": []},       # 丢
        ], open_questions=["Who pays?"], model="fake-1")

    # 这个用例测引用强制与过期判定，冷却关掉（冷却本身见
    # test_resynthesis_cooldown），否则重合成永远被冷却挡住，测不到过期语义
    stats = asyncio.run(run_synthesis(conn, FakeSynthesizer(make), limit=10,
                                      cooldown_hours=0))
    assert stats == {"stories": 1, "sentences": 1, "facts": 0, "views": 0,
                     "dropped": 3, "errors": 0}

    with conn.cursor() as cur:
        cur.execute("""SELECT summary, timeline, open_questions FROM stories
                       WHERE id=%s""", (st,))
        summary, timeline, oq = cur.fetchone()
        assert [s["text"] for s in summary] == ["Good sentence."]
        assert summary[0]["claim_ids"] == [cids[0], cids[1]]
        assert [t["what"] for t in timeline] == ["Toll rose"]
        assert oq == ["Who pays?"]
        cur.execute("SELECT kind FROM story_events WHERE story_id=%s ORDER BY id", (st,))
        assert ("synthesized",) in cur.fetchall()
        cur.execute("SELECT count(*) FROM llm_calls WHERE purpose='synthesize'")
        assert cur.fetchone()[0] == 1

    # 过期判定：合成后未更新 → 不再选中
    fake2 = FakeSynthesizer(make)
    stats2 = asyncio.run(run_synthesis(conn, fake2, limit=10, cooldown_hours=0))
    assert stats2["stories"] == 0 and not fake2.seen

    # 故事又有更新 → 重新过期，且上一版综述喂给模型
    with conn.cursor() as cur:
        cur.execute("UPDATE stories SET updated_at=now() WHERE id=%s", (st,))
    conn.commit()
    fake3 = FakeSynthesizer(make)
    asyncio.run(run_synthesis(conn, fake3, limit=10, cooldown_hours=0))
    assert fake3.seen and fake3.seen[0].prev_summary is not None
    assert fake3.seen[0].prev_summary[0]["text"] == "Good sentence."


def test_all_dropped_keeps_previous_summary(conn):
    st, cids = _seed_story(conn)
    good = FakeSynthesizer(lambda s: Synthesis(
        summary=[{"text": "V1.", "claim_ids": [cids[0]]}], model="fake-1"))
    asyncio.run(run_synthesis(conn, good, limit=10))

    with conn.cursor() as cur:
        cur.execute("UPDATE stories SET updated_at=now() WHERE id=%s", (st,))
    conn.commit()
    bad = FakeSynthesizer(lambda s: Synthesis(
        summary=[{"text": "All invalid.", "claim_ids": [42424242]}], model="fake-1"))
    stats = asyncio.run(run_synthesis(conn, bad, limit=10, cooldown_hours=0))
    assert stats["errors"] == 1 and stats["stories"] == 0

    with conn.cursor() as cur:
        cur.execute("SELECT summary FROM stories WHERE id=%s", (st,))
        assert cur.fetchone()[0][0]["text"] == "V1."   # 旧版未被覆盖


def test_resynthesis_cooldown(conn):
    """重合成冷却：热故事吸新文档就重写，一天能烧掉 synthesize 八成预算。
    冷却窗内的更新一律不重合成，窗外才放行；首次合成不受影响。"""
    st, cids = _seed_story(conn)
    v1 = FakeSynthesizer(lambda s: Synthesis(
        summary=[{"text": "V1.", "claim_ids": [cids[0]]}], model="fake-1"))
    assert asyncio.run(run_synthesis(conn, v1, limit=10))["stories"] == 1

    # 刚合成完就又吸了篇文档 → 过期但在冷却窗内，不重合成
    with conn.cursor() as cur:
        cur.execute("UPDATE stories SET updated_at=now() WHERE id=%s", (st,))
    conn.commit()
    hot = FakeSynthesizer(lambda s: Synthesis(
        summary=[{"text": "V2.", "claim_ids": [cids[0]]}], model="fake-1"))
    assert asyncio.run(run_synthesis(conn, hot, limit=10))["stories"] == 0
    assert not hot.seen

    # 把上次合成推到冷却窗外 → 同样的过期状态，这次放行
    with conn.cursor() as cur:
        cur.execute("""UPDATE stories
                       SET synthesized_at = now() - make_interval(hours => %s),
                           updated_at = now()
                       WHERE id=%s""", (COOLDOWN_HOURS + 1, st))
    conn.commit()
    cool = FakeSynthesizer(lambda s: Synthesis(
        summary=[{"text": "V2.", "claim_ids": [cids[0]]}], model="fake-1"))
    assert asyncio.run(run_synthesis(conn, cool, limit=10))["stories"] == 1

    with conn.cursor() as cur:
        cur.execute("SELECT summary FROM stories WHERE id=%s", (st,))
        assert cur.fetchone()[0][0]["text"] == "V2."


def test_single_doc_story_skipped(conn):
    _seed_story(conn, n_docs=1)
    fake = FakeSynthesizer(lambda s: Synthesis(model="fake-1"))
    stats = asyncio.run(run_synthesis(conn, fake, limit=10))
    assert stats["stories"] == 0 and not fake.seen


def test_error_result_audited_not_applied(conn):
    st, _ = _seed_story(conn)
    fake = FakeSynthesizer(lambda s: Synthesis(error="quota", model="fake-1"))
    stats = asyncio.run(run_synthesis(conn, fake, limit=10))
    assert stats["errors"] == 1

    with conn.cursor() as cur:
        cur.execute("SELECT summary, synthesized_at FROM stories WHERE id=%s", (st,))
        summary, syn_at = cur.fetchone()
        assert summary is None and syn_at is None      # 失败不落产物
        cur.execute("""SELECT output->>'error' FROM llm_calls
                       WHERE purpose='synthesize'""")
        assert cur.fetchone()[0] == "quota"            # 但审计必须在


# ── 事实槽位与图元的校验门槛 ─────────────────────────────────
# 这一层是"规则层"：模型判断数据够不够并不可靠（实测渲染成功但语义
# 错误的比例是渲染失败的六倍），所以门槛必须在代码里可测。

from newsassistant.synth import _enforce_facts, _enforce_views  # noqa: E402

VALID = {1, 2, 3}


def _fact(**kw):
    base = {"key": "death_toll", "label": "死亡人数", "kind": "single",
            "value": 12, "claim_ids": [1]}
    return {**base, **kw}


def test_facts_require_valid_citations():
    kept, dropped = _enforce_facts([_fact(claim_ids=[99])], VALID)
    assert kept == [] and dropped == 1
    kept, _ = _enforce_facts([_fact()], VALID)
    assert kept[0]["key"] == "death_toll"


def test_single_fact_without_value_is_dropped():
    kept, dropped = _enforce_facts([_fact(value=None)], VALID)
    assert kept == [] and dropped == 1


def test_disputed_needs_two_named_estimates():
    one = _fact(kind="disputed", value=None,
                estimates=[{"value": 100, "source": "官方"}])
    assert _enforce_facts([one], VALID) == ([], 1)
    two = _fact(kind="disputed", value=None, gap_label="高于官方通报的部分",
                estimates=[{"value": 100, "source": "官方"},
                           {"value": 180, "source": "世卫", "method": "超额死亡模型"}])
    kept, _ = _enforce_facts([two], VALID)
    assert len(kept[0]["estimates"]) == 2
    assert kept[0]["gap_label"] == "高于官方通报的部分"


def test_unknown_fact_survives_without_value():
    kept, _ = _enforce_facts([_fact(kind="unknown", value=None)], VALID)
    assert kept[0]["kind"] == "unknown"


def test_duplicate_fact_keys_dropped():
    kept, dropped = _enforce_facts([_fact(), _fact(label="重复")], VALID)
    assert len(kept) == 1 and dropped == 1


def _view(**kw):
    base = {"type": "bars", "intent": "排名", "title": "关税集中在三个行业",
            "unit": "%", "claim_ids": [1],
            "items": [{"label": "钢", "value": 25}, {"label": "铝", "value": 10}]}
    return {**base, **kw}


def test_view_requires_title_unit_and_citations():
    for bad in (_view(title=""), _view(unit=""), _view(claim_ids=[]),
                _view(claim_ids=[99]), _view(intent="")):
        assert _enforce_views([bad], VALID, set()) == ([], 1)
    kept, _ = _enforce_views([_view()], VALID, set())
    assert kept[0]["type"] == "bars"


def test_unknown_view_type_dropped():
    assert _enforce_views([_view(type="sankey")], VALID, set()) == ([], 1)


def test_line_needs_three_points():
    two = _view(type="line_baseline", items=None,
                points=[{"x": "1日", "y": 1}, {"x": "2日", "y": 2}])
    assert _enforce_views([two], VALID, set()) == ([], 1)
    three = _view(type="line_baseline", items=None,
                  points=[{"x": f"{i}日", "y": i} for i in range(3)])
    assert len(_enforce_views([three], VALID, set())[0]) == 1


def test_slope_needs_exactly_two_timepoints_and_three_subjects():
    ok = _view(type="slope", x_labels=["加税前", "加税后"],
               items=[{"label": c, "value": 1, "value2": 2} for c in "abc"])
    assert len(_enforce_views([ok], VALID, set())[0]) == 1
    assert _enforce_views([{**ok, "x_labels": ["前", "中", "后"]}],
                          VALID, set()) == ([], 1)
    assert _enforce_views([{**ok, "items": ok["items"][:2]}],
                          VALID, set()) == ([], 1)


def test_swimlane_needs_two_actors():
    one = _view(type="swimlane", unit="次", items=None, lanes=[
        {"actor": "甲", "events": [{"start": "1日", "label": "提案"},
                                   {"start": "2日", "label": "回应"},
                                   {"start": "3日", "label": "签署"}]}])
    assert _enforce_views([one], VALID, set()) == ([], 1)
    two = {**one, "lanes": one["lanes"] + [
        {"actor": "乙", "events": [{"start": "2日", "label": "反对"}]}]}
    assert len(_enforce_views([two], VALID, set())[0]) == 1


def test_beeswarm_needs_twenty_points():
    few = _view(type="beeswarm", items=[{"label": str(i), "value": i}
                                        for i in range(19)])
    assert _enforce_views([few], VALID, set()) == ([], 1)
    many = _view(type="beeswarm", items=[{"label": str(i), "value": i}
                                         for i in range(20)])
    assert len(_enforce_views([many], VALID, set())[0]) == 1


def test_waffle_caps_total_units():
    big = _view(type="waffle", items=[{"label": "遇难", "value": 401}])
    assert _enforce_views([big], VALID, set()) == ([], 1)
    ok = _view(type="waffle", items=[{"label": "遇难", "value": 43}])
    assert len(_enforce_views([ok], VALID, set())[0]) == 1


def test_numbers_view_keeps_only_existing_fact_keys():
    v = _view(type="numbers", unit="人", items=None,
              fact_keys=["death_toll", "ghost_key"])
    kept, _ = _enforce_views([v], VALID, {"death_toll"})
    assert kept[0]["fact_keys"] == ["death_toll"]
    assert _enforce_views([{**v, "fact_keys": ["ghost_key"]}],
                          VALID, {"death_toll"}) == ([], 1)


def test_annotations_without_text_are_stripped():
    v = _view(annotations=[{"at": "钢", "text": "最高档"}, {"at": "铝"}])
    kept, _ = _enforce_views([v], VALID, set())
    assert kept[0]["annotations"] == [{"at": "钢", "text": "最高档"}]
