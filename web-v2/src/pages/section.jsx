// 板块页 5b（v0：最小可用 —— 板块综述 + 在追故事清单）。
// #4 补全：按簇分组、右栏未解问题 / 高频实体 / 信源栏、排序器。
import { useEffect, useState } from "react";
import { api } from "../api.js";
import {
  Breadcrumbs, DomainDot, Empty, PanelSkeleton, StoryRow,
} from "../components.jsx";

const DOMAIN_COLOR = {
  "政治": "#9E2B25", "地缘政治": "#B5761E", "经济": "#1E7A63",
  "金融": "#1E7A63", "科技": "#6A4BB5", "business": "#2F5D8C",
};

export default function Section({ domain }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setData(null);
    api("/api/front?window_hours=72").then(setData).catch(setErr);
  }, [domain]);

  if (err) return <Empty>板块加载失败：{String(err)}</Empty>;
  if (!data) return <div className="page"><PanelSkeleton rows={10} /></div>;

  const wall = (data.walls || []).find((w) => w.domain === domain);
  const digest = data.section_digests?.[domain];
  const stories = wall
    ? wall.groups.flatMap((g) => g.events).concat(wall.standalone)
    : [];

  return (
    <div className="page">
      <Breadcrumbs parts={[{ label: "头版", href: "#/" }, { label: domain }]} />

      <div className="panel" style={{ padding: "20px 24px 18px", marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <DomainDot color={DOMAIN_COLOR[domain] || "#63605A"} />
          <h1 style={{ fontFamily: "Newsreader, serif", fontSize: 26,
                 fontWeight: 600, margin: 0 }}>{domain}</h1>
          <span className="mono" style={{ fontSize: 11, color: "var(--ink-4)" }}>
            {stories.length} 在追</span>
        </div>
        {digest && (digest.text?.length ? (
          <p style={{ fontFamily: "Newsreader, serif", fontSize: 17,
                 lineHeight: 1.68, color: "var(--ink-2)", margin: "12px 0 0",
                 maxWidth: 900, textWrap: "pretty" }}>
            {digest.text.map((s, i) => <span key={i}>{s.text} </span>)}
          </p>
        ) : (
          <p style={{ fontFamily: "Newsreader, serif", fontSize: 15,
                 fontStyle: "italic", color: "var(--ink-4)", margin: "12px 0 0" }}>
            {digest.theme}</p>
        ))}
      </div>

      <div className="panel">
        <div className="sect">在追故事
          <small>完整版即将上线（含簇分组 / 未解问题 / 信源栏）</small></div>
        {stories.map((s, i) => (
          <StoryRow key={s.id} story={s}
                    tier={i < 3 && (s.importance ?? 0) >= 3 ? "key" : "rest"} />
        ))}
        {!stories.length && <Empty>本板块暂无活跃故事</Empty>}
      </div>
    </div>
  );
}
