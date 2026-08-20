"""选股漏斗 L1/L2 —— 全集维护与每日雷达扫描。

漏斗哲学：全集廉价（530 只只拉日线）、清单昂贵（20 席全套监测）、
注意力逐层收窄。雷达是确定性的：每个命中都有可复算的原因标签，
新闻热度维度来自自家新闻管线（价格异动往往滞后于新闻异动）。
"""
from __future__ import annotations

import logging
import math
import re
from datetime import date

import psycopg

from .config import Config

log = logging.getLogger(__name__)

WATCHLIST_CAP = 20          # 关注清单总席位
PROMOTE_MIN_SCORE = 3.0     # 晋升门槛
DECAY_DAYS = 5              # 轮动位无信号衰减天数
UNIVERSE_REFRESH_DAYS = 7

_WIKI = {
    "SP500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "NDX": "https://en.wikipedia.org/wiki/Nasdaq-100",
}
_NAME_NOISE = re.compile(
    r",?\s*(Inc\.?|Corp(oration)?\.?|Co\.?|Company|Ltd\.?|plc|PLC|Holdings?|"
    r"Group|Technologies|Class [ABC]|\(.*\))\s*$")


def _clean_name(name: str) -> str:
    """公司名 → 新闻标题匹配用的短名（迭代剥后缀）。"""
    prev = None
    while prev != name:
        prev = name
        name = _NAME_NOISE.sub("", name).strip()
    return name


def refresh_universe(conn: psycopg.Connection, http_get) -> int:
    """从维基百科成分表刷新全集。http_get(url) -> html 文本。"""
    import io

    import pandas as pd

    members: dict[str, dict] = {}
    for idx, url in _WIKI.items():
        html = http_get(url)
        tables = pd.read_html(io.StringIO(html))
        table = None
        for t in tables:
            cols = [str(c).lower() for c in t.columns]
            if any("symbol" in c or "ticker" in c for c in cols):
                table = t
                break
        if table is None:
            log.warning("universe %s: no constituent table found", idx)
            continue
        sym_col = next(c for c in table.columns
                       if "symbol" in str(c).lower() or "ticker" in str(c).lower())
        name_col = next((c for c in table.columns
                         if "security" in str(c).lower()
                         or "company" in str(c).lower()), None)
        sec_col = next((c for c in table.columns
                        if "sector" in str(c).lower()), None)
        for _, row in table.iterrows():
            sym = str(row[sym_col]).strip().replace(".", "-")
            if not sym or sym == "nan" or len(sym) > 6:
                continue
            m = members.setdefault(sym, {
                "name": str(row[name_col]).strip() if name_col is not None else sym,
                "sector": str(row[sec_col]).strip() if sec_col is not None else None,
                "indexes": []})
            m["indexes"].append(idx)

    if len(members) < 300:      # 解析失败保护：别用残缺表覆盖好表
        raise RuntimeError(f"universe parse suspicious: only {len(members)} members")
    with conn.cursor() as cur:
        for sym, m in members.items():
            cur.execute("""
                INSERT INTO universe (symbol, name, sector, indexes, updated_at)
                VALUES (%s,%s,%s,%s,now())
                ON CONFLICT (symbol) DO UPDATE SET name=EXCLUDED.name,
                  sector=EXCLUDED.sector, indexes=EXCLUDED.indexes,
                  updated_at=now()""",
                        (sym, m["name"], m["sector"], m["indexes"]))
    conn.commit()
    return len(members)


# ── 廉价扫描指标（复用 market 的纯函数） ─────────────────────

def _scan_one(closes, highs, lows, vols, spy_closes) -> list[tuple[str, float, str]]:
    """单票扫描 → [(原因key, 权重, 说明)]。全部可复算。"""
    from .market import bollinger, sma

    hits: list[tuple[str, float, str]] = []
    i = len(closes) - 1
    if i < 60:
        return hits
    c = closes[i]
    ret1 = (c / closes[i - 1] - 1) * 100

    v_avg = sum(vols[-21:-1]) / 20 if len(vols) > 21 else None
    if v_avg and vols[i] / v_avg >= 2.5:
        hits.append(("volume", 1.5, f"放量 {vols[i]/v_avg:.1f}×"))
    if abs(ret1) >= 5:
        hits.append(("move", 1.5, f"单日 {ret1:+.1f}%"))
    hi52, lo52 = max(highs[-252:]), min(lows[-252:])
    if c >= hi52 * 0.995:
        hits.append(("hi52", 1.0, "触及 52 周高"))
    if c <= lo52 * 1.005:
        hits.append(("lo52", 1.0, "触及 52 周低"))

    s20, s50 = sma(closes, 20), sma(closes, 50)
    for j in range(max(1, i - 2), i + 1):     # 3 日内的新鲜均线交叉
        if s20[j - 1] and s50[j - 1] and s20[j] and s50[j]:
            if s20[j - 1] <= s50[j - 1] and s20[j] > s50[j]:
                hits.append(("cross_up", 1.2, "MA20 新上穿 MA50"))
                break
            if s20[j - 1] >= s50[j - 1] and s20[j] < s50[j]:
                hits.append(("cross_dn", 1.2, "MA20 新下穿 MA50"))
                break

    bb_mid, bb_up, bb_lo = bollinger(closes)
    widths = [(u - l) / m for u, l, m in zip(bb_up, bb_lo, bb_mid) if u and l and m]
    if len(widths) > 60:
        pct = sum(1 for w in widths[-120:] if w < widths[-1]) / min(len(widths), 120)
        if pct <= 0.08:
            hits.append(("squeeze", 0.8, "布林带宽近半年 <8% 分位"))

    if spy_closes is not None and len(spy_closes) > 21 and i >= 21:
        rs = (c / closes[i - 21] - spy_closes[-1] / spy_closes[-22]) * 100
        if rs >= 12:
            hits.append(("rs_top", 1.0, f"RS 1M {rs:+.0f}%"))
        elif rs <= -12:
            hits.append(("rs_bot", 1.0, f"RS 1M {rs:+.0f}%"))
    return hits


def _news_heat(conn: psycopg.Connection) -> dict[str, tuple[int, str]]:
    """全集公司在近 48h 新闻标题里的提及计数（python 侧匹配，一次拉全量标题）。"""
    with conn.cursor() as cur:
        cur.execute("""SELECT title FROM documents
                       WHERE fetched_at > now() - interval '48 hours'
                         AND title IS NOT NULL""")
        titles = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT symbol, name FROM universe")
        rows = cur.fetchall()
    heat: dict[str, tuple[int, str]] = {}
    for sym, name in rows:
        short = _clean_name(name)
        if len(short) < 4:            # "3M"、"GE" 这类太短的名字全靠误伤，跳过
            continue
        n = sum(1 for t in titles if short in t)
        if n >= 4:
            heat[sym] = (n, f"新闻热度 {n} 篇/48h（{short}）")
    return heat


def run_scan(conn: psycopg.Connection, cfg: Config) -> dict:
    import httpx
    import yfinance as yf

    stats = {"universe": 0, "scanned": 0, "hits": 0, "promoted": 0, "decayed": 0}

    # 全集刷新（周度）
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), coalesce(extract(epoch FROM now()-max(updated_at))/86400, 999) FROM universe")
        n_uni, age = cur.fetchone()
    if n_uni < 300 or age > UNIVERSE_REFRESH_DAYS:
        def _get(url):
            return httpx.get(url, timeout=30, follow_redirects=True,
                             headers={"User-Agent": cfg.user_agent}).text
        stats["universe"] = refresh_universe(conn, _get)
    else:
        stats["universe"] = n_uni

    with conn.cursor() as cur:
        cur.execute("SELECT symbol FROM universe ORDER BY symbol")
        symbols = [r[0] for r in cur.fetchall()]

    # 批量拉 1y 日线（分块防超时）
    frames = {}
    for k in range(0, len(symbols), 120):
        chunk = symbols[k:k + 120]
        df = yf.download(chunk, period="1y", interval="1d", group_by="ticker",
                         auto_adjust=True, threads=True, progress=False)
        for sym in chunk:
            try:
                sub = df[sym].dropna() if len(chunk) > 1 else df.dropna()
                if len(sub) >= 60:
                    frames[sym] = sub
            except KeyError:
                continue

    spy = frames.get("SPY")
    spy_closes = [float(x) for x in spy["Close"]] if spy is not None else None
    heat = _news_heat(conn)

    scored: list[tuple[str, float, list[dict]]] = []
    for sym, sub in frames.items():
        stats["scanned"] += 1
        closes = [float(x) for x in sub["Close"]]
        highs = [float(x) for x in sub["High"]]
        lows = [float(x) for x in sub["Low"]]
        vols = [int(x) for x in sub["Volume"]]
        hits = _scan_one(closes, highs, lows, vols, spy_closes)
        if sym in heat:
            n, note = heat[sym]
            hits.append(("news", min(2.0, 0.5 * math.log2(n + 1) + 0.8), note))
        if not hits:
            continue
        score = sum(w for _, w, _ in hits)
        if score >= 1.5:               # 低于此不值得记录
            scored.append((sym, score, [{"key": k, "note": nt}
                                        for k, _, nt in hits]))

    scored.sort(key=lambda x: -x[1])
    with conn.cursor() as cur:
        for sym, score, reasons in scored[:60]:
            cur.execute("""
                INSERT INTO radar_hits (day, symbol, score, reasons)
                VALUES (current_date, %s, %s, %s)
                ON CONFLICT (day, symbol) DO UPDATE SET
                  score=EXCLUDED.score, reasons=EXCLUDED.reasons""",
                        (sym, score, psycopg.types.json.Jsonb(reasons)))
        stats["hits"] = min(len(scored), 60)

        # 命中的在册标的刷新信号时间（防误衰减）
        cur.execute("""UPDATE watchlist SET last_signal_at=now()
                       WHERE symbol = ANY(%s)""",
                    ([s for s, _, _ in scored],))

        # 衰减：轮动位连续 DECAY_DAYS 天无信号且未 pin → 出局
        cur.execute("""DELETE FROM watchlist
                       WHERE kind='rotating' AND NOT pinned
                         AND last_signal_at < now() - interval '%s days'
                       RETURNING symbol""" % DECAY_DAYS)
        stats["decayed"] = cur.rowcount

        # 晋升：按分数从高到低填满空席
        cur.execute("SELECT symbol, kind FROM watchlist")
        wl = {r[0]: r[1] for r in cur.fetchall()}
        n_active = sum(1 for k in wl.values() if k in ("core", "rotating"))
        for sym, score, reasons in scored:
            if n_active >= WATCHLIST_CAP:
                break
            if score < PROMOTE_MIN_SCORE or sym in wl:
                continue
            cur.execute("""
                INSERT INTO watchlist (symbol, kind, reason)
                VALUES (%s, 'rotating', %s)""",
                        (sym, "；".join(r["note"] for r in reasons[:3])))
            cur.execute("""UPDATE radar_hits SET promoted=true
                           WHERE day=current_date AND symbol=%s""", (sym,))
            wl[sym] = "rotating"
            n_active += 1
            stats["promoted"] += 1
    conn.commit()
    return stats


def active_watchlist(conn: psycopg.Connection, cfg: Config) -> list[str]:
    """market 阶段的监测清单：配置核心仓（自动补种）+ DB 轮动位。"""
    with conn.cursor() as cur:
        for sym in cfg.watchlist:
            # 配置核心仓永远是 core：即使先被雷达收成轮动位也升格回来
            cur.execute("""
                INSERT INTO watchlist (symbol, kind, pinned, reason)
                VALUES (%s, 'core', true, 'config core')
                ON CONFLICT (symbol) DO UPDATE SET kind='core', pinned=true""",
                        (sym,))
        conn.commit()
        cur.execute("""SELECT symbol FROM watchlist
                       WHERE kind IN ('core','rotating')
                       ORDER BY kind='core' DESC, added_at""")
        return [r[0] for r in cur.fetchall()]
