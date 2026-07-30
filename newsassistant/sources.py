"""源注册表 —— YAML 种子文件 → sources 表。

每个源是一条有属性的记录（docs/sources.md），属性喂给下游可信度判断。
种子文件只是初始化；运行后 sources 表是唯一权威（etag 等拉取状态在表里）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import psycopg
import yaml

from .apisources import ADAPTERS
from .fetch import VIA_CHOICES

REQUIRED = ("key", "name", "kind", "url", "evidence_tier")


@dataclass
class SourceSpec:
    key: str
    name: str
    kind: str
    url: str
    evidence_tier: int
    cadence_minutes: int = 60
    revises: bool = False
    lang: str | None = None
    region: str | None = None
    legal: dict = field(default_factory=dict)
    notes: str | None = None
    enabled: bool = True
    fetch_article: bool = True   # False = feed 条目即全部载荷，不抓文章页
    adapter: str | None = None   # kind=api 时的响应解析器（apisources.ADAPTERS）
    fetch_via: str = "httpx"     # httpx | curl | auto（TLS 指纹拦截的退路）


def _validate(path_name: str, s: SourceSpec) -> None:
    """种子文件里的错字应当在 sync 时就炸，而不是等采集轮里静默失败。"""
    if s.fetch_via not in VIA_CHOICES:
        raise ValueError(f"{path_name}: source {s.key}: fetch_via={s.fetch_via!r} "
                         f"not in {VIA_CHOICES}")
    if s.kind == "api":
        if not s.adapter:
            raise ValueError(f"{path_name}: source {s.key}: kind=api requires 'adapter'")
        if s.adapter not in ADAPTERS:
            raise ValueError(f"{path_name}: source {s.key}: unknown adapter "
                             f"{s.adapter!r} (known: {sorted(ADAPTERS)})")


def load_specs(sources_dir: Path) -> list[SourceSpec]:
    specs: list[SourceSpec] = []
    for path in sorted(sources_dir.glob("*.yaml")):
        if path.name == "channels.yaml":
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        for row in data:
            missing = [k for k in REQUIRED if k not in row]
            if missing:
                raise ValueError(f"{path.name}: source missing {missing}: {row}")
            spec = SourceSpec(**row)
            _validate(path.name, spec)
            specs.append(spec)
    keys = [s.key for s in specs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate source keys in seed files")
    return specs


def sync_sources(conn: psycopg.Connection, specs: list[SourceSpec]) -> int:
    """按 key upsert；不覆盖运行时状态（etag / last_fetch_at）。"""
    n = 0
    with conn.cursor() as cur:
        for s in specs:
            cur.execute("""
                INSERT INTO sources (key, name, kind, url, evidence_tier,
                    cadence_minutes, revises, lang, region, legal, notes, enabled,
                    fetch_article, adapter, fetch_via)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (key) DO UPDATE SET
                    name=EXCLUDED.name, kind=EXCLUDED.kind, url=EXCLUDED.url,
                    evidence_tier=EXCLUDED.evidence_tier,
                    cadence_minutes=EXCLUDED.cadence_minutes,
                    revises=EXCLUDED.revises, lang=EXCLUDED.lang,
                    region=EXCLUDED.region, legal=EXCLUDED.legal,
                    notes=EXCLUDED.notes, enabled=EXCLUDED.enabled,
                    fetch_article=EXCLUDED.fetch_article,
                    adapter=EXCLUDED.adapter, fetch_via=EXCLUDED.fetch_via
                """, (s.key, s.name, s.kind, s.url, s.evidence_tier,
                      s.cadence_minutes, s.revises, s.lang, s.region,
                      psycopg.types.json.Json(s.legal), s.notes, s.enabled,
                      s.fetch_article, s.adapter, s.fetch_via))
            n += 1
    conn.commit()
    return n
