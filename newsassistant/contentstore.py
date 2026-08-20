"""内容寻址文件存储 —— 正文存文件，库里存指针（docs/architecture.md L0）。

路径 = data_dir/content/<sha256 前 2 位>/<sha256>.txt。
内容寻址天然做精确去重：同文只落盘一次。

冷热分层：archive 阶段把超过热窗口的文件迁去 rclone 远端（目录结构不变），
get() 在本地未命中时回落远端并回填本地（cache-on-read）。指针（ref）
对上层永远稳定 —— 文件住在哪一层是存储的私事。
"""
from __future__ import annotations

import gzip
import hashlib
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class ContentStore:
    def __init__(self, data_dir: Path, remote: str = ""):
        self.root = data_dir / "content"
        self.remote = remote.rstrip("/") if remote else ""

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

    def put_raw(self, data: bytes) -> str:
        """原始 HTML/PDF 字节 → gzip 压缩落本地暂存区，返回引用路径。

        原始层是"可重放"的保险：换了抽取器可以对历史全量重跑。写一次
        不再被管线读取，archive 阶段每天整体迁去远端；按原始字节内容
        寻址，扩展名从魔数嗅探（列目录时能一眼分清网页与 PDF）。
        """
        sha = hashlib.sha256(data).hexdigest()
        ext = "pdf" if b"%PDF-" in data[:1024] else "html"
        rel = f"raw/{sha[:2]}/{sha}.{ext}.gz"
        path = self.root.parent / rel
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with gzip.open(tmp, "wb", compresslevel=6) as f:
                f.write(data)
            tmp.replace(path)
        return rel

    def get(self, ref: str) -> str:
        path = self.root.parent / ref
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            if not self.remote:
                raise
        # 冷层回落：低频路径（故事深挖、补生成阅读版本），几秒延迟可接受
        p = subprocess.run(["rclone", "cat", f"{self.remote}/{ref}"],
                           capture_output=True, timeout=120)
        if p.returncode != 0:
            raise FileNotFoundError(
                f"{ref}: 本地与冷层均无 "
                f"({p.stderr.decode('utf-8', 'replace').strip()[:200]})")
        # 回填本地：同一篇再读走热层；put 的原子写法在此同样适用
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(p.stdout)
        tmp.replace(path)
        log.info("content %s: 冷层回落并回填", ref)
        return p.stdout.decode("utf-8")
