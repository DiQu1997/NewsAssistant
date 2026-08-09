// 市场快照（handoff 4a）：共轴时间带（归一化基期 100，绝不双纵轴）+ 标的表。
// 系列色与涨跌色为彩色 —— 用户 2026-08-08 明确否决 handoff 的纯墨方向色。
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Empty, PanelSkeleton } from "../components.jsx";

const LINE_STYLES = [
  { stroke: "#2F5D8C", dash: "" },
  { stroke: "#B0403A", dash: "" },
  { stroke: "#1E7A63", dash: "" },
  { stroke: "#B5761E", dash: "" },
];

function pct(x) {
  if (x == null) return "—";
  const v = Math.abs(x).toFixed(1);
  return x > 0 ? `▲${v}%` : x < 0 ? `▼${v}%` : "—";
}
const pctColor = (x) =>
  x > 0 ? "var(--up)" : x < 0 ? "var(--down)" : "var(--ink-4)";

function CoAxis({ seriesList }) {
  // 归一化到首日=100，共用一根轴，终点直标（handoff 硬约束）
  const W = 700, H = 210, PADR = 62;
  const all = seriesList.flatMap((s) => s.norm);
  const lo = Math.min(...all), hi = Math.max(...all);
  const y = (v) => H - ((v - lo) / (hi - lo || 1)) * (H - 20) - 10;
  const n = Math.max(...seriesList.map((s) => s.norm.length));
  const x = (i) => (i / (n - 1 || 1)) * (W - 8) + 4;
  return (
    <div style={{ position: "relative", paddingRight: PADR }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", display: "block" }}>
        {[lo, (lo + hi) / 2, hi].map((v, i) => (
          <line key={i} x1={0} x2={W} y1={y(v)} y2={y(v)}
                stroke="var(--hairline)" strokeWidth="1" />
        ))}
        {seriesList.map((s, si) => (
          <polyline key={s.symbol} fill="none"
                    stroke={LINE_STYLES[si % 4].stroke}
                    strokeDasharray={LINE_STYLES[si % 4].dash}
                    strokeWidth={si === 0 ? 1.8 : 1.3}
                    points={s.norm.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
        ))}
      </svg>
      {/* 轴标签放 HTML 沟槽，不进 SVG（handoff 踩坑记录） */}
      <div style={{ position: "absolute", right: 0, top: 0, bottom: 0,
                    width: PADR - 6, fontFamily: "var(--mono)", fontSize: 10.5,
                    color: "var(--ink-4)" }}>
        {seriesList.map((s, si) => {
          const last = s.norm[s.norm.length - 1];
          return (
            <div key={s.symbol}
                 style={{ position: "absolute",
                          color: LINE_STYLES[si % 4].stroke, fontWeight: 600,
                          top: `${((hi - last) / (hi - lo || 1)) * 88}%` }}>
              {s.symbol} {last.toFixed(0)}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function Market() {
  const [data, setData] = useState(null);
  const [bars, setBars] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api("/api/market").then(async (d) => {
      setData(d);
      const syms = (d.symbols || []).filter((s) => s !== "_MARKET").slice(0, 4);
      const bs = await Promise.all(
        syms.map((s) => api(`/api/market/${s}/bars?days=30`).catch(() => null)));
      setBars(bs.filter(Boolean).filter((b) => b.bars?.length > 2));
    }).catch(setErr);
  }, []);

  if (err) return <Empty>加载失败：{String(err)}</Empty>;
  if (!data) return <div className="page"><PanelSkeleton rows={10} /></div>;

  const syms = (data.symbols || []).filter((s) => s !== "_MARKET");
  const seriesList = (bars || []).map((b) => {
    const base = b.bars[0].c || 1;
    return { symbol: b.symbol, norm: b.bars.map((x) => (x.c / base) * 100) };
  });

  return (
    <div className="page">
      <div className="mkgrid">
        <div className="panel panel-pad">
          <div className="uplabel" style={{ marginBottom: 10 }}>
            30 日 · 归一化基期 100 · 单轴
          </div>
          {seriesList.length > 1
            ? <CoAxis seriesList={seriesList} />
            : <Empty>行情序列不足（market stage 收盘后落 bars）</Empty>}
        </div>
        <div className="panel">
          <div className="sect">信号 <small>最近扫描</small></div>
          {syms.slice(0, 8).map((sym) => {
            const note = data.notes?.[sym];
            return (
              <a className="srow rest" key={sym} href={`#/market/${sym}`}>
                <span className="t" style={{ fontFamily: "var(--sans)",
                                             fontWeight: 600, fontSize: 13 }}>
                  {sym}
                </span>
                <span className="m">
                  {note?.headline
                    ? <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                                     whiteSpace: "nowrap" }}>{note.headline}</span>
                    : <span>无分析 note</span>}
                </span>
              </a>
            );
          })}
        </div>
      </div>

      <div className="panel">
        <div className="sect">标的表 <small>{syms.length} 个关注标的</small></div>
        <table className="mtable">
          <thead>
            <tr>
              <th>标的</th><th style={{ textAlign: "right" }}>最新</th>
              <th style={{ textAlign: "right" }}>1d</th>
              <th style={{ textAlign: "right" }}>5d</th>
              <th style={{ textAlign: "right" }}>21d</th>
              <th>watchlist</th>
            </tr>
          </thead>
          <tbody>
            {syms.map((sym) => {
              const ind = data.data?.[sym]?.indicators || {};
              const wl = data.watchlist?.[sym];
              const dim = !data.notes?.[sym];
              return (
                <tr key={sym} className={dim ? "dim" : ""}>
                  <td style={{ fontWeight: 600 }}>
                    <a href={`#/market/${sym}`} style={{ textDecoration: "none",
                       borderBottom: "1px dotted var(--ink-4)" }}>{sym}</a>
                  </td>
                  <td className="num">
                    {ind.close != null ? (+ind.close).toFixed(2) : "—"}
                  </td>
                  <td className="num" style={{ color: pctColor(ind.ret_1d) }}>
                    {pct(ind.ret_1d)}
                  </td>
                  <td className="num" style={{ color: pctColor(ind.ret_5d) }}>
                    {pct(ind.ret_5d)}
                  </td>
                  <td className="num" style={{ fontWeight: 600,
                                               color: pctColor(ind.ret_21d) }}>
                    {pct(ind.ret_21d)}
                  </td>
                  <td className="mono" style={{ fontSize: 10.5, color: "var(--ink-4)" }}>
                    {wl?.kind}{wl?.pinned ? " · pinned" : ""}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
