// 板块页 5b：首页放走的密度全落这里 —— 三栏板块头（综述 / 14日报道量 / 簇清单）
// + 左栏按簇分组的完整清单（今日无更新的簇折叠）+ 右栏 未解问题 / 高频实体 / 信源。
import { useEffect, useState } from "react";
import { api } from "../api.js";
import {
  Breadcrumbs, DensityBand, DomainDot, Empty, PanelSkeleton, StoryRow,
} from "../components.jsx";

const DOMAIN_COLOR = {
  "政治": "#9E2B25", "地缘政治": "#B5761E", "经济": "#1E7A63",
  "金融": "#1E7A63", "科技": "#6A4BB5", "business": "#2F5D8C",
};
const DENS = ["#efeeea", "#e0ded8", "#c9c6be", "#aba79d", "#8b8779",
  "#6b675a", "#4a473c", "#2c2a22"];

// 簇面板：簇头（名→5c + 统计）+ 簇内三档故事。今日无更新默认折叠成一条。
function ClusterPanel({ cluster }) {
  const st = cluster.stories;
  const noToday = cluster.today_updates === 0;
  const [open, setOpen] = useState(!noToday);
  const meta = `${st.length} 故事 · 跨度 ${cluster.span_days}d · ` +
    (cluster.today_updates ? `今日 ${cluster.today_updates} 条更新` : "今日无更新");
  return (
    <div className="panel" style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10,
             padding: "13px 20px", borderBottom: open ? "1px solid var(--line-soft)"
             : "none" }}>
        <a href={`#/node/${cluster.node.id}`}
           style={{ fontFamily: "var(--sans, 'IBM Plex Sans')", fontSize: 11,
             fontWeight: 600, letterSpacing: ".08em", textTransform: "uppercase",
             color: cluster.today_updates ? "var(--ink)" : "var(--ink-3)",
             textDecoration: "none" }}>{cluster.node.name}</a>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-4)" }}>
          {meta}</span>
        {noToday && (
          <a onClick={(e) => { e.preventDefault(); setOpen(!open); }} href="#"
             style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 11,
               color: "var(--label)", textDecoration: "none" }}>
            {open ? "折叠 ⌃" : "展开 ⌄"}</a>)}
      </div>
      {open && st.map((s, i) => (
        <StoryRow key={s.id} story={s}
                  tier={s.today && i === 0 ? "key" : "rest"} />
      ))}
    </div>
  );
}

export default function Section({ domain }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setD(null);
    api(`/api/sections/${encodeURIComponent(domain)}`).then(setD).catch(setErr);
  }, [domain]);

  if (err) return <Empty>板块加载失败：{String(err)}</Empty>;
  if (!d)
    return (
      <div className="page">
        <PanelSkeleton rows={4} />
        <div className="storygrid"><PanelSkeleton rows={12} /><PanelSkeleton rows={8} /></div>
      </div>
    );

  const color = DOMAIN_COLOR[domain] || "#63605A";
  const dg = d.digest;
  const maxSrc = Math.max(...(d.sources || []).map((s) => s.count), 1);

  return (
    <div className="page">
      <Breadcrumbs parts={[{ label: "头版", href: "#/" }, { label: domain }]} />

      {/* 板块头部：综述 | 14日报道量 | 簇清单 */}
      <div className="panel" style={{ display: "flex", gap: 24,
             padding: "20px 24px 18px", marginBottom: 14 }}>
        <div style={{ flex: 1, maxWidth: 860 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <DomainDot color={color} size={7} />
            <h1 style={{ fontFamily: "Newsreader, serif", fontSize: 26,
                   fontWeight: 600, margin: 0 }}>{domain}</h1>
            <span className="mono" style={{ fontSize: 11, color: "var(--ink-4)" }}>
              {d.stats.stories} 在追故事 · {d.stats.clusters} 簇</span>
          </div>
          {dg && (dg.text?.length ? (
            <p style={{ fontFamily: "Newsreader, serif", fontSize: 17,
                   lineHeight: 1.68, color: "var(--ink-2)", margin: "12px 0 0",
                   textWrap: "pretty" }}>
              {dg.text.map((s, i) => <span key={i}>{s.text} </span>)}</p>
          ) : (
            <p style={{ fontFamily: "Newsreader, serif", fontSize: 15,
                   fontStyle: "italic", color: "var(--ink-4)", margin: "12px 0 0" }}>
              {dg.theme}</p>))}
        </div>
        <div style={{ flex: "0 0 210px", borderLeft: "1px solid var(--line-soft)",
               paddingLeft: 20 }}>
          <div className="uplabel" style={{ marginBottom: 8 }}>本板块 14 日报道量</div>
          <DensityBand series={d.density_14d} height={26} />
          <div className="mono" style={{ fontSize: 11, color: "var(--ink-3)",
                 marginTop: 8 }}>
            今日 {d.stats.docs_today} 篇 / {d.stats.sources} 源
            {d.stats.docs_delta_pct != null &&
              ` · ${d.stats.docs_delta_pct >= 0 ? "▲" : "▼"}${Math.abs(d.stats.docs_delta_pct)}%`}
          </div>
        </div>
        <div style={{ flex: "0 0 230px", borderLeft: "1px solid var(--line-soft)",
               paddingLeft: 20 }}>
          <div className="uplabel" style={{ marginBottom: 8 }}>簇</div>
          {d.clusters.slice(0, 7).map((c) => (
            <a key={c.node.id} href={`#/node/${c.node.id}`}
               style={{ display: "flex", justifyContent: "space-between",
                 gap: 8, padding: "4px 0", textDecoration: "none" }}>
              <span style={{ fontFamily: "Newsreader, serif", fontSize: 13.5,
                     color: c.today_updates ? "var(--ink)" : "var(--ink-3)",
                     fontWeight: c.today_updates ? 500 : 400 }}>{c.node.name}</span>
              <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)",
                     whiteSpace: "nowrap" }}>{c.stories.length} · {c.span_days}d</span>
            </a>
          ))}
        </div>
      </div>

      {/* 主体：左 按簇分组清单 | 右 未解问题 / 高频实体 / 信源 */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 14 }}>
        <div>
          {d.clusters.map((c) => <ClusterPanel key={c.node.id} cluster={c} />)}
          {d.standalone.length > 0 && (
            <div className="panel">
              <div className="sect">未成簇 <small>{d.standalone.length} 条</small></div>
              {d.standalone.map((s) => (
                <StoryRow key={s.id} story={s} tier="rest" />
              ))}
            </div>
          )}
          {!d.clusters.length && !d.standalone.length &&
            <Empty>本板块暂无活跃故事</Empty>}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="panel">
            <div className="sect">未解问题 <small>本板块存量 {d.questions.length} 条</small></div>
            <div style={{ padding: "4px 18px 12px" }}>
              {d.questions.slice(0, 12).map((q, i) => (
                <a key={i} href={`#/story/${q.story_id}`}
                   style={{ display: "block", padding: "8px 0",
                     borderLeft: "2px solid var(--line)", paddingLeft: 12,
                     marginBottom: 2, textDecoration: "none",
                     borderTop: i ? "1px solid var(--row-line)" : "none" }}>
                  <div style={{ fontFamily: "Newsreader, serif", fontSize: 14,
                         color: q.today ? "var(--ink)" : "var(--ink-2)",
                         lineHeight: 1.4, textWrap: "pretty" }}>{q.question}</div>
                  <div className="mono" style={{ fontSize: 10, color: "var(--ink-4)",
                         marginTop: 3 }}>
                    {q.today && "今日 · "}{q.story_title.slice(0, 22)}</div>
                </a>
              ))}
              {!d.questions.length && <Empty>本板块暂无未解问题</Empty>}
            </div>
          </div>

          {d.entities.length > 0 && (
            <div className="panel">
              <div className="sect">高频实体 <small>按出现故事数</small></div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6,
                     padding: "4px 18px 14px" }}>
                {d.entities.map((e, i) => (
                  <span key={e.name} style={{ display: "inline-flex",
                    alignItems: "center", gap: 5, background: "var(--chip)",
                    borderRadius: 5, padding: "5px 8px" }}>
                    {i < 2 && <i style={{ width: 6, height: 6, background: "var(--ink)",
                      display: "inline-block" }} />}
                    <span style={{ fontFamily: "Newsreader, serif", fontSize: 13,
                      color: i < 2 ? "var(--ink)" : i < 4 ? "var(--ink-2)" : "var(--ink-3)" }}>
                      {e.name}</span>
                    <span className="mono" style={{ fontSize: 10,
                      color: "var(--ink-4)" }}>{e.count}</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {d.sources.length > 0 && (
            <div className="panel">
              <div className="sect">本板块信源 <small>{d.stats.sources} 个 · 按贡献量</small></div>
              <div style={{ padding: "4px 18px 14px" }}>
                {d.sources.map((s) => (
                  <div key={s.name} style={{ display: "flex", alignItems: "center",
                         gap: 8, padding: "4px 0" }}>
                    <span style={{ flex: 1, fontFamily: "Newsreader, serif",
                           fontSize: 13, color: "var(--ink-2)", overflow: "hidden",
                           whiteSpace: "nowrap", textOverflow: "ellipsis" }}>
                      {s.name}</span>
                    <span style={{ flex: "0 0 120px", height: 9, borderRadius: 1,
                           background: `linear-gradient(90deg, ${DENS[Math.min(6, s.tier)]} 0 ${Math.round(s.count / maxSrc * 100)}%, var(--dens-0) ${Math.round(s.count / maxSrc * 100)}%)` }} />
                    <span className="mono" style={{ flex: "0 0 30px", fontSize: 10,
                           color: "var(--ink-4)", textAlign: "right" }}>{s.count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
