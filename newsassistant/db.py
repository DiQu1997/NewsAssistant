"""数据库连接与迁移。psycopg3 直连 + 纯 SQL，不上 ORM。"""
from __future__ import annotations

import logging
from importlib import resources

import psycopg

log = logging.getLogger(__name__)


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, autocommit=False)


def migrate(conn: psycopg.Connection) -> list[str]:
    """按文件名顺序执行未应用的迁移，返回本次应用的列表。"""
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())""")
        cur.execute("SELECT name FROM schema_migrations")
        done = {r[0] for r in cur.fetchall()}

    applied = []
    root = resources.files("newsassistant").joinpath("migrations")
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        if not entry.name.endswith(".sql") or entry.name in done:
            continue
        sql = entry.read_text(encoding="utf-8")
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (entry.name,))
        conn.commit()
        log.info("migration applied: %s", entry.name)
        applied.append(entry.name)
    return applied
