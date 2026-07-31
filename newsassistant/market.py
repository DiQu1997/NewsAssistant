"""行情信号层 —— 大盘与个股的技术面/期权面，全部确定性计算，不经 LLM。

设计立场：这是**信号仪表盘**，不是荐股器。每个信号是一条可复算的技术事实
（金叉、超买、带宽收缩、P/C 比…），方向标注 bull/bear 只描述信号的传统读法，
交易决策永远在人。数据源 yfinance（免 key，日线 + 期权链）。
"""
from __future__ import annotations

import logging
import math
from datetime import date

import psycopg

from .config import Config

log = logging.getLogger(__name__)


# ── 指标（纯 python，输入为时间正序数组） ─────────────────────

def sma(xs: list[float], n: int) -> list[float | None]:
    out, s = [None] * len(xs), 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(xs: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(xs)
    if len(xs) < n:
        return out
    k = 2 / (n + 1)
    out[n - 1] = sum(xs[:n]) / n
    for i in range(n, len(xs)):
        out[i] = xs[i] * k + out[i - 1] * (1 - k)
    return out


def rsi14(closes: list[float]) -> list[float | None]:
    n = 14
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    out[n] = 100 - 100 / (1 + (ag / al if al else math.inf))
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100 - 100 / (1 + (ag / al if al else math.inf))
    return out


def macd(closes: list[float]) -> tuple[list, list, list]:
    e12, e26 = ema(closes, 12), ema(closes, 26)
    line = [a - b if a is not None and b is not None else None
            for a, b in zip(e12, e26)]
    valid = [x for x in line if x is not None]
    sig_valid = ema(valid, 9)
    sig: list[float | None] = [None] * len(line)
    j = 0
    for i, x in enumerate(line):
        if x is not None:
            sig[i] = sig_valid[j]
            j += 1
    hist = [a - b if a is not None and b is not None else None
            for a, b in zip(line, sig)]
    return line, sig, hist


def bollinger(closes: list[float], n: int = 20, k: float = 2.0):
    mid = sma(closes, n)
    up: list[float | None] = [None] * len(closes)
    lo: list[float | None] = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        window = closes[i - n + 1:i + 1]
        m = mid[i]
        sd = math.sqrt(sum((x - m) ** 2 for x in window) / n)
        up[i], lo[i] = m + k * sd, m - k * sd
    return mid, up, lo


def atr14(highs, lows, closes) -> float | None:
    n = 14
    if len(closes) <= n:
        return None
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


# ── 信号（可复算的技术事实） ─────────────────────────────────

def build_signals(days, closes, highs, lows, vols) -> tuple[dict, list[dict]]:
    """返回 (指标摘要, 信号列表)。"""
    i = len(closes) - 1
    c = closes[i]
    s20, s50, s200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    rsi = rsi14(closes)
    m_line, m_sig, m_hist = macd(closes)
    bb_mid, bb_up, bb_lo = bollinger(closes)
    atr = atr14(highs, lows, closes)
    hi52, lo52 = max(highs[-252:]), min(lows[-252:])
    v_avg20 = sum(vols[-21:-1]) / 20 if len(vols) > 21 else None
    vol_ratio = vols[i] / v_avg20 if v_avg20 else None

    def ret(n):
        return (c / closes[i - n] - 1) * 100 if i >= n else None

    ind = {
        "close": c, "ret_1d": ret(1), "ret_5d": ret(5), "ret_21d": ret(21),
        "sma20": s20[i], "sma50": s50[i], "sma200": s200[i],
        "rsi": rsi[i], "macd": m_line[i], "macd_sig": m_sig[i],
        "macd_hist": m_hist[i],
        "bb_up": bb_up[i], "bb_lo": bb_lo[i],
        "atr": atr, "atr_pct": atr / c * 100 if atr else None,
        "hi52": hi52, "lo52": lo52,
        "from_hi52": (c / hi52 - 1) * 100, "from_lo52": (c / lo52 - 1) * 100,
        "vol_ratio": vol_ratio,
    }

    sigs: list[dict] = []

    def add(key, direction, note):
        sigs.append({"key": key, "dir": direction, "note": note})

    # 趋势结构
    if s50[i] and s200[i]:
        if s50[i] > s200[i] and c > s50[i]:
            add("uptrend", "bull", "多头排列：价 > MA50 > MA200")
        elif s50[i] < s200[i] and c < s50[i]:
            add("downtrend", "bear", "空头排列：价 < MA50 < MA200")
        for j in range(max(1, i - 4), i + 1):     # 5 日内均线交叉
            if s50[j - 1] and s200[j - 1] and s50[j] and s200[j]:
                if s50[j - 1] <= s200[j - 1] and s50[j] > s200[j]:
                    add("golden_cross", "bull", f"金叉（{days[j]}）：MA50 上穿 MA200")
                if s50[j - 1] >= s200[j - 1] and s50[j] < s200[j]:
                    add("death_cross", "bear", f"死叉（{days[j]}）：MA50 下穿 MA200")
    # RSI
    if rsi[i] is not None:
        if rsi[i] >= 70:
            add("rsi_overbought", "bear", f"RSI {rsi[i]:.0f} 超买区")
        elif rsi[i] <= 30:
            add("rsi_oversold", "bull", f"RSI {rsi[i]:.0f} 超卖区")
    # MACD 交叉（3 日内）
    for j in range(max(1, i - 2), i + 1):
        if all(x is not None for x in (m_line[j - 1], m_sig[j - 1],
                                       m_line[j], m_sig[j])):
            if m_line[j - 1] <= m_sig[j - 1] and m_line[j] > m_sig[j]:
                add("macd_bull_cross", "bull", f"MACD 金叉（{days[j]}）")
            if m_line[j - 1] >= m_sig[j - 1] and m_line[j] < m_sig[j]:
                add("macd_bear_cross", "bear", f"MACD 死叉（{days[j]}）")
    # 布林
    if bb_up[i] and bb_lo[i]:
        if c > bb_up[i]:
            add("bb_break_up", "bull", "收盘破布林上轨（强势/过热并存）")
        elif c < bb_lo[i]:
            add("bb_break_down", "bear", "收盘破布林下轨")
        widths = [(u - l) / m for u, l, m in zip(bb_up, bb_lo, bb_mid)
                  if u and l and m]
        if len(widths) > 60:
            cur_w = widths[-1]
            pct = sum(1 for w in widths[-120:] if w < cur_w) / min(len(widths), 120)
            if pct <= 0.15:
                add("bb_squeeze", "neutral",
                    f"布林带宽处近半年 {pct * 100:.0f}% 分位：挤压待变盘")
    # 量能
    if vol_ratio and vol_ratio >= 2:
        d = "bull" if ret(1) and ret(1) > 0 else "bear"
        add("volume_spike", d, f"放量 {vol_ratio:.1f}× 20 日均量")
    # 52 周位置
    if c >= hi52 * 0.99:
        add("near_52w_high", "bull", "距 52 周高点 <1%")
    if c <= lo52 * 1.01:
        add("near_52w_low", "bear", "距 52 周低点 <1%")
    return ind, sigs


# ── 期权面 ───────────────────────────────────────────────────

def options_snapshot(tk, spot: float) -> dict | None:
    """近月 + ~30 天两个到期的期权面：ATM IV、P/C、偏斜、max pain。"""
    try:
        exps = tk.options
        if not exps:
            return None
        today = date.today()

        def dte(e):
            y, m, d = map(int, e.split("-"))
            return (date(y, m, d) - today).days

        near = next((e for e in exps if dte(e) >= 3), exps[0])
        far = min(exps, key=lambda e: abs(dte(e) - 30))

        def chain_stats(exp):
            ch = tk.option_chain(exp)
            calls, puts = ch.calls, ch.puts

            def atm_iv(df):
                m = df[(df["strike"] > spot * 0.98) & (df["strike"] < spot * 1.02)
                       & (df["impliedVolatility"] > 0.01)]
                return float(m["impliedVolatility"].mean()) if len(m) else None

            civ, piv = atm_iv(calls), atm_iv(puts)
            iv = (civ + piv) / 2 if civ and piv else civ or piv
            c_oi, p_oi = calls["openInterest"].sum(), puts["openInterest"].sum()
            c_v, p_v = calls["volume"].fillna(0).sum(), puts["volume"].fillna(0).sum()

            # skew：~5% 价外 put IV − 价外 call IV
            otm_p = puts[(puts["strike"] < spot * 0.96)
                         & (puts["impliedVolatility"] > 0.01)]
            otm_c = calls[(calls["strike"] > spot * 1.04)
                          & (calls["impliedVolatility"] > 0.01)]
            skew = None
            if len(otm_p) and len(otm_c):
                pk = otm_p.iloc[(otm_p["strike"] - spot * 0.95).abs().argsort()[:3]]
                ck = otm_c.iloc[(otm_c["strike"] - spot * 1.05).abs().argsort()[:3]]
                skew = float(pk["impliedVolatility"].mean()
                             - ck["impliedVolatility"].mean())

            # max pain：使期权持仓总内在价值最小的行权价
            strikes = sorted(set(calls["strike"]) | set(puts["strike"]))
            best, best_pain = None, math.inf
            coi = dict(zip(calls["strike"], calls["openInterest"].fillna(0)))
            poi = dict(zip(puts["strike"], puts["openInterest"].fillna(0)))
            for s in strikes:
                pain = sum(max(s - k, 0) * v for k, v in coi.items()) \
                     + sum(max(k - s, 0) * v for k, v in poi.items())
                if pain < best_pain:
                    best, best_pain = s, pain
            return {"exp": exp, "dte": dte(exp), "atm_iv": iv,
                    "pc_oi": float(p_oi / c_oi) if c_oi else None,
                    "pc_vol": float(p_v / c_v) if c_v else None,
                    "skew": skew, "max_pain": best}

        near_s = chain_stats(near)
        out = {"near": near_s}
        if far != near:
            out["far"] = chain_stats(far)
        return out
    except Exception as e:
        log.warning("options snapshot failed: %s", e)
        return None


# ── orchestrator ─────────────────────────────────────────────

def run_market(conn: psycopg.Connection, cfg: Config) -> dict:
    import yfinance as yf

    stats = {"symbols": 0, "bars": 0, "errors": 0}
    for sym in cfg.watchlist:
        try:
            tk = yf.Ticker(sym)
            h = tk.history(period="1y", interval="1d", auto_adjust=True)
            if h.empty:
                raise RuntimeError("no bars")
            days = [d.strftime("%Y-%m-%d") for d in h.index]
            closes = [float(x) for x in h["Close"]]
            highs = [float(x) for x in h["High"]]
            lows = [float(x) for x in h["Low"]]
            vols = [int(x) for x in h["Volume"]]

            with conn.cursor() as cur:
                rows = [(sym, days[i], float(h["Open"].iloc[i]), highs[i],
                         lows[i], closes[i], vols[i]) for i in range(len(days))]
                cur.executemany("""
                    INSERT INTO market_bars (symbol, day, open, high, low, close, volume)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (symbol, day) DO UPDATE SET
                      open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                      close=EXCLUDED.close, volume=EXCLUDED.volume""", rows)
            stats["bars"] += len(days)

            ind, sigs = build_signals(days, closes, highs, lows, vols)
            opt = options_snapshot(tk, closes[-1]) if cfg.market_options else None
            payload = {"indicators": ind, "signals": sigs, "options": opt,
                       "as_of": days[-1]}
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO market_snapshots (symbol, payload)
                               VALUES (%s,%s)""",
                            (sym, psycopg.types.json.Jsonb(payload)))
            conn.commit()
            stats["symbols"] += 1
        except Exception as e:
            conn.rollback()
            stats["errors"] += 1
            log.warning("market %s: %s", sym, e)
    return stats
