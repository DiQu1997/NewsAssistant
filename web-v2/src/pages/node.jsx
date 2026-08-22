// 簇页 5c：只放跨故事才成立的东西 —— 共轴时间带、贡献度、共享实体、相邻簇。
// 完整簇综述/主线漂移(三个月轨迹+阈值)需簇级 LLM 阶段,后续补;当前用入簇标准占位。
import { useEffect, useState } from "react";
import { ago, api } from "../api.js";
import {
  Breadcrumbs, DensityBand, Empty, PanelSkeleton, StoryRow,
} from "../components.jsx";

const fdate = (iso) => iso ? iso.slice(5, 10) : "?";

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

  const crumb = [{ label: "头版", href: "#/" }];
  if (n.domains?.length)
    crumb.push({ label: n.domains[0], href: `#/s/${encodeURIComponent(n.domains[0])}` });
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
          <div className="mono" style={{ fontSize: 11, color: "var(--ink-4)",
                 margin: "2px 0 10px" }}>
            {(n.events || []).length} 故事 · {n.rollup?.docs ?? 0} docs（去重）·
            {" "}{n.rollup?.breadth ?? 0} 独立源 · 首次成簇 {fdate(n.created_at)} ·
            活跃 {ago(n.last_active_at)}
          </div>
          {n.hint && (
            <p className="serif" style={{ margin: "0 0 12px", fontSize: 15,
                                          color: "var(--ink-2)" }}>
              入簇标准：{n.hint}
              <span style={{ color: "var(--ink-4)", fontSize: 12 }}>
                （簇综述与主线漂移随簇级综述阶段补上）</span>
            </p>
          )}
          <div className="chipline">
            <span className="chip">重要度 {n.importance ?? "?"}</span>
            {(n.domains || []).map((d) => <span className="chip sm" key={d}>{d}</span>)}
          </div>
        </div>
      </div>

      {/* 共轴时间带：簇内各故事在同一时间轴上的报道密度（严格共轴）*/}
      {n.coaxis?.rows?.length > 0 && (
        <div className="panel" style={{ padding: "14px 18px 16px" }}>
          <div className="uplabel" style={{ marginBottom: 10 }}>
            共轴时间带 · 簇内各故事在同一时间轴上的报道密度 ·
            {" "}{n.coaxis.labels[0]} → {n.coaxis.labels.at(-1)}
          </div>
          {n.coaxis.rows.slice(0, 8).map((r) => (
            <div key={r.story_id} style={{ display: "flex", alignItems: "center",
                   gap: 10, padding: "3px 0" }}>
              <a href={`#/story/${r.story_id}`} style={{ flex: "0 0 190px",
                     fontFamily: "Newsreader, serif", fontSize: 13,
                     color: "var(--ink-2)", overflow: "hidden",
                     whiteSpace: "nowrap", textOverflow: "ellipsis",
                     textDecoration: "none" }}>{r.title}</a>
              <div style={{ flex: 1 }}>
                <DensityBand series={r.series} height={14} />
              </div>
            </div>
          ))}
          <div style={{ display: "flex", justifyContent: "space-between",
                 marginLeft: 200, marginTop: 6 }}>
            {n.coaxis.labels.map((l, i) => (
              <span key={i} className="mono" style={{ fontSize: 9.5,
                     color: "var(--ink-4)" }}>{l}</span>
            ))}
          </div>
        </div>
      )}

      <div className="storygrid">
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {/* 簇内故事：按贡献度（占簇内断言比例）*/}
          <div className="panel">
            <div className="sect">簇内故事
              <small>{(n.events || []).length} 条 · 贡献度=占簇内断言比例</small></div>
            {[...(n.events || [])]
              .sort((a, b) => (b.contribution ?? 0) - (a.contribution ?? 0))
              .map((s, i) => (
                <div key={s.id} style={{ display: "flex", alignItems: "stretch" }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <StoryRow story={s} tier={i < 3 ? "key" : "rest"} />
                  </div>
                  {s.contribution != null && (
                    <span className="mono" style={{ flex: "0 0 auto",
                           alignSelf: "center", fontSize: 10.5,
                           color: s.contribution >= 15 ? "var(--ink)" : "var(--ink-4)",
                           fontWeight: s.contribution >= 15 ? 600 : 400,
                           padding: "0 14px", whiteSpace: "nowrap" }}>
                      贡献 {s.contribution}%</span>
                  )}
                </div>
              ))}
            {!(n.events || []).length && <Empty>该簇暂无直属故事</Empty>}
          </div>

          <div className="panel">
            <div className="sect">合流时间线 <small>各故事按时间合并</small></div>
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
                <Empty>子故事尚未生成时间线（synthesize 随周期跑）</Empty>
              )}
            </div>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {(n.shared_entities || []).length > 0 && (
            <div className="panel">
              <div className="sect">共享实体 <small>出现在 ≥2 个故事</small></div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6,
                     padding: "4px 18px 14px" }}>
                {n.shared_entities.map((e, i) => (
                  <span key={e.name} style={{ display: "inline-flex",
                    alignItems: "center", gap: 5, background: "var(--chip)",
                    borderRadius: 5, padding: "5px 8px" }}>
                    {i < 2 && <i style={{ width: 6, height: 6,
                      background: "var(--ink)", display: "inline-block" }} />}
                    <span style={{ fontFamily: "Newsreader, serif", fontSize: 13,
                      color: i < 2 ? "var(--ink)" : "var(--ink-2)" }}>{e.name}</span>
                    <span className="mono" style={{ fontSize: 10,
                      color: "var(--ink-4)" }}>{e.stories} 故事</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {(n.siblings || []).length > 0 && (
            <div className="panel">
              <div className="sect">相邻簇 <small>共享父节点</small></div>
              {n.siblings.map((s) => (
                <a className="srow rest" key={s.id} href={`#/node/${s.id}`}>
                  <span className="t">{s.name}</span>
                  <span className="m"><span>重要度 {s.importance ?? "?"}</span></span>
                </a>
              ))}
            </div>
          )}

          {(n.children_nodes || []).length > 0 && (
            <div className="panel">
              <div className="sect">子节点 <small>{n.children_nodes.length} 个</small></div>
              {n.children_nodes.map((c) => (
                <a className="srow rest" key={c.id} href={`#/node/${c.id}`}>
                  <span className="t">{c.name}</span>
                  <span className="m"><span>{ago(c.last_active_at)}</span></span>
                </a>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
