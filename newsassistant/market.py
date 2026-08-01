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


# ── 结构分析（全部可复算） ───────────────────────────────────

def hv20(closes: list[float]) -> float | None:
    """20 日已实现波动率（年化）——与 ATM IV 对照出波动率溢价。"""
    if len(closes) < 22:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(-20, 0)]
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var * 252)


def swing_levels(highs, lows, closes) -> dict:
    """摆动高低点（窗口 5 的局部极值）→ 距当前价最近的支撑/阻力各两档。"""
    c = closes[-1]
    res, sup = [], []
    for i in range(5, len(highs) - 5):
        w = 5
        if highs[i] == max(highs[i - w:i + w + 1]) and highs[i] > c:
            res.append(highs[i])
        if lows[i] == min(lows[i - w:i + w + 1]) and lows[i] < c:
            sup.append(lows[i])
    res = sorted(set(round(x, 2) for x in res))[:2]
    sup = sorted(set(round(x, 2) for x in sup), reverse=True)[:2]
    return {"resistance": res, "support": sup}


def rsi_divergence(closes, rsi_vals, lookback: int = 40) -> str | None:
    """近端背离：价格新高而 RSI 走低（顶背离）/ 价格新低而 RSI 走高（底背离）。"""
    n = len(closes)
    if n < lookback + 5:
        return None
    seg = range(n - lookback, n)
    highs_i = [i for i in seg if 2 <= i < n - 2
               and closes[i] == max(closes[i - 2:i + 3])]
    lows_i = [i for i in seg if 2 <= i < n - 2
              and closes[i] == min(closes[i - 2:i + 3])]
    if len(highs_i) >= 2:
        a, b = highs_i[-2], highs_i[-1]
        if (closes[b] > closes[a] and rsi_vals[a] is not None
                and rsi_vals[b] is not None and rsi_vals[b] < rsi_vals[a] - 2):
            return "bearish"
    if len(lows_i) >= 2:
        a, b = lows_i[-2], lows_i[-1]
        if (closes[b] < closes[a] and rsi_vals[a] is not None
                and rsi_vals[b] is not None and rsi_vals[b] > rsi_vals[a] + 2):
            return "bullish"
    return None


def build_signals(days, closes, highs, lows, opens, vols,
                  spy_closes: list[float] | None = None
                  ) -> tuple[dict, list[dict]]:
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

    # 相对强弱（vs SPY）：同窗收益差
    def rs(n):
        if spy_closes is None or len(spy_closes) <= n or i < n:
            return None
        return ((c / closes[i - n]) - (spy_closes[-1] / spy_closes[-1 - n])) * 100

    # 连续同向天数（+3 = 三连阳）
    streak = 0
    for j in range(i, 0, -1):
        d = closes[j] - closes[j - 1]
        if streak == 0:
            streak = 1 if d > 0 else -1 if d < 0 else 0
            if streak == 0:
                break
        elif (d > 0) == (streak > 0) and d != 0:
            streak += 1 if streak > 0 else -1
        else:
            break

    # 最大回撤（1y，沿途峰值）与当前回撤
    peak, mdd = closes[0], 0.0
    for x in closes:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)

    atr_prev = atr14(highs[:-20], lows[:-20], closes[:-20]) if len(closes) > 40 else None
    div = rsi_divergence(closes, rsi)

    ind = {
        "close": c, "ret_1d": ret(1), "ret_5d": ret(5), "ret_21d": ret(21),
        "ret_63d": ret(63),
        "rs_21d": rs(21), "rs_63d": rs(63),
        "sma20": s20[i], "sma50": s50[i], "sma200": s200[i],
        "rsi": rsi[i], "macd": m_line[i], "macd_sig": m_sig[i],
        "macd_hist": m_hist[i],
        "bb_up": bb_up[i], "bb_lo": bb_lo[i],
        "atr": atr, "atr_pct": atr / c * 100 if atr else None,
        "atr_trend": atr / atr_prev if atr and atr_prev else None,
        "hv20": hv20(closes),
        "hi52": hi52, "lo52": lo52,
        "from_hi52": (c / hi52 - 1) * 100, "from_lo52": (c / lo52 - 1) * 100,
        "max_dd_1y": mdd * 100,
        "vol_ratio": vol_ratio,
        "gap_1d": (opens[i] / closes[i - 1] - 1) * 100 if i >= 1 else None,
        "streak": streak,
        "divergence": div,
        "levels": swing_levels(highs, lows, closes),
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
    # 背离
    if div == "bearish":
        add("rsi_div_bear", "bear", "顶背离：价格新高而 RSI 走低")
    elif div == "bullish":
        add("rsi_div_bull", "bull", "底背离：价格新低而 RSI 走高")
    # 跳空
    if ind["gap_1d"] is not None and abs(ind["gap_1d"]) >= 1.5:
        add("gap", "bull" if ind["gap_1d"] > 0 else "bear",
            f"跳空{'高' if ind['gap_1d'] > 0 else '低'}开 {ind['gap_1d']:+.1f}%")
    # 连续同向
    if abs(ind["streak"]) >= 5:
        add("streak", "bull" if ind["streak"] > 0 else "bear",
            f"{abs(ind['streak'])} 连{'阳' if ind['streak'] > 0 else '阴'}")
    # 波动扩张
    if ind["atr_trend"] and ind["atr_trend"] >= 1.5:
        add("vol_expansion", "neutral",
            f"ATR 较一个月前扩张 {ind['atr_trend']:.1f}×：波动进入放大期")

    # 综合评分（-6..+6）：结构位置的加权和，不是预测
    score = 0
    if s200[i]:
        score += 2 if c > s200[i] else -2
    if s50[i]:
        score += 1 if c > s50[i] else -1
    if m_hist[i] is not None:
        score += 1 if m_hist[i] > 0 else -1
    if rsi[i] is not None:
        if rsi[i] >= 70:
            score -= 1
        elif rsi[i] <= 30:
            score += 1
    if ind["rs_21d"] is not None:
        score += 1 if ind["rs_21d"] > 0 else -1
    ind["score"] = score
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

            # 持仓墙：现价 ±10% 内 call+put 总 OI 最大的三档 —— 期权市场
            # 用真金白银标出的关注价位（常表现为磁吸/阻力）
            tot = {}
            for k in strikes:
                if spot * 0.9 <= k <= spot * 1.1:
                    tot[k] = float(coi.get(k, 0)) + float(poi.get(k, 0))
            walls = [{"strike": k, "oi": int(v)} for k, v in
                     sorted(tot.items(), key=lambda x: -x[1])[:3]]

            d = max(dte(exp), 1)
            exp_move = spot * iv * math.sqrt(d / 365) if iv else None
            return {"exp": exp, "dte": dte(exp), "atm_iv": iv,
                    "pc_oi": float(p_oi / c_oi) if c_oi else None,
                    "pc_vol": float(p_v / c_v) if c_v else None,
                    "skew": skew, "max_pain": best,
                    "oi_walls": walls,
                    "exp_move": exp_move,
                    "exp_move_pct": exp_move / spot * 100 if exp_move else None}

        near_s = chain_stats(near)
        out = {"near": near_s}
        if far != near:
            out["far"] = chain_stats(far)
            a, b = near_s.get("atm_iv"), out["far"].get("atm_iv")
            if a and b:
                # 期限结构：近月 IV − 远月 IV 为正 = 倒挂（事件/恐慌定价）
                out["term_slope"] = a - b
        return out
    except Exception as e:
        log.warning("options snapshot failed: %s", e)
        return None


# ── orchestrator ─────────────────────────────────────────────

def run_market(conn: psycopg.Connection, cfg: Config) -> dict:
    import yfinance as yf

    from .universe import active_watchlist

    stats = {"symbols": 0, "bars": 0, "errors": 0}
    spy_closes: list[float] | None = None
    collected: list[dict] = []
    watch = active_watchlist(conn, cfg)
    # SPY 先算：其余标的的相对强弱以它为基准
    order = (["SPY"] if "SPY" in watch else []) \
        + [s for s in watch if s != "SPY"]
    for sym in order:
        try:
            tk = yf.Ticker(sym)
            h = tk.history(period="1y", interval="1d", auto_adjust=True)
            if h.empty:
                raise RuntimeError("no bars")
            days = [d.strftime("%Y-%m-%d") for d in h.index]
            opens = [float(x) for x in h["Open"]]
            closes = [float(x) for x in h["Close"]]
            highs = [float(x) for x in h["High"]]
            lows = [float(x) for x in h["Low"]]
            vols = [int(x) for x in h["Volume"]]

            with conn.cursor() as cur:
                rows = [(sym, days[i], opens[i], highs[i],
                         lows[i], closes[i], vols[i]) for i in range(len(days))]
                cur.executemany("""
                    INSERT INTO market_bars (symbol, day, open, high, low, close, volume)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (symbol, day) DO UPDATE SET
                      open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                      close=EXCLUDED.close, volume=EXCLUDED.volume""", rows)
            stats["bars"] += len(days)

            ind, sigs = build_signals(days, closes, highs, lows, opens, vols,
                                      spy_closes)
            if sym == "SPY":
                spy_closes = closes
            opt = options_snapshot(tk, closes[-1]) if cfg.market_options else None
            payload = {"indicators": ind, "signals": sigs, "options": opt,
                       "as_of": days[-1]}
            collected.append({"symbol": sym, "ind": ind, "opt": opt})
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO market_snapshots (symbol, payload)
                               VALUES (%s,%s)""",
                            (sym, psycopg.types.json.Jsonb(payload)))
                if sigs:      # 触发任何信号 → 轮动位保鲜
                    cur.execute("""UPDATE watchlist SET last_signal_at=now()
                                   WHERE symbol=%s""", (sym,))
            conn.commit()
            stats["symbols"] += 1
        except Exception as e:
            conn.rollback()
            stats["errors"] += 1
            log.warning("market %s: %s", sym, e)

    # 市场宽度汇总（存 _MARKET 伪标的）：个股结构的聚合就是市场状态
    if collected:
        n = len(collected)
        above50 = sum(1 for x in collected
                      if x["ind"].get("sma50") and x["ind"]["close"] > x["ind"]["sma50"])
        above200 = sum(1 for x in collected
                       if x["ind"].get("sma200") and x["ind"]["close"] > x["ind"]["sma200"])
        adv = sum(1 for x in collected if (x["ind"].get("ret_1d") or 0) > 0)
        rsis = [x["ind"]["rsi"] for x in collected if x["ind"].get("rsi") is not None]
        ivs = [x["opt"]["near"]["atm_iv"] for x in collected
               if x.get("opt") and x["opt"].get("near")
               and x["opt"]["near"].get("atm_iv")]
        hvs = [x["ind"]["hv20"] for x in collected if x["ind"].get("hv20")]
        breadth = {
            "n": n, "pct_above_ma50": above50 / n * 100,
            "pct_above_ma200": above200 / n * 100,
            "advancers": adv, "decliners": n - adv,
            "avg_rsi": sum(rsis) / len(rsis) if rsis else None,
            "avg_iv": sum(ivs) / len(ivs) if ivs else None,
            "avg_hv20": sum(hvs) / len(hvs) if hvs else None,
            "scores": {x["symbol"]: x["ind"].get("score") for x in collected},
        }
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO market_snapshots (symbol, payload)
                           VALUES ('_MARKET', %s)""",
                        (psycopg.types.json.Jsonb(breadth),))
        conn.commit()
    return stats
