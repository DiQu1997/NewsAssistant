"""64-bit simhash —— 近重与转述候选检测。

特征取词的 3-shingle（对 CJK 按字符 3-gram），blake2b 哈希到 64 bit。
汉明距离 ≤ 阈值（默认 3）视为近重候选 —— 是候选，不是判决：
转述判定（syndication_of）属于阶段 3 的裁决，这里只负责把候选找出来。
"""
from __future__ import annotations

import hashlib
import re

_WORD = re.compile(r"[A-Za-z0-9]+|[一-鿿぀-ヿ가-힯]")


def _features(text: str) -> list[str]:
    toks = _WORD.findall(text.lower())
    if len(toks) < 3:
        return toks
    return [" ".join(toks[i:i + 3]) for i in range(len(toks) - 2)]


def simhash64(text: str) -> int:
    v = [0] * 64
    for f in _features(text):
        h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
        for i in range(64):
            v[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(64):
        if v[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return ((a ^ b) & 0xFFFFFFFFFFFFFFFF).bit_count()


def to_signed(h: int) -> int:
    """Postgres bigint 是有符号的；对称转换，round-trip 无损。"""
    return h - (1 << 64) if h >= (1 << 63) else h


def from_signed(h: int) -> int:
    return h + (1 << 64) if h < 0 else h
