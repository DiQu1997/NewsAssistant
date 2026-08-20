// 共享微组件 —— handoff §微组件 的逐项实现。
// 编码轴颜色一律引用 tokens，组件内不出现裸色值。
import { ago, fmtVel } from "./api.js";

const STANCE_VARS = [
  "var(--stance-n2)", "var(--stance-n1)", "var(--stance-0)",
  "var(--stance-p1)", "var(--stance-p2)",
];
const DENS_VARS = [
  "var(--dens-0)", "var(--dens-1)", "var(--dens-2)", "var(--dens-3)",
  "var(--dens-4)", "var(--dens-5)", "var(--dens-6)", "var(--dens-7)",
];
export const TIER_VARS = {
  1: "var(--tier-1)", 2: "var(--tier-2)", 3: "var(--tier-2)",
  4: "var(--tier-2)", 5: "var(--tier-5)", 6: "var(--tier-6)",
  7: "var(--tier-6)",
};

/** 立场微条：5 段 flex，段宽按各档计数取比例。counts=[n-2..n+2] */
export function StanceStrip({ counts, card = false, width }) {
  if (!counts || counts.every((n) => !n)) return null;
  const total = counts.reduce((a, b) => a + b, 0);
  const w = width || (card ? 44 : 26);
  return (
    <span className={"stancestrip" + (card ? " card" : "")}
          style={{ width: w }} title={`立场分布 ${counts.join("/")}`}>
      {counts.map((n, i) => (
        <i key={i} style={{ flex: Math.max(n / total, 0.04),
                            background: STANCE_VARS[i] }} />
      ))}
    </span>
  );
}

/** 14 日密度带：分位分档的单色阶。series=[n,...] */
export function DensityBand({ series, height = 12 }) {
  if (!series || !series.length) return null;
  const max = Math.max(...series, 1);
  return (
    <span className="densband" title={`14 日吸收量 ${series.join("/")}`}>
      {series.map((n, i) => (
        <i key={i}
           style={{ height,
                    background: DENS_VARS[Math.min(7,
                      Math.round((n / max) * 7))] }} />
      ))}
    </span>
  );
}

export function TierBadge({ tier }) {
  if (!tier) return null;
  return (
    <span className="badge" style={{ background: TIER_VARS[tier] || "var(--tier-6)" }}>
      L{tier}
    </span>
  );
}

export function DomainDot({ color }) {
  return <span className="domdot" style={{ background: color }} />;
}

/** 指标行（Mono 10.5px）：跨度/更新/velocity/立场微条 */
export function MetricLine({ story, stance = true }) {
  const sc = story.scalars || {};
  return (
    <span className="m">
      <span>{sc.docs ?? "?"}d</span>
      <span>{sc.breadth ?? "?"}s</span>
      <span className="vel">{fmtVel(sc.velocity)}</span>
      {story.updated_at && <span>{ago(story.updated_at)}</span>}
      {stance && story.stance && (
        <span style={{ marginLeft: "auto" }}>
          <StanceStrip counts={story.stance} />
        </span>
      )}
    </span>
  );
}

/** 两行制故事行。tier: "key" | "rest" */
export function StoryRow({ story, tier = "key" }) {
  return (
    <a className={`srow ${tier}`} href={`#/story/${story.id}`}>
      <span className="t">{story.title}</span>
      <MetricLine story={story} stance={tier === "key"} />
    </a>
  );
}

/** DAG 多父面包屑：属于多个上层时用 · 并列 */
export function Breadcrumbs({ parts }) {
  // parts: [{label, href} | {labels: [{label, href}]}]
  return (
    <div className="crumbrow">
      {parts.map((p, i) => (
        <span key={i} style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {i > 0 && <span style={{ color: "var(--ink-4)" }}>/</span>}
          {p.labels
            ? p.labels.map((l, j) => (
                <span key={j}>
                  {j > 0 && <span style={{ color: "var(--ink-4)" }}> · </span>}
                  <a href={l.href}>{l.label}</a>
                </span>
              ))
            : p.href
              ? <a href={p.href}>{p.label}</a>
              : <span>{p.label}</span>}
        </span>
      ))}
    </div>
  );
}

export function PanelSkeleton({ rows = 5 }) {
  return (
    <div className="panel panel-pad">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skel"
             style={{ height: 14, margin: "10px 0",
                      width: `${90 - (i % 3) * 15}%` }} />
      ))}
    </div>
  );
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>;
}
