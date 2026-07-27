"""内容寻址文件存储 —— 正文存文件，库里存指针（docs/architecture.md L0）。

路径 = data_dir/content/<sha256 前 2 位>/<sha256>.txt。
内容寻址天然做精确去重：同文只落盘一次。
"""
from __future__ import annotations

import hashlib
from pathlib import Path


class ContentStore:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "content"

    def put(self, text: str) -> tuple[str, str]:
        """存入文本，返回 (sha256hex, 相对引用路径)。已存在则不重写。"""
        raw = text.encode("utf-8")
        sha = hashlib.sha256(raw).hexdigest()
        rel = f"content/{sha[:2]}/{sha}.txt"
        path = self.root / sha[:2] / f"{sha}.txt"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(raw)
            tmp.replace(path)          # 原子落盘
        return sha, rel

    def get(self, ref: str) -> str:
        return (self.root.parent / ref).read_text(encoding="utf-8")
