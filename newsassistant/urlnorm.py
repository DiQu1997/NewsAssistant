"""URL 规范化 —— 去重的第一道闸。

刻意保守：只做确定安全的变换（追踪参数、fragment、默认端口、大小写、
尾斜杠）。激进变换（AMP 还原、移动子域折叠）留给后续有证据时再加 ——
规范化过度会把不同文章折叠成一条，比漏合并更糟。
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# 明确的追踪参数：前缀匹配 + 全名匹配
_TRACK_PREFIXES = ("utm_", "mc_", "pk_", "piwik_", "matomo_", "hsa_", "vero_")
_TRACK_EXACT = {
    "gclid", "gclsrc", "dclid", "fbclid", "msclkid", "twclid", "igshid",
    "mkt_tok", "ref", "ref_src", "ref_url", "referrer", "source", "cmpid",
    "cmp", "ncid", "sr_share", "ocid", "smid", "smtyp", "share_type",
    "wt_mc", "s_kwcid", "spm", "scm", "from", "isappinstalled",
}


def canonical_url(url: str) -> str:
    s = urlsplit(url.strip())
    scheme = (s.scheme or "https").lower()
    host = s.hostname.lower() if s.hostname else ""
    port = s.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"

    q = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=True)
         if not (k.lower() in _TRACK_EXACT or k.lower().startswith(_TRACK_PREFIXES))]
    q.sort()

    path = s.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    return urlunsplit((scheme, host, path, urlencode(q), ""))
