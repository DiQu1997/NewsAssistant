// 节点页（redesign-ui §四）：导航枢纽，复用 2b 骨架。
// DAG 多父面包屑；子节点组 + 直属 event；合流时间线。不做节点级综述。
import { useEffect, useState } from "react";
import { ago, api } from "../api.js";
import {
  Breadcrumbs, Empty, PanelSkeleton, StoryRow,
} from "../components.jsx";

export default function NodePage({ id }) {
  const [n, setN] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setN(null);
    api(`/api/nodes/${id}`).then(setN).catch(setErr);
  }, [id]);

  if (err) return <Empty>加载失败：{String(err)}</Empty>;
  if (!n)
    return (
      <div className="page">
        <PanelSkeleton rows={3} />
        <div className="storygrid"><PanelSkeleton rows={8} /><PanelSkeleton rows={6} /></div>
      </div>
    );

  const crumb = [{ label: "NewsAssistant", href: "#/" }];
  if (n.domains?.length) crumb.push({ label: n.domains[0] });
  if (n.parents?.length)
    crumb.push({ labels: n.parents.map((p) => ({ label: p.name, href: `#/node/${p.id}` })) });

  return (
    <div className="page">
      <div style={{ display: "flex", alignItems: "center" }}>
        <Breadcrumbs parts={crumb} />
        <span className="chip sm" style={{ marginLeft: "auto" }}>
          node #{n.id} · 活跃 {ago(n.last_active_at)}
        </span>
      </div>

      <div className="panel storyhead">
        <div className="sh-main" style={{ maxWidth: "none", paddingRight: 0 }}>
          <h1>{n.name}</h1>
          {n.hint && (
            <p className="serif" style={{ margin: "0 0 12px", fontSize: 15,
                                          color: "var(--ink-2)" }}>
              入簇标准：{n.hint}
            </p>
          )}
          <div className="chipline">
            <span className="chip">{n.rollup?.events ?? 0} events</span>
            <span className="chip">{n.rollup?.docs ?? 0} docs（去重）</span>
            <span className="chip">{n.rollup?.breadth ?? 0} 独立源</span>
            <span className="chip">重要度 {n.importance ?? "?"}</span>
            {(n.domains || []).map((d) => <span className="chip sm" key={d}>{d}</span>)}
          </div>
        </div>
      </div>

      <div className="storygrid">
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {(n.children_nodes || []).length > 0 && (
            <div className="panel">
              <div className="sect">子节点 <small>{n.children_nodes.length} 个</small></div>
              {n.children_nodes.map((c) => (
                <a className="srow key" key={c.id} href={`#/node/${c.id}`}>
                  <span className="t">{c.name}</span>
                  <span className="m">
                    <span>重要度 {c.importance ?? "?"}</span>
                    <span>{ago(c.last_active_at)}</span>
                    {c.hint && <span style={{ overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.hint}</span>}
                  </span>
                </a>
              ))}
            </div>
          )}
          <div className="panel">
            <div className="sect">事件 <small>{(n.events || []).length} 条，按重要度</small></div>
            {(n.events || []).map((s, i) => (
              <StoryRow key={s.id} story={s} tier={i < 4 ? "key" : "rest"} />
            ))}
            {!(n.events || []).length && <Empty>该节点暂无直属事件</Empty>}
          </div>
        </div>

        <div className="panel">
          <div className="sect">合流时间线 <small>各事件按时间合并</small></div>
          <div className="tl">
            {(n.timeline || []).map((t, i) => (
              <div className="tlitem" key={i}
                   style={{ "--dot": i < 4 ? "var(--ink)" : "var(--dens-3)" }}>
                <div className="ts">{t.when}</div>
                <div className="ev">
                  {t.what}
                  <a href={`#/story/${t.story_id}`}
                     style={{ marginLeft: 6, fontFamily: "var(--mono)",
                              fontSize: 10, color: "var(--ink-4)" }}>
                    → {t.story_title?.slice(0, 18)}
                  </a>
                </div>
              </div>
            ))}
            {!(n.timeline || []).length && (
              <Empty>子事件尚未生成时间线（synthesize 随周期跑）</Empty>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
