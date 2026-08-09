// 市场快照仪表盘：宽度体温计 / 阶段分布 / 收益分布 / 共轴时间带 /
// RS 排行 / 叙事×价格背离（自家新闻图谱独有）/ RSI 条带 / 标的表 / 雷达。
// 数据一次来自 /api/market/overview + bars。技术观察，不构成投资建议。
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

function rank(vals, v) {
  if (v == null || !vals.length) return 0;
  return vals.filter((x) => x <= v).length / vals.length;
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
      {/* 体温计 / 阶段 / 收益分布 */}
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

      {/* 共轴 + RS 排行 */}
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
        叙事强度按公司名匹配实体，口径为启发式。
      </div>
    </div>
  );
}
