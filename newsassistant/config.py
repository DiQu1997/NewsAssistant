"""运行配置 —— 全部来自环境变量，带开发默认值。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    database_url: str = field(default_factory=lambda: os.environ.get(
        "NA_DATABASE_URL",
        "postgresql://postgres:postgres@127.0.0.1:5432/newsassistant"))
    data_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("NA_DATA_DIR", "data")))
    sources_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("NA_SOURCES_DIR", "sources")))
    user_agent: str = os.environ.get(
        "NA_USER_AGENT",
        "NewsAssistantBot/0.1 (+https://github.com/DiQu1997/NewsAssistant)")
    http_timeout: float = float(os.environ.get("NA_HTTP_TIMEOUT", "20"))
    respect_robots: bool = os.environ.get("NA_RESPECT_ROBOTS", "1") != "0"
    max_items_per_source: int = int(os.environ.get("NA_MAX_ITEMS", "50"))
    # 近重判定：simhash 汉明距离阈值 与 回看窗口
    near_dup_hamming: int = int(os.environ.get("NA_NEAR_DUP_HAMMING", "3"))
    near_dup_days: int = int(os.environ.get("NA_NEAR_DUP_DAYS", "14"))


def load() -> Config:
    return Config()
