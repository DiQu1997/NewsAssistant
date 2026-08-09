// 市场快照三屏：宏观（风险罗盘/收益率曲线/全球接力/商品汇率带/叙事仪表）
// → 结构（体温计/宽度历史/风格四象限/宽度热力图/行业强弱/比值）
// → 个股（共轴/RS排行/背离榜/RSI条带/标的表/雷达）。
// 数据 /api/market/overview（含 _MACRO 快照）+ bars。技术观察，不构成投资建议。
// 彩色系列与涨跌色：用户 2026-08-08 明确否决 handoff 的纯墨方向色。
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Empty, PanelSkeleton } from "../components.jsx";

const LINE_STYLES = ["#2F5D8C", "#B0403A", "#1E7A63", "#B5761E"];

function pct(x, digits = 1) {
  if (x == null) return "—";
  const v = Math.abs(x).toFixed(digits);
  return x > 0 ? `▲${v}%` : x < 0 ? `▼${v}%` : "—";
}
const pctColor = (x) =>
  x > 0 ? "var(--up)" : x < 0 ? "var(--down)" : "var(--ink-4)";
const fmtNum = (v) =>
  v == null ? "—" : Math.abs(v) >= 1000 ? v.toFixed(0)
  : Math.abs(v) >= 100 ? v.toFixed(1)
  : Math.abs(v) >= 10 ? v.toFixed(2) : v.toFixed(3);

function rank(vals, v) {
  if (v == null || !vals.length) return 0;
  return vals.filter((x) => x <= v).length / vals.length;
}

function Hdr({ children }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12,
                  margin: "10px 0 -4px" }}>
      <span className="uplabel" style={{ letterSpacing: ".16em" }}>{children}</span>
      <span style={{ flex: 1, height: 1, background: "var(--hairline)" }} />
    </div>
  );
}

function BigNum({ label, value, sub, color }) {
  return (
    <div>
      <div className="uplabel">{label}</div>
      <div className="bignum" style={{ color: color || "var(--ink)" }}>{value}</div>
      {sub && <div style={{ fontSize: 10.5, color: "var(--ink-4)" }}>{sub}</div>}
    </div>
  );
}

function Spark({ xs, color = "var(--ink-3)", h = 30 }) {
  if (!xs || xs.length < 2) return null;
  const lo = Math.min(...xs), hi = Math.max(...xs), W = 120;
  const pts = xs.map((v, i) =>
    `${(i / (xs.length - 1)) * W},${h - 2 - ((v - lo) / (hi - lo || 1)) * (h - 4)}`
  ).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${h}`} preserveAspectRatio="none"
         style={{ width: "100%", height: h, display: "block" }}>
      <polyline fill="none" stroke={color} strokeWidth="1.4" points={pts} />
    </svg>
  );
}

// ── 宏观屏 ──────────────────────────────────────────────────

function RiskCompass({ compass }) {
  const { score, votes, max } = compass;
  const color = score > 0 ? "var(--up)" : score < 0 ? "var(--down)" : "var(--ink-3)";
  return (
    <div className="panel panel-pad">
      <div className="uplabel" style={{ marginBottom: 10 }}>
        风险偏好罗盘 · {max} 票合议
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <span className="bignum" style={{ color, fontSize: 34 }}>
          {score > 0 ? `+${score}` : score}
        </span>
        <div style={{ flex: 1, display: "flex", gap: 3 }}>
          {Array.from({ length: 2 * max + 1 }, (_, i) => i - max).map((k) => (
            <span key={k} style={{ flex: 1, height: 10, borderRadius: 2,
              background: k === 0 ? "var(--line)"
                : (k > 0 && score >= k) ? "var(--up)"
                : (k < 0 && score <= k) ? "var(--down)" : "var(--dens-1)" }} />
          ))}
        </div>
      </div>
      <div style={{ fontSize: 11, color: "var(--ink-4)", margin: "2px 0 8px" }}>
        {score >= 2 ? "risk-on：跨资产多数在买风险" :
         score <= -2 ? "risk-off：跨资产多数在避险" : "无共识：各资产各说各话"}
      </div>
      {votes.map((v) => (
        <div key={v.key} style={{ display: "flex", gap: 8, margin: "5px 0",
                                  alignItems: "baseline" }}>
          <span className="mono" style={{ width: 24, fontWeight: 700, fontSize: 11,
                color: v.dir > 0 ? "var(--up)" : v.dir < 0 ? "var(--down)"
                       : "var(--ink-4)" }}>
            {v.dir > 0 ? "+1" : v.dir < 0 ? "−1" : "0"}
          </span>
          <span style={{ fontSize: 11.5, color: "var(--ink-2)", flex: 1 }}>
            {v.note}
          </span>
        </div>
      ))}
    </div>
  );
}

function YieldCurve({ curve }) {
  const pts = (curve?.points || []).filter((p) => p.now != null);
  if (pts.length < 2) return <Empty>利率数据不足</Empty>;
  const W = 320, H = 150, PADX = 30, PADY = 22;
  const all = pts.flatMap((p) => [p.now, p.prev]).filter((v) => v != null);
  const lo = Math.min(...all) - 0.15, hi = Math.max(...all) + 0.15;
  const x = (i) => PADX + (i / (pts.length - 1)) * (W - 2 * PADX);
  const y = (v) => H - PADY - ((v - lo) / (hi - lo || 1)) * (H - 2 * PADY);
  const sp = curve.spread_10y_3m;
  return (
    <div className="panel panel-pad">
      <div className="uplabel" style={{ marginBottom: 6 }}>
        美债收益率曲线 · 实线今天 / 虚线 21 交易日前
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", display: "block" }}>
        {pts[0].prev != null && (
          <polyline fill="none" stroke="var(--ink-4)" strokeWidth="1.2"
                    strokeDasharray="4 3"
                    points={pts.filter((p) => p.prev != null)
                      .map((p, i) => `${x(i)},${y(p.prev)}`).join(" ")} />
        )}
        <polyline fill="none" stroke={LINE_STYLES[0]} strokeWidth="1.8"
                  points={pts.map((p, i) => `${x(i)},${y(p.now)}`).join(" ")} />
        {pts.map((p, i) => (
          <g key={p.tenor}>
            <circle cx={x(i)} cy={y(p.now)} r="2.6" fill={LINE_STYLES[0]} />
            <text x={x(i)} y={y(p.now) - 7} textAnchor="middle"
                  style={{ font: "600 10px var(--mono)", fill: "var(--ink)" }}>
              {p.now.toFixed(2)}
            </text>
            <text x={x(i)} y={H - 6} textAnchor="middle"
                  style={{ font: "10px var(--mono)", fill: "var(--ink-4)" }}>
              {p.tenor}
            </text>
          </g>
        ))}
      </svg>
      {sp && (
        <div className="mono" style={{ fontSize: 11, marginTop: 4,
              color: sp.now < 0 ? "var(--down)" : "var(--ink-2)" }}>
          10Y−3M 利差 {sp.now >= 0 ? "+" : ""}{sp.now.toFixed(2)}%
          {sp.prev != null && ` （21 日前 ${sp.prev >= 0 ? "+" : ""}${sp.prev.toFixed(2)}%）`}
          {sp.now < 0 && " · 倒挂"}
        </div>
      )}
    </div>
  );
}

function NarrativeGauge({ gauge }) {
  const doms = (gauge?.domains || []).slice()
    .sort((a, b) => b.cur - a.cur);
  const max = Math.max(...doms.map((d) => d.cur), 1);
  return (
    <div className="panel panel-pad">
      <div className="uplabel" style={{ marginBottom: 8 }}>
        宏观叙事仪表 · 六域 importance 加权 · 本 7 日 vs 前 7 日
      </div>
      {doms.map((d) => {
        const chg = d.prev > 0 ? (d.cur / d.prev - 1) * 100 : null;
        return (
          <div key={d.domain} style={{ display: "flex", alignItems: "center",
                                       gap: 8, margin: "5px 0" }}>
            <span style={{ width: 58, fontSize: 11, color: "var(--ink-2)" }}>
              {d.domain}
            </span>
            <div style={{ flex: 1, height: 9, borderRadius: 2,
                          background: "var(--dens-0)" }}>
              <div style={{ height: 9, borderRadius: 2, background: "var(--dens-5)",
                            width: `${(d.cur / max) * 100}%` }} />
            </div>
            <span className="mono" style={{ width: 76, fontSize: 10.5,
                  textAlign: "right",
                  color: chg > 25 ? "var(--mark)" : "var(--ink-4)" }}>
              {d.cur}{chg != null && ` ${chg >= 0 ? "▲" : "▼"}${Math.abs(chg).toFixed(0)}%`}
            </span>
          </div>
        );
      })}
      {(gauge?.stories || []).length > 0 && (
        <div style={{ marginTop: 10, borderTop: "1px solid var(--hairline)",
                      paddingTop: 8 }}>
          {gauge.stories.slice(0, 4).map((s) => (
            <div key={s.id} style={{ margin: "4px 0", fontSize: 12,
                                     fontFamily: "var(--serif)" }}>
              <span className="mono" style={{ fontSize: 9.5, color: "var(--mark)",
                                              marginRight: 6 }}>
                重要度{s.importance}
              </span>
              <a href={`#/story/${s.id}`}>{s.title}</a>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const RELAY_ZONE = { "^N225": "亚", "000001.SS": "亚", "^HSI": "亚",
                     "^GDAXI": "欧", "^STOXX50E": "欧",
                     "^GSPC": "美", "^IXIC": "美", "^RUT": "美" };

function Relay({ relay }) {
  let prevZone = null;
  return (
    <div className="panel panel-pad">
      <div className="uplabel" style={{ marginBottom: 10 }}>
        全球接力 · 按开盘时区排序 · 1d / 5d
      </div>
      <div style={{ display: "flex", gap: 0, overflowX: "auto",
                    alignItems: "stretch" }}>
        {relay.map((r) => {
          const zone = RELAY_ZONE[r.sym];
          const newZone = zone !== prevZone;
          prevZone = zone;
          return (
            <div key={r.sym} style={{ display: "flex", alignItems: "stretch" }}>
              {newZone && (
                <div style={{ display: "flex", flexDirection: "column",
                              justifyContent: "center", padding: "0 10px",
                              borderLeft: zone !== "亚" ? "1px solid var(--line)" : "none",
                              marginLeft: zone !== "亚" ? 10 : 0 }}>
                  <span className="mono" style={{ fontSize: 10, fontWeight: 700,
                        color: "var(--ink-3)" }}>
                    {zone}
                  </span>
                </div>
              )}
              <div style={{ padding: "0 14px 0 4px", minWidth: 86 }}>
                <div style={{ fontSize: 11, color: "var(--ink-3)",
                              whiteSpace: "nowrap" }}>
                  {r.label}
                </div>
                <div className="mono" style={{ fontSize: 16, fontWeight: 700,
                      color: pctColor(r.ret_1d) }}>
                  {pct(r.ret_1d)}
                </div>
                <div className="mono" style={{ fontSize: 10.5,
                      color: pctColor(r.ret_5d) }}>
                  5d {pct(r.ret_5d)}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MacroBand({ band }) {
  return (
    <div style={{ display: "grid", gap: 10,
                  gridTemplateColumns: "repeat(auto-fill, minmax(148px, 1fr))" }}>
      {band.map((a) => (
        <div key={a.sym} className="panel" style={{ padding: "10px 12px 8px" }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "baseline" }}>
            <span style={{ fontSize: 11, color: "var(--ink-3)" }}>{a.label}</span>
            <span className="mono" style={{ fontSize: 13, fontWeight: 700 }}>
              {fmtNum(a.last)}
            </span>
          </div>
          <div className="mono" style={{ fontSize: 10.5, margin: "2px 0 4px" }}>
            <span style={{ color: pctColor(a.ret_1d) }}>{pct(a.ret_1d)}</span>
            <span style={{ color: "var(--ink-4)" }}> · 21d </span>
            <span style={{ color: pctColor(a.ret_21d) }}>{pct(a.ret_21d)}</span>
          </div>
          <Spark xs={a.spark}
                 color={a.ret_21d > 0 ? "var(--up)" : a.ret_21d < 0
                        ? "var(--down)" : "var(--ink-4)"} />
        </div>
      ))}
    </div>
  );
}

// ── 结构屏 ──────────────────────────────────────────────────

function BreadthHistory({ hist }) {
  const { days, pct50, pct200 } = hist;
  const W = 700, H = 170, PADY = 14;
  const x = (i) => (i / (days.length - 1 || 1)) * (W - 8) + 4;
  const y = (v) => H - PADY - (v / 100) * (H - 2 * PADY);
  const p200 = pct200.filter((v) => v != null);
  return (
    <div className="panel panel-pad">
      <div className="uplabel" style={{ marginBottom: 8 }}>
        宽度历史 · 近 {days.length} 交易日 ·{" "}
        <span style={{ color: LINE_STYLES[0] }}>■</span> 站上 MA50{"  "}
        <span style={{ color: LINE_STYLES[2] }}>■</span> 站上 MA200
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", display: "block" }}>
        {[25, 50, 75].map((v) => (
          <g key={v}>
            <line x1={0} x2={W} y1={y(v)} y2={y(v)} stroke="var(--hairline)"
                  strokeDasharray={v === 50 ? "" : "3 4"} />
            <text x={2} y={y(v) - 3}
                  style={{ font: "9px var(--mono)", fill: "var(--ink-4)" }}>
              {v}%
            </text>
          </g>
        ))}
        {p200.length > 1 && (
          <polyline fill="none" stroke={LINE_STYLES[2]} strokeWidth="1.4"
                    points={pct200.map((v, i) => v != null ? `${x(i)},${y(v)}` : null)
                      .filter(Boolean).join(" ")} />
        )}
        <polyline fill="none" stroke={LINE_STYLES[0]} strokeWidth="1.8"
                  points={pct50.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
      </svg>
      <div style={{ display: "flex", justifyContent: "space-between",
                    fontFamily: "var(--mono)", fontSize: 9.5,
                    color: "var(--ink-4)" }}>
        <span>{days[0]}</span>
        <span>宽度背离（价新高而此线走低）是顶部最早的预警</span>
        <span>{days[days.length - 1]}</span>
      </div>
    </div>
  );
}

function StyleQuadrant({ trail }) {
  if (!trail || trail.length < 2) return <Empty>风格数据不足</Empty>;
  const R = Math.max(...trail.flatMap((p) => [Math.abs(p.x), Math.abs(p.y)]), 2) * 1.2;
  const W = 300, H = 240;
  const x = (v) => W / 2 + (v / R) * (W / 2 - 14);
  const y = (v) => H / 2 - (v / R) * (H / 2 - 14);
  const last = trail[trail.length - 1];
  return (
    <div className="panel panel-pad">
      <div className="uplabel" style={{ marginBottom: 6 }}>
        风格四象限 · 21d 相对收益 · 60 日轨迹（5 日一点）
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", display: "block" }}>
        <line x1={W / 2} x2={W / 2} y1={6} y2={H - 6} stroke="var(--line)" />
        <line x1={6} x2={W - 6} y1={H / 2} y2={H / 2} stroke="var(--line)" />
        {[["大盘 · 成长", W - 8, 14, "end"], ["大盘 · 价值", 8, 14, "start"],
          ["小盘 · 成长", W - 8, H - 8, "end"], ["小盘 · 价值", 8, H - 8, "start"]]
          .map(([t, tx, ty, anchor]) => (
          <text key={t} x={tx} y={ty} textAnchor={anchor}
                style={{ font: "10px var(--sans)", fill: "var(--ink-4)" }}>
            {t}
          </text>
        ))}
        <polyline fill="none" stroke="var(--ink-4)" strokeWidth="1"
                  strokeDasharray="2 3"
                  points={trail.map((p) => `${x(p.x)},${y(p.y)}`).join(" ")} />
        {trail.map((p, i) => (
          <circle key={i} cx={x(p.x)} cy={y(p.y)}
                  r={i === trail.length - 1 ? 4.5 : 2.2}
                  fill={i === trail.length - 1 ? LINE_STYLES[1] : "var(--ink-4)"}
                  opacity={0.35 + 0.65 * (i / (trail.length - 1))} />
        ))}
        <text x={x(last.x) + 8} y={y(last.y) + 4}
              style={{ font: "600 10px var(--mono)", fill: LINE_STYLES[1] }}>
          现在
        </text>
      </svg>
      <div style={{ fontSize: 10.5, color: "var(--ink-4)", marginTop: 4 }}>
        横轴：成长(IWF)−价值(IWD)；纵轴：大盘(SPY)−小盘(IWM)。
        现在落点 = 资金在买{last.y >= 0 ? "大盘" : "小盘"}
        {last.x >= 0 ? "成长" : "价值"}。
      </div>
    </div>
  );
}

const heat = (v, cap) => v == null ? "transparent"
  : `color-mix(in srgb, ${v > 0 ? "var(--up)" : "var(--down)"} ${
      Math.round(Math.min(Math.abs(v) / cap, 1) * 62)}%, transparent)`;

function HeatCell({ v, cap, digits = 1 }) {
  return (
    <td className="num" style={{ background: heat(v, cap), fontSize: 10.5 }}>
      {v == null ? "—" : v.toFixed(digits)}
    </td>
  );
}

function BreadthHeatmap({ rows }) {
  const sorted = rows.slice().sort((a, b) =>
    (a.sector || "").localeCompare(b.sector || "") ||
    a.symbol.localeCompare(b.symbol));
  return (
    <div className="panel">
      <div className="sect">
        宽度热力图 <small>行=标的（按行业排）· 列=时间尺度与结构位 ·
        色深∝幅度（各列上限 3/5/10/20/10%）</small>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="mtable" style={{ minWidth: 620 }}>
          <thead>
            <tr>
              <th>标的</th><th>行业</th>
              <th style={{ textAlign: "right" }}>1d</th>
              <th style={{ textAlign: "right" }}>5d</th>
              <th style={{ textAlign: "right" }}>21d</th>
              <th style={{ textAlign: "right" }}>63d</th>
              <th style={{ textAlign: "right" }}>RS21</th>
              <th style={{ textAlign: "right" }}>RSI</th>
              <th>MA50</th><th>MA200</th><th>阶段</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.symbol}>
                <td style={{ fontWeight: 600 }}>
                  <a className="mono" href={`#/market/${r.symbol}`}
                     style={{ fontSize: 11 }}>
                    {r.symbol}
                  </a>
                </td>
                <td style={{ fontSize: 10.5, color: "var(--ink-4)" }}>
                  {r.sector || "—"}
                </td>
                <HeatCell v={r.ret_1d} cap={3} />
                <HeatCell v={r.ret_5d} cap={5} />
                <HeatCell v={r.ret_21d} cap={10} />
                <HeatCell v={r.ret_63d} cap={20} />
                <HeatCell v={r.rs_21d} cap={10} />
                <td className="num" style={{ fontSize: 10.5,
                      background: r.rsi > 70
                        ? "color-mix(in srgb, var(--stance-p2) 40%, transparent)"
                        : r.rsi < 30
                        ? "color-mix(in srgb, var(--stance-n2) 40%, transparent)"
                        : "transparent" }}>
                  {r.rsi?.toFixed(0) ?? "—"}
                </td>
                {[r.above50, r.above200].map((b, i) => (
                  <td key={i} style={{ textAlign: "center" }}>
                    <span style={{ color: b == null ? "var(--ink-4)"
                          : b ? "var(--up)" : "var(--down)", fontSize: 10 }}>
                      {b == null ? "—" : "●"}
                    </span>
                  </td>
                ))}
                <td className="mono" style={{ fontSize: 10.5, textAlign: "center",
                      background: r.stage === "2"
                        ? "color-mix(in srgb, var(--up) 25%, transparent)"
                        : r.stage === "4"
                        ? "color-mix(in srgb, var(--down) 25%, transparent)"
                        : "transparent" }}>
                  {r.stage ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SectorRS({ sectors }) {
  const max = Math.max(...sectors.map((s) => Math.abs(s.rs_21d)), 1);
  return (
    <div className="panel">
      <div className="sect">
        行业 vs SPY <small>21 日相对强弱；进攻性行业（科技/可选消费）领涨
        与防守性（公用/必需消费）领涨，定性完全不同</small>
      </div>
      <div style={{ padding: "8px 16px 12px" }}>
        {sectors.map((s) => (
          <div key={s.sym} style={{ display: "flex", alignItems: "center",
                                    gap: 6, margin: "4px 0" }}>
            <span style={{ width: 62, fontSize: 11, color: "var(--ink-2)" }}>
              {s.label}
            </span>
            <div style={{ flex: 1, display: "flex" }}>
              <div style={{ width: "50%", display: "flex",
                            justifyContent: "flex-end" }}>
                {s.rs_21d < 0 && (
                  <span style={{ height: 9, borderRadius: 2,
                    background: "var(--down)",
                    width: `${(Math.abs(s.rs_21d) / max) * 100}%` }} />
                )}
              </div>
              <div style={{ width: "50%", display: "flex" }}>
                {s.rs_21d > 0 && (
                  <span style={{ height: 9, borderRadius: 2,
                    background: "var(--up)",
                    width: `${(s.rs_21d / max) * 100}%` }} />
                )}
              </div>
            </div>
            <span className="mono" style={{ width: 46, fontSize: 10.5,
                  textAlign: "right", color: pctColor(s.rs_21d) }}>
              {pct(s.rs_21d)}
            </span>
            <span className="mono" style={{ width: 58, fontSize: 9.5,
                  textAlign: "right", color: pctColor(s.rs_5d) }}>
              5d {pct(s.rs_5d)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

const RATIO_META = {
  copper_gold: ["铜金比", "增长交易 vs 避险——上行 = 经济乐观压过恐惧"],
  hyg_ief: ["HYG / IEF", "信用风险胃口——上行 = 垃圾债跑赢国债，risk-on"],
  vix_term: ["VIX / VIX3M", "恐慌期限结构——>1 倒挂 = 为眼前几周付恐慌溢价"],
};

function Ratios({ ratios }) {
  return (
    <div className="panel panel-pad">
      <div className="uplabel" style={{ marginBottom: 10 }}>
        三条跨资产比值 · 60 日
      </div>
      {Object.entries(ratios).map(([k, xs]) => {
        const meta = RATIO_META[k] || [k, ""];
        const chg = (xs[xs.length - 1] / xs[Math.max(0, xs.length - 22)] - 1) * 100;
        return (
          <div key={k} style={{ margin: "8px 0" }}>
            <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "baseline" }}>
              <span style={{ fontSize: 11.5, fontWeight: 600 }}>{meta[0]}</span>
              <span className="mono" style={{ fontSize: 10.5 }}>
                {xs[xs.length - 1].toFixed(3)}{" "}
                <span style={{ color: pctColor(chg) }}>21d {pct(chg)}</span>
              </span>
            </div>
            <Spark xs={xs} h={26}
                   color={chg > 0 ? "var(--up)" : chg < 0 ? "var(--down)"
                          : "var(--ink-4)"} />
            <div style={{ fontSize: 10, color: "var(--ink-4)" }}>{meta[1]}</div>
          </div>
        );
      })}
    </div>
  );
}

// ── 个股屏（原有面板） ──────────────────────────────────────

function CoAxis({ seriesList }) {
  const W = 700, H = 190, PADR = 62;
  const all = seriesList.flatMap((s) => s.norm);
  const lo = Math.min(...all), hi = Math.max(...all);
  const y = (v) => H - ((v - lo) / (hi - lo || 1)) * (H - 20) - 10;
  const n = Math.max(...seriesList.map((s) => s.norm.length));
  const x = (i) => (i / (n - 1 || 1)) * (W - 8) + 4;
  return (
    <div style={{ position: "relative", paddingRight: PADR }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", display: "block" }}>
        {[lo, (lo + hi) / 2, hi].map((v, i) => (
          <line key={i} x1={0} x2={W} y1={y(v)} y2={y(v)} stroke="var(--hairline)" />
        ))}
        {seriesList.map((s, si) => (
          <polyline key={s.symbol} fill="none" stroke={LINE_STYLES[si % 4]}
                    strokeWidth={si === 0 ? 1.8 : 1.3}
                    points={s.norm.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
        ))}
      </svg>
      <div style={{ position: "absolute", right: 0, top: 0, bottom: 0,
                    width: PADR - 6, fontFamily: "var(--mono)", fontSize: 10.5 }}>
        {seriesList.map((s, si) => {
          const last = s.norm[s.norm.length - 1];
          return (
            <div key={s.symbol}
                 style={{ position: "absolute", color: LINE_STYLES[si % 4],
                          fontWeight: 600,
                          top: `${((hi - last) / (hi - lo || 1)) * 85}%` }}>
              {s.symbol} {last.toFixed(0)}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function Market() {
  const [ov, setOv] = useState(null);
  const [bars, setBars] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api("/api/market/overview").then(async (d) => {
      setOv(d);
      const pick = ["SPY", ...d.rows
        .filter((r) => r.symbol !== "SPY" && r.rs_21d != null)
        .sort((a, b) => Math.abs(b.rs_21d) - Math.abs(a.rs_21d))
        .slice(0, 3).map((r) => r.symbol)];
      const bs = await Promise.all(
        pick.map((s) => api(`/api/market/${s}/bars?days=30`).catch(() => null)));
      setBars(bs.filter(Boolean).filter((b) => b.bars?.length > 2));
    }).catch(setErr);
  }, []);

  if (err) return <Empty>加载失败：{String(err)}</Empty>;
  if (!ov) return <div className="page"><PanelSkeleton rows={12} /></div>;

  const b = ov.breadth?.breadth || ov.breadth || {};
  const rows = ov.rows || [];
  const mac = ov.macro;
  const seriesList = (bars || []).map((x) => {
    const base = x.bars[0].c || 1;
    return { symbol: x.symbol, norm: x.bars.map((v) => (v.c / base) * 100) };
  });

  // 阶段分布
  const stages = {};
  for (const r of rows) {
    const s = Array.isArray(r.stage) ? r.stage[0] : r.stage;
    if (s != null) stages[String(s)] = (stages[String(s)] || 0) + 1;
  }
  // 21d 收益分布直方图（2.5% 一档）
  const rets = rows.map((r) => r.ret_21d).filter((v) => v != null);
  const bins = {};
  for (const v of rets) {
    const k = Math.max(-6, Math.min(6, Math.round(v / 2.5)));
    bins[k] = (bins[k] || 0) + 1;
  }
  const binKeys = Object.keys(bins).map(Number).sort((a, c) => a - c);
  const binMax = Math.max(...Object.values(bins), 1);

  // RS 排行
  const rsRows = rows.filter((r) => r.rs_21d != null)
    .sort((a, c) => c.rs_21d - a.rs_21d);
  const rsMax = Math.max(...rsRows.map((r) => Math.abs(r.rs_21d)), 1);

  // 背离榜：叙事 30d 分位 vs |21d 收益| 分位
  const n30s = rows.map((r) => ov.narrative[r.symbol]?.docs_30d ?? 0);
  const absRets = rows.map((r) => Math.abs(r.ret_21d ?? 0));
  const div = rows.map((r) => {
    const nRank = rank(n30s, ov.narrative[r.symbol]?.docs_30d ?? 0);
    const pRank = rank(absRets, Math.abs(r.ret_21d ?? 0));
    return { ...r, nRank, pRank, div: Math.round((nRank - pRank) * 100) };
  }).sort((a, c) => Math.abs(c.div) - Math.abs(a.div)).slice(0, 8);

  return (
    <div className="page">
      {/* ═══ 第一屏：宏观 ═══ */}
      <Hdr>宏观 · 跨资产与全球{mac?.as_of ? ` · ${mac.as_of}` : ""}</Hdr>
      {mac ? (
        <>
          <div style={{ display: "grid", gap: 14,
                        gridTemplateColumns: "1.1fr 1fr 1.15fr" }}>
            {mac.compass && <RiskCompass compass={mac.compass} />}
            {mac.curve && <YieldCurve curve={mac.curve} />}
            <NarrativeGauge gauge={ov.gauge} />
          </div>
          {mac.relay?.length > 0 && <Relay relay={mac.relay} />}
          {mac.band?.length > 0 && <MacroBand band={mac.band} />}
        </>
      ) : (
        <Empty>宏观层待市场阶段首跑后生成（工作日盘后）</Empty>
      )}

      {/* ═══ 第二屏：结构 ═══ */}
      <Hdr>结构 · 市场内部</Hdr>
      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr 1fr", gap: 14 }}>
        <div className="panel panel-pad">
          <div className="uplabel" style={{ marginBottom: 12 }}>
            市场体温计 · {b.n ?? rows.length} 标的
          </div>
          <div className="wrapnums" style={{ gap: 22 }}>
            <BigNum label="站上 MA50"
                    value={b.pct_above_ma50 != null ? `${Math.round(b.pct_above_ma50)}%` : "—"}
                    color={b.pct_above_ma50 >= 50 ? "var(--up)" : "var(--down)"} />
            <BigNum label="站上 MA200"
                    value={b.pct_above_ma200 != null ? `${Math.round(b.pct_above_ma200)}%` : "—"}
                    color={b.pct_above_ma200 >= 50 ? "var(--up)" : "var(--down)"} />
            <BigNum label="涨 / 跌"
                    value={`${b.advancers ?? "—"} / ${b.decliners ?? "—"}`} />
            <BigNum label="平均 RSI"
                    value={b.avg_rsi != null ? b.avg_rsi.toFixed(0) : "—"}
                    sub={b.avg_rsi > 70 ? "整体超买" : b.avg_rsi < 30 ? "整体超卖" : "中性区"} />
            {b.avg_hv20 != null && (
              <BigNum label="平均 HV20" value={`${b.avg_hv20.toFixed(0)}%`} />
            )}
          </div>
        </div>
        <div className="panel panel-pad">
          <div className="uplabel" style={{ marginBottom: 10 }}>Weinstein 阶段分布</div>
          {["1", "2", "3", "4"].map((s) => (
            <div key={s} style={{ display: "flex", alignItems: "center",
                                  gap: 8, margin: "6px 0" }}>
              <span className="mono" style={{ width: 60, fontSize: 10.5,
                                              color: "var(--label)" }}>
                阶段 {s}
              </span>
              <span style={{ height: 10, borderRadius: 2,
                background: s === "2" ? "var(--up)" : s === "4" ? "var(--down)"
                            : "var(--dens-4)",
                width: `${((stages[s] || 0) / Math.max(1, rows.length)) * 100}%` }} />
              <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-4)" }}>
                {stages[s] || 0}
              </span>
            </div>
          ))}
          <div style={{ fontSize: 10.5, color: "var(--ink-4)", marginTop: 6 }}>
            1 筑底 · 2 上升 · 3 筑顶 · 4 下降
          </div>
        </div>
        <div className="panel panel-pad">
          <div className="uplabel" style={{ marginBottom: 10 }}>21 日收益分布 · 2.5%/档</div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 90 }}>
            {binKeys.map((k) => (
              <div key={k} style={{ flex: 1, display: "flex",
                                    flexDirection: "column", alignItems: "center" }}>
                <div style={{ width: "100%", borderRadius: 2,
                              height: `${(bins[k] / binMax) * 80}px`,
                              background: k > 0 ? "var(--up)"
                                        : k < 0 ? "var(--down)" : "var(--dens-3)" }} />
                <span className="mono" style={{ fontSize: 8.5, color: "var(--ink-4)",
                                                marginTop: 3 }}>
                  {k * 2.5}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {mac?.breadth_hist && mac?.style_trail?.length > 1 ? (
        <div className="mkgrid">
          <BreadthHistory hist={mac.breadth_hist} />
          <StyleQuadrant trail={mac.style_trail} />
        </div>
      ) : mac?.breadth_hist ? (
        <BreadthHistory hist={mac.breadth_hist} />
      ) : null}

      <BreadthHeatmap rows={rows} />

      {mac?.sectors?.length > 0 && (
        <div className="mkgrid">
          <SectorRS sectors={mac.sectors} />
          {mac.ratios && Object.keys(mac.ratios).length > 0 && (
            <Ratios ratios={mac.ratios} />
          )}
        </div>
      )}

      {/* ═══ 第三屏：个股 ═══ */}
      <Hdr>个股 · 关注清单</Hdr>
      <div className="mkgrid">
        <div className="panel panel-pad">
          <div className="uplabel" style={{ marginBottom: 10 }}>
            30 日 · 归一化基期 100 · 单轴 · SPY + |RS| 最大三标的
          </div>
          {seriesList.length > 1
            ? <CoAxis seriesList={seriesList} />
            : <Empty>行情序列不足</Empty>}
        </div>
        <div className="panel">
          <div className="sect">相对强弱 <small>rs_21d，vs SPY 同窗收益差</small></div>
          <div style={{ padding: "8px 16px 12px" }}>
            {rsRows.map((r) => (
              <div key={r.symbol} style={{ display: "flex", alignItems: "center",
                                           gap: 6, margin: "4px 0" }}>
                <a className="mono" href={`#/market/${r.symbol}`}
                   style={{ width: 46, fontSize: 11, fontWeight: 600 }}>
                  {r.symbol}
                </a>
                <div style={{ flex: 1, display: "flex" }}>
                  <div style={{ width: "50%", display: "flex",
                                justifyContent: "flex-end" }}>
                    {r.rs_21d < 0 && (
                      <span style={{ height: 9, borderRadius: 2,
                        background: "var(--down)",
                        width: `${(Math.abs(r.rs_21d) / rsMax) * 100}%` }} />
                    )}
                  </div>
                  <div style={{ width: "50%", display: "flex" }}>
                    {r.rs_21d > 0 && (
                      <span style={{ height: 9, borderRadius: 2,
                        background: "var(--up)",
                        width: `${(r.rs_21d / rsMax) * 100}%` }} />
                    )}
                  </div>
                </div>
                <span className="mono" style={{ width: 48, fontSize: 10.5,
                      textAlign: "right", color: pctColor(r.rs_21d) }}>
                  {pct(r.rs_21d)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 背离榜 + RSI 条带 */}
      <div className="mkgrid">
        <div className="panel">
          <div className="sect">
            叙事 × 价格背离 <small>左=30日新闻提及分位 右=|21日收益|分位；差值大=叙事与价格脱节</small>
          </div>
          <div style={{ padding: "8px 16px 12px" }}>
            {div.map((r) => (
              <div key={r.symbol} style={{ display: "flex", alignItems: "center",
                                           gap: 8, margin: "5px 0" }}>
                <a className="mono" href={`#/market/${r.symbol}`}
                   style={{ width: 46, fontSize: 11, fontWeight: 600 }}>
                  {r.symbol}
                </a>
                <span className="mono" style={{ width: 52, fontSize: 10.5,
                      color: Math.abs(r.div) > 40 ? "var(--mark)" : "var(--ink-4)",
                      fontWeight: 600 }}>
                  背离 {r.div > 0 ? "+" : ""}{r.div}
                </span>
                <div className="mirror" style={{ flex: 1 }}>
                  <div className="l" style={{ flex: 1 }}>
                    <i style={{ background: "var(--dens-5)",
                                width: `${r.nRank * 100}%` }} />
                  </div>
                  <span style={{ width: 1, background: "var(--line)",
                                 height: 12 }} />
                  <div className="r" style={{ flex: 1 }}>
                    <i style={{ background: "var(--dens-3)",
                                width: `${r.pRank * 100}%` }} />
                  </div>
                </div>
                <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)",
                                                width: 90, textAlign: "right" }}>
                  {ov.narrative[r.symbol]?.docs_30d ?? 0} 篇 · {pct(r.ret_21d)}
                </span>
              </div>
            ))}
            <div style={{ fontSize: 10.5, color: "var(--ink-4)", marginTop: 8 }}>
              正背离大：新闻在喊、价格没动；负背离大：价格动了、没人在讲——
              两头都值得点进关联故事找原因。
            </div>
          </div>
        </div>
        <div className="panel">
          <div className="sect">RSI 条带 <small>&lt;30 超卖 · &gt;70 超买</small></div>
          <div style={{ padding: "34px 20px 16px" }}>
            <div style={{ position: "relative", height: 26, borderRadius: 4,
                background: "linear-gradient(90deg, var(--stance-n2) 0 30%, var(--dens-1) 30% 70%, var(--stance-p2) 70% 100%)",
                opacity: 0.85 }}>
              {rows.filter((r) => r.rsi != null).map((r, i) => (
                <a key={r.symbol} href={`#/market/${r.symbol}`}
                   title={`${r.symbol} RSI ${r.rsi.toFixed(0)}`}
                   style={{ position: "absolute", left: `${r.rsi}%`,
                            top: i % 2 ? -16 : 30,
                            transform: "translateX(-50%)",
                            fontFamily: "var(--mono)", fontSize: 9,
                            color: "var(--ink)", fontWeight: 600,
                            whiteSpace: "nowrap" }}>
                  {r.symbol}
                </a>
              ))}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between",
                          marginTop: 22, fontFamily: "var(--mono)", fontSize: 9.5,
                          color: "var(--ink-4)" }}>
              <span>0</span><span>30</span><span>50</span><span>70</span><span>100</span>
            </div>
          </div>
        </div>
      </div>

      {/* 标的表 */}
      <div className="panel">
        <div className="sect">标的表 <small>{rows.length} 个关注标的</small></div>
        <div style={{ overflowX: "auto" }}>
          <table className="mtable">
            <thead>
              <tr>
                <th>标的</th><th>行业</th>
                <th style={{ textAlign: "right" }}>最新</th>
                <th style={{ textAlign: "right" }}>1d</th>
                <th style={{ textAlign: "right" }}>21d</th>
                <th style={{ textAlign: "right" }}>RS21</th>
                <th style={{ textAlign: "right" }}>RSI</th>
                <th style={{ textAlign: "right" }}>ATR%</th>
                <th>阶段</th><th>叙事7d</th><th>关联故事</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const na = ov.narrative[r.symbol] || {};
                const stage = Array.isArray(r.stage) ? r.stage.join(" ") : r.stage;
                return (
                  <tr key={r.symbol} className={na.story ? "" : "dim"}>
                    <td style={{ fontWeight: 600 }}>
                      <a href={`#/market/${r.symbol}`}
                         style={{ borderBottom: "1px dotted var(--ink-4)" }}>
                        {r.symbol}
                      </a>
                    </td>
                    <td style={{ fontSize: 11.5, color: "var(--ink-3)" }}>
                      {r.sector || "—"}
                    </td>
                    <td className="num">{r.close != null ? (+r.close).toFixed(2) : "—"}</td>
                    <td className="num" style={{ color: pctColor(r.ret_1d) }}>
                      {pct(r.ret_1d)}
                    </td>
                    <td className="num" style={{ fontWeight: 600,
                                                 color: pctColor(r.ret_21d) }}>
                      {pct(r.ret_21d)}
                    </td>
                    <td className="num" style={{ color: pctColor(r.rs_21d) }}>
                      {pct(r.rs_21d)}
                    </td>
                    <td className="num"
                        style={{ color: r.rsi > 70 ? "var(--stance-p2)"
                                 : r.rsi < 30 ? "var(--stance-n2)" : undefined }}>
                      {r.rsi?.toFixed(0) ?? "—"}
                    </td>
                    <td className="num">{r.atr_pct?.toFixed(1) ?? "—"}</td>
                    <td className="mono" style={{ fontSize: 10.5 }}>{stage ?? "—"}</td>
                    <td className="num">{na.docs_7d ?? 0}</td>
                    <td style={{ fontSize: 12, fontFamily: "var(--serif)" }}>
                      {na.story
                        ? <a href={`#/story/${na.story.id}`}>
                            {na.story.title.slice(0, 24)}…
                          </a>
                        : <span style={{ color: "var(--ink-4)" }}>无活跃关联故事</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* 雷达 */}
      {ov.radar.length > 0 && (
        <div className="panel">
          <div className="sect">
            雷达命中 <small>{ov.radar_day} · 全集扫描 top {ov.radar.length}，
            尚未入关注清单的信号</small>
          </div>
          <div style={{ padding: "8px 16px 12px", display: "grid",
                        gridTemplateColumns: "repeat(2, 1fr)", gap: "4px 24px" }}>
            {ov.radar.map((h) => (
              <div key={h.symbol} style={{ display: "flex", gap: 8,
                                           alignItems: "baseline",
                                           padding: "4px 0" }}>
                <span className="mono" style={{ fontWeight: 600, fontSize: 12,
                                                width: 52 }}>
                  {h.symbol}
                </span>
                <span className="mono" style={{ fontSize: 10.5, color: "var(--ink)",
                                                width: 34 }}>
                  {h.score}
                </span>
                <span style={{ fontSize: 11.5, color: "var(--ink-3)", flex: 1 }}>
                  {h.name || ""}{h.sector ? ` · ${h.sector}` : ""}
                  {Array.isArray(h.reasons) && h.reasons.length > 0 &&
                    ` · ${h.reasons.slice(0, 2).join("、")}`}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>
        技术观察与自家新闻图谱统计，自动生成，不构成投资建议。
        叙事强度按公司名匹配实体，口径为启发式。罗盘与比值判据阈值均已明示。
      </div>
    </div>
  );
}
