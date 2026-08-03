"""运行配置 —— 默认值内置，config.json（可选）覆盖，环境变量兜底。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

# 模型选择 policy：量大的机械阶段用小模型，唯一给人读的 synthesize 用大模型。
#   extract          结构化抽取，量最大        → haiku
#   assign           归并裁决（判断题）         → sonnet
#   resolve-entities 实体消歧对（判断题）       → haiku
#   synthesize       带引用综述，直接面向阅读    → opus
DEFAULT_STAGE_MODELS: dict[str, str] = {
    "extract": "haiku",
    "assign": "sonnet",
    "resolve-entities": "haiku",
    "synthesize": "opus",
    "picture": "opus",
    "wrap": "opus",
    "note": "sonnet",
    "reading": "haiku",
    "digest": "codex:gpt-5.6-terra@medium",
}


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
    # 各 LLM 阶段的模型（别名或完整 ID）。config.json 里同名 key 可整体或部分覆盖。
    stage_models: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_STAGE_MODELS))
    # 行情信号层：关注清单（大盘 ETF + 个股）与是否抓期权面
    watchlist: list[str] = field(default_factory=lambda: [
        "SPY", "QQQ", "DIA", "IWM",
        "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN", "GOOGL"])
    market_options: bool = True
    # 阅读版本自动生成的重要度门槛（1=每篇都生成，代价按篇数线性）
    digest_min_sig: int = 4

    def stage_model(self, stage: str) -> str | None:
        return self.stage_models.get(stage)


def load(config_path: str | Path | None = None) -> Config:
    """config.json 允许覆盖任意 Config 字段；stage_models 是合并而非整体替换，
    这样文件里只写想改的阶段即可。文件不存在则纯用默认值。"""
    path = Path(config_path or os.environ.get("NA_CONFIG", "config.json"))
    overrides: dict = {}
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: 顶层必须是 JSON object")
        known = {f.name for f in fields(Config)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"{path}: 未知配置项 {sorted(unknown)}")
        overrides = dict(data)
        if "stage_models" in overrides:
            merged = dict(DEFAULT_STAGE_MODELS)
            merged.update(overrides["stage_models"])
            overrides["stage_models"] = merged
        for key in ("data_dir", "sources_dir"):
            if key in overrides:
                overrides[key] = Path(overrides[key])
    return Config(**overrides)
