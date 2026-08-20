// 个股观察页（日线级）—— 结构对标"关键位分区/均线状态/结构逻辑/失效参考"
// 四件套：K线+均线+量、MACD/KDJ、关键位分区（确定性推导）、均线状态表。
// 数据：/api/market/{sym}/bars（日线 OHLCV）+ /api/market 快照指标 + LLM note。
// 技术观察，不构成投资建议。
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Empty, PanelSkeleton } from "../components.jsx";

// ── 指标计算（客户端，纯函数） ────────────────────────────
function sma(a, n) {
  return a.map((_, i) =>
    i + 1 < n ? null : a.slice(i + 1 - n, i + 1).reduce((x, y) => x + y, 0) / n);
}
function ema(a, n) {
  const k = 2 / (n + 1);
  const out = [];
  let prev = null;
  for (const v of a) {
    prev = prev == null ? v : v * k + prev * (1 - k);
    out.push(prev);
  }
  return out;
}
function macd(c) {
  const dif = ema(c, 12).map((v, i) => v - ema(c, 26)[i]);
  const dea = ema(dif, 9);
  return { dif, dea, hist: dif.map((v, i) => (v - dea[i]) * 2) };
}
function kdj(bars, n = 9) {
  const k = [], d = [], j = [];
  let pk = 50, pd = 50;
  bars.forEach((b, i) => {
    const win = bars.slice(Math.max(0, i - n + 1), i + 1);
    const hi = Math.max(...win.map((x) => x.h));
    const lo = Math.min(...win.map((x) => x.l));
    const rsv = hi === lo ? 50 : ((b.c - lo) / (hi - lo)) * 100;
    pk = (2 / 3) * pk + (1 / 3) * rsv;
    pd = (2 / 3) * pd + (1 / 3) * pk;
    k.push(pk); d.push(pd); j.push(3 * pk - 2 * pd);
  });
  return { k, d, j };
}

const MA_DEFS = [[5, "#B5761E"], [10, "#2F5D8C"], [20, "#6A4BB5"],
                 [60, "#1E7A63"]];

function Candles({ bars }) {
  const W = 900, H = 300, VH = 70, N = bars.length;
  const hi = Math.max(...bars.map((b) => b.h));
  const lo = Math.min(...bars.map((b) => b.l));
  const y = (v) => 8 + (1 - (v - lo) / (hi - lo || 1)) * (H - 16);
  const x = (i) => (i + 0.5) * (W / N);
  const bw = Math.max(1.5, (W / N) * 0.55);
  const closes = bars.map((b) => b.c);
  const mas = MA_DEFS.map(([n, color]) => ({ n, color, s: sma(closes, n) }));
  const vmax = Math.max(...bars.map((b) => b.v || 0), 1);
  return (
    <svg viewBox={`0 0 ${W} ${H + VH + 14}`} style={{ width: "100%", display: "block" }}>
      {[hi, (hi + lo) / 2, lo].map((v, i) => (
        <g key={i}>
          <line x1="0" x2={W - 46} y1={y(v)} y2={y(v)}
                stroke="var(--hairline)" />
          <text x={W - 42} y={y(v) + 3} fontSize="10"
                fontFamily="var(--mono)" fill="var(--ink-4)">
            {v.toFixed(1)}
          </text>
        </g>
      ))}
      {bars.map((b, i) => {
        const up = b.c >= b.o;
        const col = up ? "var(--up)" : "var(--down)";
        return (
          <g key={i}>
            <line x1={x(i)} x2={x(i)} y1={y(b.h)} y2={y(b.l)}
                  stroke={col} strokeWidth="1" />
            <rect x={x(i) - bw / 2} y={y(Math.max(b.o, b.c))}
                  width={bw} height={Math.max(1, Math.abs(y(b.o) - y(b.c)))}
                  fill={up ? "none" : col} stroke={col} strokeWidth="1" />
          </g>
        );
      })}
      {mas.map((m) => (
        <polyline key={m.n} fill="none" stroke={m.color} strokeWidth="1.2"
                  points={m.s.map((v, i) => (v == null ? null : `${x(i)},${y(v)}`))
                            .filter(Boolean).join(" ")} />
      ))}
      {bars.map((b, i) => (
        <rect key={i} x={x(i) - bw / 2}
              y={H + 12 + (1 - (b.v || 0) / vmax) * (VH - 6)}
              width={bw}
              height={((b.v || 0) / vmax) * (VH - 6)}
              fill={b.c >= b.o ? "var(--up)" : "var(--down)"} opacity="0.75" />
      ))}
    </svg>
  );
}

function OscPanel({ label, series, zero }) {
  const W = 900, H = 90;
  const all = series.flatMap((s) => s.v).filter((v) => v != null);
  const hi = Math.max(...all), lo = Math.min(...all);
  const y = (v) => 6 + (1 - (v - lo) / (hi - lo || 1)) * (H - 12);
  const n = series[0].v.length;
  const x = (i) => (i / (n - 1 || 1)) * (W - 50);
  return (
    <div style={{ marginTop: 8 }}>
      <div className="uplabel" style={{ marginBottom: 4 }}>{label}</div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", display: "block" }}>
        {zero != null && zero >= lo && zero <= hi && (
          <line x1="0" x2={W - 50} y1={y(zero)} y2={y(zero)}
                stroke="var(--line)" strokeDasharray="3 3" />
        )}
        {series.map((s) =>
          s.bars
            ? s.v.map((v, i) => (
                <rect key={i} x={x(i) - 1} width="2"
                      y={Math.min(y(v), y(zero ?? 0))}
                      height={Math.max(1, Math.abs(y(v) - y(zero ?? 0)))}
                      fill={v >= (zero ?? 0) ? "var(--up)" : "var(--down)"} />
              ))
            : (
              <polyline key={s.name} fill="none" stroke={s.color}
                        strokeWidth="1.2"
                        points={s.v.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
            ))}
        {series.filter((s) => !s.bars).map((s, si) => (
          <text key={s.name} x={W - 46} y={12 + si * 12} fontSize="10"
                fontFamily="var(--mono)" fill={s.color}>
            {s.name} {s.v[s.v.length - 1]?.toFixed(1)}
          </text>
        ))}
      </svg>
    </div>
  );
}

/** 关键位分区：确定性推导（近 20/60 日高低点 + 长期均线），阈值全部明示 */
function keyZones(bars, ind) {
  const c = bars[bars.length - 1].c;
  const lo20 = Math.min(...bars.slice(-20).map((b) => b.l));
  const hi20 = Math.max(...bars.slice(-20).map((b) => b.h));
  const lo60 = Math.min(...bars.slice(-60).map((b) => b.l));
  const hi60 = Math.max(...bars.slice(-60).map((b) => b.h));
  const sma200 = ind?.sma200;
  const zones = [
    { level: lo60, name: "前期低点支撑", note: "60 日最低；跌破则结构转弱" },
    { level: lo20, name: "短线支撑", note: "20 日最低；守住是止跌前提" },
    { level: hi20, name: "短线压力", note: "20 日最高；突破并站稳，结构改善" },
    sma200 != null
      ? { level: sma200,
          name: sma200 <= c ? "长期均线支撑" : "长期均线压力",
          note: sma200 <= c ? "SMA200；回踩不破则趋势健康"
                            : "SMA200；站上则空间打开" }
      : { level: hi60, name: "阶段高点", note: "60 日最高" },
  ];
  return zones
    .filter((z) => z.level != null)
    .sort((a, b) => a.level - b.level)
    .map((z) => ({ ...z, side: z.level <= c ? "下方" : "上方" }));
}

export default function MarketSymbol({ symbol }) {
  const [bars, setBars] = useState(null);
  const [snap, setSnap] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setBars(null);
    api(`/api/market/${symbol}/bars?days=150`).then((b) => setBars(b.bars)).catch(setErr);
    api("/api/market").then((d) => setSnap(d)).catch(() => {});
  }, [symbol]);

  if (err) return <Empty>加载失败：{String(err)}</Empty>;
  if (!bars) return <div className="page"><PanelSkeleton rows={12} /></div>;
  if (bars.length < 30)
    return <Empty>{symbol} 行情序列不足（{bars.length} 天）——market stage 收盘后落数据</Empty>;

  const view = bars.slice(-120);
  const closes = bars.map((b) => b.c);
  const m = macd(closes);
  const kd = kdj(bars);
  const cut = bars.length - view.length;
  const ind = snap?.data?.[symbol]?.indicators;
  const note = snap?.notes?.[symbol];
  const c = bars[bars.length - 1].c;
  const zones = keyZones(bars, ind);

  const maStates = MA_DEFS.map(([n]) => {
    const s = sma(closes, n);
    const now = s[s.length - 1], prev = s[s.length - 6];
    return { n, v: now, dir: now != null && prev != null
             ? (now > prev ? "向上" : "向下") : "—",
             above: now != null && c >= now };
  });
  const bullCount = maStates.filter((s) => s.above).length;

  return (
    <div className="page">
      <div style={{ display: "flex", alignItems: "center" }}>
        <div className="crumbrow">
          <a href="#/market">市场快照</a>
          <span style={{ color: "var(--ink-4)" }}>/</span>
          <span style={{ fontWeight: 600, color: "var(--ink)" }}>{symbol}</span>
        </div>
        <span className="chip sm" style={{ marginLeft: "auto" }}>
          日线 · {bars[bars.length - 1].day} 收 {c.toFixed(2)}
        </span>
      </div>

      <div className="mkgrid">
        <div className="panel panel-pad">
          <div style={{ display: "flex", alignItems: "baseline", marginBottom: 6 }}>
            <span className="uplabel">K 线 · 近 {view.length} 交易日</span>
            <span className="mono" style={{ marginLeft: "auto", fontSize: 10,
                                            color: "var(--ink-4)" }}>
              {MA_DEFS.map(([n, color]) => (
                <span key={n} style={{ color, marginLeft: 8 }}>MA{n}</span>
              ))}
            </span>
          </div>
          <Candles bars={view} />
          <OscPanel label="MACD (12,26,9)" zero={0} series={[
            { name: "HIST", v: m.hist.slice(cut), bars: true },
            { name: "DIF", v: m.dif.slice(cut), color: "var(--ink)" },
            { name: "DEA", v: m.dea.slice(cut), color: "#B5761E" },
          ]} />
          <OscPanel label="KDJ (9,3,3)" series={[
            { name: "K", v: kd.k.slice(cut), color: "var(--ink)" },
            { name: "D", v: kd.d.slice(cut), color: "#B5761E" },
            { name: "J", v: kd.j.slice(cut), color: "#6A4BB5" },
          ]} />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="panel">
            <div className="sect">关键位分区 <small>20/60 日高低点 + 长期均线，确定性推导</small></div>
            <div style={{ padding: "10px 16px 14px", display: "flex",
                          flexDirection: "column", gap: 10 }}>
              {zones.map((z) => (
                <div key={z.name} style={{ display: "flex", gap: 10,
                                           alignItems: "baseline" }}>
                  <span className="mono" style={{ fontSize: 13, fontWeight: 600,
                        color: z.side === "下方" ? "var(--up)" : "var(--down)",
                        width: 64 }}>
                    {z.level.toFixed(2)}
                  </span>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 12.5,
                                  color: "var(--ink)" }}>
                      {z.name}（{z.side}）
                    </div>
                    <div style={{ fontSize: 11.5, color: "var(--ink-3)" }}>{z.note}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="sect">均线状态 <small>5 日斜率</small></div>
            <table className="mtable">
              <tbody>
                {maStates.map((s) => (
                  <tr key={s.n}>
                    <td style={{ fontWeight: 600 }}>MA{s.n}</td>
                    <td className="num">{s.v?.toFixed(2) ?? "—"}</td>
                    <td className="num"
                        style={{ color: s.dir === "向上" ? "var(--up)"
                                 : s.dir === "向下" ? "var(--down)" : "var(--ink-4)" }}>
                      {s.dir}
                    </td>
                    <td className="mono" style={{ fontSize: 10.5,
                                                  color: "var(--ink-4)" }}>
                      {s.above ? "价在上方" : "价在下方"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ padding: "8px 16px 12px", fontSize: 11.5,
                          color: "var(--ink-3)" }}>
              {bullCount === 4 ? "价格位于全部主要均线上方，多头排列"
                : bullCount === 0 ? "价格位于全部主要均线下方，空头排列"
                : `价格位于 ${bullCount}/4 条主要均线上方，均线纠缠`}
            </div>
          </div>

          {note?.headline && (
            <div className="panel">
              <div className="sect">分析 note <small>{note.at?.slice(0, 10)}</small></div>
              <div className="summary" style={{ fontSize: 14.5, lineHeight: 1.6 }}>
                {note.headline}
              </div>
            </div>
          )}

          <div className="mono" style={{ fontSize: 10, color: "var(--ink-4)",
                                         padding: "0 4px" }}>
            日线级技术观察，自动生成，不构成投资建议。
          </div>
        </div>
      </div>
    </div>
  );
}
