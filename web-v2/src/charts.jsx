// 事件层图元库（docs/redesign-facts.md）。全部纯 SVG，零图表库。
//
// 研究结论落成的硬规矩（改之前先看 docs）：
// - 直接标注，不用图例；标注层比图型更重要（Amanda Cox）
// - 静态、滚动即可读完；关键信息绝不藏进 hover（Archie Tse 第 2 条）
// - 条形/面积必须从零起；折线不必（Dona Wong）
// - 圆的面积编码用 √value 定半径 —— 用 value 定半径会让感知量级虚增 58%
// - 华夫格重复单位图形，绝不缩放单个图形；单位键与精确数字都要印出来
// - 泳道里 end 为空的事件画点，绝不画成条 —— 那是在虚构持续时间
// - 蜂群图的纵轴是防重叠的假坐标，所以纵轴必须不存在
// - 争议数字：各口径并列，差额自带名字，绝不取平均
import { useId } from "react";

const SERIES = ["#2F5D8C", "#B0403A", "#1E7A63", "#B5761E", "#6A4BB5"];
const fmt = (v, d) =>
  v == null ? "—"
  : Math.abs(v) >= 1e8 ? (v / 1e8).toFixed(2) + "亿"
  : Math.abs(v) >= 1e4 ? (v / 1e4).toFixed(1) + "万"
  // 小数不能被抹掉：6.5 显示成 7 就是在改数据
  : v.toLocaleString("zh-CN", {
      maximumFractionDigits: d ?? (Number.isInteger(v) ? 0 : 1) });

// 标签避让：同值的条目标签会精确叠在一起（斜率图最容易触发）。
// 按 y 排序后逐个下推，保证最小间距。
function declutter(entries, minGap = 12) {
  const s = [...entries].sort((a, b) => a.y - b.y);
  for (let i = 1; i < s.length; i++) {
    if (s[i].y - s[i - 1].y < minGap) s[i].y = s[i - 1].y + minGap;
  }
  return s;
}

// ── 通用外壳：标题即发现 + 单位 + 口径注 ─────────────────────
function Frame({ view, children }) {
  return (
    <figure className="viz">
      <figcaption>
        <span className="viz-intent">{view.intent}</span>
        <h4>{view.title}</h4>
      </figcaption>
      {children}
      <div className="viz-foot">
        {view.unit && <span className="viz-unit">单位：{view.unit}</span>}
        {view.note && <span>{view.note}</span>}
      </div>
    </figure>
  );
}

function Annots({ items }) {
  if (!items?.length) return null;
  return (
    <ul className="viz-annots">
      {items.map((a, i) => (
        <li key={i}>
          <b>{a.at}</b>
          {a.text}
        </li>
      ))}
    </ul>
  );
}

// ── 1. 关键数字盘（含争议口径三数并列） ──────────────────────
// 官方值与估计值是同级字段，不是正文加脚注；差额有自己的名字。
function DisputedFact({ f }) {
  const ests = f.estimates || [];
  const lo = Math.min(...ests.map((e) => e.value));
  const hi = Math.max(...ests.map((e) => e.value));
  return (
    <div className="fact fact-disputed">
      <div className="fact-label">
        {f.label}
        <span className="fact-flag">口径分歧</span>
      </div>
      <div className="fact-ests">
        {ests.map((e, i) => (
          <div key={i} className="fact-est">
            <div className="fact-val">
              {fmt(e.value)}
              {f.unit && <i>{f.unit}</i>}
            </div>
            <div className="fact-src">{e.source}</div>
            {e.method && <div className="fact-method">{e.method}</div>}
          </div>
        ))}
      </div>
      {hi > lo && (
        <div className="fact-gap">
          <span className="fact-gap-name">{f.gap_label || "两者差额"}</span>
          <span className="mono">{fmt(hi - lo)}{f.unit}</span>
        </div>
      )}
      {f.scope_excludes && (
        <div className="fact-excl">不含：{f.scope_excludes}</div>
      )}
      {f.as_of && <div className="fact-asof">截至 {f.as_of}</div>}
    </div>
  );
}

function SimpleFact({ f }) {
  if (f.kind === "unknown") {
    return (
      <div className="fact fact-unknown">
        <div className="fact-label">{f.label}</div>
        <div className="fact-val fact-none">尚无可引用数字</div>
      </div>
    );
  }
  return (
    <div className="fact">
      <div className="fact-label">{f.label}</div>
      <div className="fact-val">
        {fmt(f.value)}
        {f.unit && <i>{f.unit}</i>}
      </div>
      {f.scope_excludes && (
        <div className="fact-excl">不含：{f.scope_excludes}</div>
      )}
      {f.as_of && <div className="fact-asof">截至 {f.as_of}</div>}
    </div>
  );
}

function Numbers({ view, facts }) {
  const byKey = Object.fromEntries((facts || []).map((f) => [f.key, f]));
  const picked = (view.fact_keys || []).map((k) => byKey[k]).filter(Boolean);
  const extra = (view.items || []).map((i) => ({
    key: i.label, label: i.label, kind: "single",
    value: i.value, unit: view.unit,
  }));
  const all = [...picked, ...extra];
  if (!all.length) return null;
  return (
    <Frame view={view}>
      <div className="fact-row">
        {all.map((f) =>
          f.kind === "disputed"
            ? <DisputedFact key={f.key} f={f} />
            : <SimpleFact key={f.key} f={f} />)}
      </div>
      <Annots items={view.annotations} />
    </Frame>
  );
}

// ── 2. 折线 + 常态基准带 ────────────────────────────────────
// 观测线与基准线之间那块阴影就是故事（超额死亡的语法）。
function LineBaseline({ view }) {
  const pts = view.points || [];
  const W = 640, H = 200, PT = 16, PB = 26, PL = 44, PR = 12;
  const ys = pts.map((p) => p.y);
  const base = view.baseline;
  const lo = Math.min(...ys, base ?? Infinity);
  const hi = Math.max(...ys, base ?? -Infinity);
  const pad = (hi - lo) * 0.12 || 1;
  const y = (v) =>
    H - PB - ((v - (lo - pad)) / (hi + pad - (lo - pad) || 1)) * (H - PT - PB);
  const x = (i) => PL + (i / (pts.length - 1 || 1)) * (W - PL - PR);
  const line = pts.map((p, i) => `${x(i)},${y(p.y)}`).join(" ");
  const area = base != null
    ? `${line} ${x(pts.length - 1)},${y(base)} ${x(0)},${y(base)}`
    : null;
  const gid = useId();
  return (
    <Frame view={view}>
      <svg viewBox={`0 0 ${W} ${H}`} className="viz-svg" role="img">
        {[lo, (lo + hi) / 2, hi].map((v, i) => (
          <g key={i}>
            <line x1={PL} x2={W - PR} y1={y(v)} y2={y(v)} stroke="var(--hairline)" />
            <text x={PL - 6} y={y(v) + 3} textAnchor="end" className="viz-tick">
              {fmt(v)}
            </text>
          </g>
        ))}
        {area && (
          <polygon points={area} fill={`url(#${gid})`} opacity="0.5" />
        )}
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--down)" stopOpacity="0.35" />
            <stop offset="100%" stopColor="var(--down)" stopOpacity="0.05" />
          </linearGradient>
        </defs>
        {base != null && (
          <>
            <line x1={PL} x2={W - PR} y1={y(base)} y2={y(base)}
                  stroke="var(--ink-3)" strokeDasharray="5 4" strokeWidth="1.2" />
            {/* 基准标签靠左：右端留给末值标签，两者同侧会撞 */}
            <text x={PL + 6} y={y(base) - 5} className="viz-tick">
              {view.baseline_label || "常态基准"} {fmt(base)}
            </text>
          </>
        )}
        <polyline points={line} fill="none" stroke={SERIES[0]} strokeWidth="2" />
        {pts.map((p, i) => (
          <circle key={i} cx={x(i)} cy={y(p.y)} r="2.4" fill={SERIES[0]} />
        ))}
        {[0, pts.length - 1].map((i) => (
          <text key={i} x={x(i)} y={H - 8}
                textAnchor={i === 0 ? "start" : "end"} className="viz-tick">
            {pts[i]?.x}
          </text>
        ))}
        <text x={x(pts.length - 1)} y={y(pts[pts.length - 1].y) - 8}
              textAnchor="end" className="viz-endlabel" fill={SERIES[0]}>
          {fmt(pts[pts.length - 1].y)}
        </text>
      </svg>
      <Annots items={view.annotations} />
    </Frame>
  );
}

// ── 3. 日柱 + 滚动均线 ──────────────────────────────────────
// 柱是原始值（含上报噪声），线是均值。累计值会抹掉好消息，所以默认画日增。
function BarsRolling({ view }) {
  const pts = view.points || [];
  const W = 640, H = 190, PB = 26, PL = 44, PR = 12, PT = 14;
  const hi = Math.max(...pts.map((p) => p.y), 1);
  const y = (v) => H - PB - (v / hi) * (H - PT - PB);
  const bw = (W - PL - PR) / pts.length;
  const win = Math.min(7, Math.max(3, Math.floor(pts.length / 3)));
  const roll = pts.map((_, i) => {
    if (i < win - 1) return null;
    const s = pts.slice(i - win + 1, i + 1).reduce((a, p) => a + p.y, 0);
    return s / win;
  });
  return (
    <Frame view={view}>
      <svg viewBox={`0 0 ${W} ${H}`} className="viz-svg" role="img">
        {[hi / 2, hi].map((v, i) => (
          <g key={i}>
            <line x1={PL} x2={W - PR} y1={y(v)} y2={y(v)} stroke="var(--hairline)" />
            <text x={PL - 6} y={y(v) + 3} textAnchor="end" className="viz-tick">
              {fmt(v)}
            </text>
          </g>
        ))}
        {pts.map((p, i) => (
          <rect key={i} x={PL + i * bw + bw * 0.15} y={y(p.y)}
                width={bw * 0.7} height={Math.max(H - PB - y(p.y), 0)}
                fill="var(--dens-2)" />
        ))}
        <polyline fill="none" stroke={SERIES[1]} strokeWidth="2"
                  points={roll.map((v, i) => v == null ? null
                    : `${PL + i * bw + bw / 2},${y(v)}`).filter(Boolean).join(" ")} />
        {[0, pts.length - 1].map((i) => (
          <text key={i} x={PL + i * bw + bw / 2} y={H - 8}
                textAnchor={i === 0 ? "start" : "end"} className="viz-tick">
            {pts[i]?.x}
          </text>
        ))}
      </svg>
      <div className="viz-key">
        <span><i className="sw" style={{ background: "var(--dens-2)" }} />当日值</span>
        <span><i className="sw" style={{ background: SERIES[1] }} />{win} 期均线</span>
      </div>
      <Annots items={view.annotations} />
    </Frame>
  );
}

// ── 4. 泳道时间线（多方并行；新闻图表里的头号主力） ──────────
function Swimlane({ view }) {
  const lanes = view.lanes || [];
  const all = lanes.flatMap((l) => (l.events || []).flatMap(
    (e) => [e.start, e.end].filter(Boolean)));
  const uniq = [...new Set(all)].sort();
  const pos = (t) => {
    const i = uniq.indexOf(t);
    return i < 0 ? 0 : (i / (uniq.length - 1 || 1)) * 100;
  };
  return (
    <Frame view={view}>
      <div className="swim">
        <div className="swim-axis">
          {uniq.length > 1 && [uniq[0], uniq[uniq.length - 1]].map((t, i) => (
            <span key={i} className="mono" style={{
              position: "absolute", left: `${i ? 100 : 0}%`,
              transform: i ? "translateX(-100%)" : "none",
            }}>{t}</span>
          ))}
        </div>
        {lanes.map((l, li) => (
          <div key={li} className="swim-lane">
            <div className="swim-actor">{l.actor}</div>
            <div className="swim-track">
              {(l.events || []).map((e, ei) => {
                const a = pos(e.start);
                // end 为空 = 瞬时事件，画点。画成条就是在虚构持续时间。
                const isSpan = !!e.end && e.end !== e.start;
                const b = isSpan ? pos(e.end) : a;
                return isSpan ? (
                  <span key={ei} className="swim-bar" title={e.label}
                        style={{ left: `${a}%`, width: `${Math.max(b - a, 1.5)}%`,
                                 background: SERIES[li % SERIES.length] }}>
                    <b>{e.label}</b>
                  </span>
                ) : (
                  <span key={ei} className="swim-dot"
                        style={{ left: `${a}%`,
                                 borderColor: SERIES[li % SERIES.length] }}>
                    <b>{e.label}</b>
                  </span>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <div className="viz-key">
        <span><i className="sw sw-bar" />有持续时间</span>
        <span><i className="sw sw-dot" />瞬时事件</span>
      </div>
      <Annots items={view.annotations} />
    </Frame>
  );
}

// ── 5. 华夫格（人形单位；每 N 个里有几个） ───────────────────
const PERSON = "M5,6.2 C2.7,6.2 1.5,7.6 1.5,9.6 L1.5,13.7 L8.5,13.7 L8.5,9.6 "
  + "C8.5,7.6 7.3,6.2 5,6.2 Z";

function Waffle({ view }) {
  const each = view.unit_each && view.unit_each > 0 ? view.unit_each : 1;
  const items = (view.items || []).filter((i) => i.value > 0);
  const cells = items.flatMap((it, gi) =>
    Array.from({ length: Math.round(it.value / each) }, () => gi));
  const COLS = 20, S = 15;
  const rows = Math.ceil(cells.length / COLS);
  const person = view.unit_icon !== "square";
  return (
    <Frame view={view}>
      <svg viewBox={`0 0 ${COLS * S} ${Math.max(rows, 1) * S}`}
           className="viz-svg" style={{ maxHeight: 220 }} role="img">
        {cells.map((gi, i) => {
          const cx = (i % COLS) * S, cy = Math.floor(i / COLS) * S;
          const fill = SERIES[gi % SERIES.length];
          return person ? (
            <g key={i} transform={`translate(${cx + 2},${cy + 0.5})`}>
              <circle cx="5" cy="3" r="2.3" fill={fill} />
              <path d={PERSON} fill={fill} />
            </g>
          ) : (
            <rect key={i} x={cx + 2} y={cy + 1} width={S - 4} height={S - 4}
                  rx="1.5" fill={fill} />
          );
        })}
      </svg>
      <div className="viz-key">
        {items.map((it, i) => (
          <span key={i}>
            <i className="sw" style={{ background: SERIES[i % SERIES.length] }} />
            {it.label} <b className="mono">{fmt(it.value)}</b>{view.unit}
          </span>
        ))}
      </div>
      {/* 单位键与精确数字都要印出来：这种图型必然取整 */}
      <div className="viz-scale">
        1 {person ? "个人形" : "个方块"} = {fmt(each)} {view.unit}
      </div>
      <Annots items={view.annotations} />
    </Frame>
  );
}

// ── 6. 实体×实体矩阵 ────────────────────────────────────────
function Matrix({ view }) {
  const { rows = [], cols = [], cells = [] } = view.matrix || {};
  const at = {};
  for (const c of cells) at[`${c.r} ${c.c}`] = c.v;
  const vals = cells.map((c) => c.v);
  const hi = Math.max(...vals.map(Math.abs), 1);
  return (
    <Frame view={view}>
      <div className="viz-scroll">
        <table className="viz-matrix">
          <thead>
            <tr>
              <th />
              {cols.map((c) => <th key={c}>{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r}>
                <th>{r}</th>
                {cols.map((c) => {
                  const v = at[`${r} ${c}`];
                  return (
                    <td key={c} className="mono" style={{
                      background: v == null ? "transparent"
                        : `color-mix(in srgb, ${v < 0 ? "var(--up)" : "var(--down)"} ${
                            Math.round((Math.abs(v) / hi) * 62)}%, transparent)`,
                    }}>
                      {v == null ? "—" : fmt(v, 1)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Annots items={view.annotations} />
    </Frame>
  );
}

// ── 7. 斜率图（恰好两个时点，多主体，同一刻度） ─────────────
function Slope({ view }) {
  const items = (view.items || []).filter((i) => i.value2 != null);
  const [L, R] = view.x_labels || ["前", "后"];
  const W = 760, H = 250, PT = 24, PB = 24, PX = 150;
  const all = items.flatMap((i) => [i.value, i.value2]);
  const lo = Math.min(...all), hi = Math.max(...all);
  const y = (v) => H - PB - ((v - lo) / (hi - lo || 1)) * (H - PT - PB);
  return (
    <Frame view={view}>
      <svg viewBox={`0 0 ${W} ${H}`} className="viz-svg" role="img">
        <text x={PX} y={14} textAnchor="middle" className="viz-tick">{L}</text>
        <text x={W - PX} y={14} textAnchor="middle" className="viz-tick">{R}</text>
        {items.map((it, i) => {
          const up = it.value2 >= it.value;
          const col = up ? "var(--up)" : "var(--down)";
          return (
            <g key={i}>
              <line x1={PX} y1={y(it.value)} x2={W - PX} y2={y(it.value2)}
                    stroke={col} strokeWidth="1.6" opacity="0.85" />
              <circle cx={PX} cy={y(it.value)} r="3" fill={col} />
              <circle cx={W - PX} cy={y(it.value2)} r="3" fill={col} />
            </g>
          );
        })}
        {/* 标签独立于连线绘制，同值时下推避让 */}
        {declutter(items.map((it) => ({ ...it, y: y(it.value) }))).map((it, i) => (
          <text key={i} x={PX - 8} y={it.y + 3.5} textAnchor="end"
                className="viz-slopelabel">
            {it.label} {fmt(it.value)}
          </text>
        ))}
        {declutter(items.map((it) => ({ ...it, y: y(it.value2) }))).map((it, i) => (
          <text key={i} x={W - PX + 8} y={it.y + 3.5} className="viz-slopelabel">
            {fmt(it.value2)}
          </text>
        ))}
      </svg>
      <Annots items={view.annotations} />
    </Frame>
  );
}

// ── 8. 哑铃图（差距即长度，排序即排名） ─────────────────────
function Dumbbell({ view }) {
  const items = (view.items || []).filter((i) => i.value2 != null);
  const all = items.flatMap((i) => [i.value, i.value2]);
  const lo = Math.min(...all, 0), hi = Math.max(...all);
  const pc = (v) => ((v - lo) / (hi - lo || 1)) * 100;
  const [L, R] = view.x_labels || ["起", "止"];
  return (
    <Frame view={view}>
      <div className="dumb">
        {items.map((it, i) => (
          <div key={i} className="dumb-row">
            <span className="dumb-label">{it.label}</span>
            <span className="dumb-track">
              <i className="dumb-bar" style={{
                left: `${Math.min(pc(it.value), pc(it.value2))}%`,
                width: `${Math.abs(pc(it.value2) - pc(it.value))}%`,
              }} />
              <i className="dumb-pt a" style={{ left: `${pc(it.value)}%` }} />
              <i className="dumb-pt b" style={{ left: `${pc(it.value2)}%` }} />
            </span>
            <span className="dumb-val mono">
              {fmt(it.value)} → {fmt(it.value2)}
            </span>
          </div>
        ))}
      </div>
      <div className="viz-key">
        <span><i className="sw sw-a" />{L}</span>
        <span><i className="sw sw-b" />{R}</span>
      </div>
      <Annots items={view.annotations} />
    </Frame>
  );
}

// ── 9. 排序条（从零起） ─────────────────────────────────────
function Bars({ view }) {
  const items = view.items || [];
  const hi = Math.max(...items.map((i) => Math.abs(i.value)), 1);
  const neg = items.some((i) => i.value < 0);
  return (
    <Frame view={view}>
      <div className="barlist">
        {items.map((it, i) => (
          <div key={i} className="bar-row">
            <span className="bar-label">{it.label}</span>
            {neg ? (
              <span className="bar-track diverge">
                <span className="half l">
                  {it.value < 0 && <i style={{
                    width: `${(Math.abs(it.value) / hi) * 100}%`,
                    background: "var(--down)" }} />}
                </span>
                <span className="half r">
                  {it.value > 0 && <i style={{
                    width: `${(it.value / hi) * 100}%`,
                    background: "var(--up)" }} />}
                </span>
              </span>
            ) : (
              <span className="bar-track">
                <i style={{ width: `${(it.value / hi) * 100}%`,
                            background: SERIES[0] }} />
              </span>
            )}
            <span className="bar-val mono">{fmt(it.value, 1)}</span>
          </div>
        ))}
      </div>
      <Annots items={view.annotations} />
    </Frame>
  );
}

// ── 10. 堆叠贡献（总量由什么构成） ──────────────────────────
function Stacked({ view }) {
  const items = view.items || [];
  const total = items.reduce((a, i) => a + Math.max(i.value, 0), 0) || 1;
  // 按条目上色而非按 group：同组两项同色会在条上糊成一片，
  // 而图例是逐条目列的，两者必须对得上
  return (
    <Frame view={view}>
      <div className="stackbar">
        {items.map((it, i) => (
          <span key={i} style={{
            width: `${(Math.max(it.value, 0) / total) * 100}%`,
            background: SERIES[i % SERIES.length],
          }} title={`${it.label} ${fmt(it.value)}`} />
        ))}
      </div>
      <div className="viz-key">
        {items.map((it, i) => (
          <span key={i}>
            <i className="sw" style={{ background: SERIES[i % SERIES.length] }} />
            {it.label} <b className="mono">{fmt(it.value)}</b>
            <em className="mono"> {((it.value / total) * 100).toFixed(0)}%</em>
          </span>
        ))}
      </div>
      <Annots items={view.annotations} />
    </Frame>
  );
}

// ── 11. 蜂群图（一个点一个主体；纵轴不存在） ────────────────
function Beeswarm({ view }) {
  const items = view.items || [];
  const W = 640, H = 130, PL = 16, PR = 16, MID = H / 2;
  const vals = items.map((i) => i.value);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const x = (v) => PL + ((v - lo) / (hi - lo || 1)) * (W - PL - PR);
  // 简易蜂群排布：按值排序后遇到拥挤就上下交替错开
  const placed = [];
  for (const it of [...items].sort((a, b) => a.value - b.value)) {
    const px = x(it.value);
    let k = 0;
    while (placed.some((p) => Math.abs(p.px - px) < 7
      && Math.abs(p.oy - (k % 2 ? -1 : 1) * Math.ceil(k / 2) * 7) < 6)) k++;
    placed.push({ ...it, px, oy: (k % 2 ? -1 : 1) * Math.ceil(k / 2) * 7 });
  }
  const marked = new Set((view.annotations || []).map((a) => a.at));
  return (
    <Frame view={view}>
      <svg viewBox={`0 0 ${W} ${H}`} className="viz-svg" role="img">
        <line x1={PL} x2={W - PR} y1={MID + 26} y2={MID + 26}
              stroke="var(--line)" />
        {[lo, (lo + hi) / 2, hi].map((v, i) => (
          <text key={i} x={x(v)} y={MID + 40} textAnchor="middle"
                className="viz-tick">{fmt(v, 1)}</text>
        ))}
        {placed.map((p, i) => (
          <g key={i}>
            <circle cx={p.px} cy={MID + p.oy} r={marked.has(p.label) ? 5 : 3.2}
                    fill={marked.has(p.label) ? "var(--mark)" : "var(--dens-4)"}
                    opacity={marked.has(p.label) ? 1 : 0.75} />
            {marked.has(p.label) && (
              <text x={p.px} y={MID + p.oy - 9} textAnchor="middle"
                    className="viz-endlabel" fill="var(--mark)">
                {p.label}
              </text>
            )}
          </g>
        ))}
      </svg>
      <Annots items={view.annotations} />
    </Frame>
  );
}

// ── 12. 阶段进度 ────────────────────────────────────────────
const STEP_TONE = {
  done: "var(--up)", current: "var(--mark)",
  pending: "var(--dens-2)", failed: "var(--down)",
};
const STEP_CN = { done: "已完成", current: "进行中", pending: "未开始", failed: "已破裂" };

function Stepper({ view }) {
  const steps = view.steps || [];
  return (
    <Frame view={view}>
      <ol className="stepper">
        {steps.map((s, i) => (
          <li key={i}>
            <span className="step-dot" style={{ background: STEP_TONE[s.status] }} />
            {i < steps.length - 1 && (
              <span className="step-line" style={{
                background: s.status === "done" ? "var(--up)" : "var(--line)",
              }} />
            )}
            <div className="step-body">
              <div className="step-label">{s.label}</div>
              <div className="step-meta mono">
                {STEP_CN[s.status] || s.status}{s.at ? ` · ${s.at}` : ""}
              </div>
            </div>
          </li>
        ))}
      </ol>
      <Annots items={view.annotations} />
    </Frame>
  );
}

// ── 13. 修订史（这个数字被改过几次） ────────────────────────
// 我们没有校准过的概率区间可画，但"它自己被上修了几次"是硬事实。
function Revision({ view }) {
  const pts = view.points || [];
  const first = pts[0]?.y, last = pts[pts.length - 1]?.y;
  const hi = Math.max(...pts.map((p) => p.y), 1);
  return (
    <Frame view={view}>
      <div className="revlist">
        {pts.map((p, i) => {
          const prev = i ? pts[i - 1].y : null;
          const d = prev == null ? null : p.y - prev;
          return (
            <div key={i} className="rev-row">
              <span className="rev-x mono">{p.x}</span>
              <span className="rev-track">
                <i style={{ width: `${(p.y / hi) * 100}%` }} />
              </span>
              <span className="rev-val mono">{fmt(p.y)}</span>
              <span className="rev-delta mono" style={{
                color: d > 0 ? "var(--down)" : d < 0 ? "var(--up)" : "var(--ink-4)",
              }}>
                {d == null ? "首次" : d > 0 ? `上修 ${fmt(d)}`
                  : d < 0 ? `下修 ${fmt(-d)}` : "未变"}
              </span>
              {p.source && <span className="rev-src">{p.source}</span>}
            </div>
          );
        })}
      </div>
      {first != null && last != null && first !== last && (
        <div className="rev-sum">
          共 {pts.length} 次发布，累计{last > first ? "上修" : "下修"}{" "}
          <b className="mono">{fmt(Math.abs(last - first))}</b>
          {view.unit}
          （{((Math.abs(last - first) / (first || 1)) * 100).toFixed(0)}%）
        </div>
      )}
      <Annots items={view.annotations} />
    </Frame>
  );
}

// ── 分发 ────────────────────────────────────────────────────
const RENDERERS = {
  numbers: Numbers, line_baseline: LineBaseline, bars_rolling: BarsRolling,
  swimlane: Swimlane, waffle: Waffle, matrix: Matrix, slope: Slope,
  dumbbell: Dumbbell, bars: Bars, stacked: Stacked, beeswarm: Beeswarm,
  stepper: Stepper, revision: Revision,
};

export function EventViews({ views, facts }) {
  const list = (views || []).filter((v) => RENDERERS[v.type]);
  if (!list.length) return null;
  return (
    <div className="vizwrap">
      {list.map((v, i) => {
        const C = RENDERERS[v.type];
        try {
          return <C key={i} view={v} facts={facts} />;
        } catch {
          return null;      // 单张图渲染失败不拖垮整页
        }
      })}
    </div>
  );
}

// 未被任何图引用的事实槽位仍然值得单独展示
export function FactStrip({ facts, views }) {
  const used = new Set((views || []).flatMap((v) => v.fact_keys || []));
  const rest = (facts || []).filter((f) => !used.has(f.key));
  if (!rest.length) return null;
  return (
    <div className="fact-row fact-strip">
      {rest.map((f) =>
        f.kind === "disputed"
          ? <DisputedFact key={f.key} f={f} />
          : <SimpleFact key={f.key} f={f} />)}
    </div>
  );
}
