"""抽取 orchestrator 测试 —— FakeExtractor，不碰网络/SDK/订阅。

验证：选待处理文档 → claims/entities/document_entities 落库 →
llm_calls 审计（含失败调用）→ 幂等（extracted_at 置位后不再选中）→
实体跨文档去重（同名同类只一条）。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import psycopg
import pytest

from newsassistant import db
from newsassistant.config import Config
from newsassistant.contentstore import ContentStore
from newsassistant.llm_extract import ExtractionResult, run_extraction

TEST_DB = "postgresql://postgres:postgres@127.0.0.1:5432/newsassistant_test"


class FakeExtractor:
    """批量协议的替身：第 fail_on 篇（全局计数）返回 error，其余成功。"""

    def __init__(self, fail_on: set[int] | None = None):
        self.calls = 0
        self.fail_on = fail_on or set()

    async def extract_batch(self, docs):
        out = []
        for text, title in docs:
            self.calls += 1
            if self.calls in self.fail_on:
                out.append(ExtractionResult(model="fake-1", error="boom"))
                continue
            out.append(ExtractionResult(
                claims=[{"text": f"claim about {title}", "who": "Agency",
                         "did": "proposed", "stance": 0, "confidence": 0.9}],
                entities=[{"name": "Test Agency", "kind": "org"},
                          {"name": "Jane Reporter", "kind": "person"}],
                lang="en", is_opinion=False, model="fake-1",
                tokens_in=100, tokens_out=50))
        return out


@pytest.fixture()
def conn():
    try:
        c = db.connect(TEST_DB)
    except psycopg.OperationalError:
        pytest.skip("no local postgres")
    db.migrate(c)
    with c.cursor() as cur:
        cur.execute("TRUNCATE llm_calls, document_entities, fetch_log, "
                    "story_documents, story_events, claims, documents, entities, "
                    "sources RESTART IDENTITY CASCADE")
    c.commit()
    yield c
    c.close()


def _seed_docs(conn, store: ContentStore, n: int) -> None:
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO sources (key,name,kind,url,evidence_tier)
                       VALUES ('t','T','rss','http://x/feed',5) RETURNING id""")
        sid = cur.fetchone()[0]
        for i in range(n):
            _, ref = store.put(f"Body of article {i}. " * 30)
            cur.execute("""INSERT INTO documents (source_id,url,url_canonical,title,
                           content_ref,status) VALUES (%s,%s,%s,%s,%s,'ok')""",
                        (sid, f"http://x/a{i}", f"http://x/a{i}", f"Article {i}", ref))
    conn.commit()


def test_extraction_orchestration(conn, tmp_path: Path):
    cfg = Config(database_url=TEST_DB, data_dir=tmp_path)
    _seed_docs(conn, ContentStore(tmp_path), 3)
    ex = FakeExtractor(fail_on={2})       # 第二篇失败

    st = asyncio.run(run_extraction(conn, cfg, ex, limit=10))
    assert st == {"docs": 2, "claims": 2, "entities": 4, "errors": 1}

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM claims")
        assert cur.fetchone()[0] == 2
        # 实体跨文档去重：两篇成功文档提交同样两个实体 → 只有 2 条
        cur.execute("SELECT count(*) FROM entities")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT count(*) FROM document_entities")
        assert cur.fetchone()[0] == 4
        # 审计：3 次调用全落库，失败的那次带 error
        cur.execute("SELECT count(*) FROM llm_calls WHERE purpose='extract'")
        assert cur.fetchone()[0] == 3
        cur.execute("SELECT count(*) FROM llm_calls WHERE output->>'error' IS NOT NULL")
        assert cur.fetchone()[0] == 1
        # 失败文档未置 extracted_at → 重跑会重试它
        cur.execute("SELECT count(*) FROM documents WHERE extracted_at IS NULL")
        assert cur.fetchone()[0] == 1

    # 幂等 + 失败重试：再跑一轮只处理失败的那篇
    st2 = asyncio.run(run_extraction(conn, cfg, FakeExtractor(), limit=10))
    assert st2["docs"] == 1
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM documents WHERE extracted_at IS NULL")
        assert cur.fetchone()[0] == 0
