// 周复盘（handoff 4c）：看系统自己这周干得怎么样。
// 生命周期大数（story_events）+ 成本（/api/admin/tokens）+ 涨落榜 + 悬置问题。
import { useEffect, useState } from "react";
import { ago, api, fmtVel } from "../api.js";
import { Empty, PanelSkeleton } from "../components.jsx";

export default function Wrap() {
  const [shape, setShape] = useState(null);
  const [tokens, setTokens] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api("/api/weekly-shape").then(setShape).catch(setErr);
    api("/api/admin/tokens").then(setTokens).catch(() => {});
  }, []);

  if (err) return <Empty>加载失败：{String(err)}</Empty>;
  if (!shape) return <div className="page"><PanelSkeleton rows={10} /></div>;

  const lc = shape.lifecycle || {};
  const weekTok = (tokens?.by_purpose || []).reduce(
    (a, p) => a + (p.input_week || 0) + (p.output_week || 0), 0);

  return (
    <div className="page">
      <div style={{ display: "grid", gridTemplateColumns: "1.15fr 1fr 1fr", gap: 14 }}>
        <div className="panel panel-pad">
          <div className="uplabel" style={{ marginBottom: 12 }}>故事生命周期 · 7 日</div>
          <div className="wrapnums">
            {[["created", "新建"], ["absorbed", "吸收"],
              ["dormant", "转沉寂"], ["merged", "合并"]].map(([k, label]) => (
              <div key={k}>
                <div className="n">{lc[k] ?? 0}</div>
                <div className="l">{label}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="panel panel-pad">
          <div className="uplabel" style={{ marginBottom: 12 }}>悬置最久的未解问题</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {shape.open_questions.slice(0, 4).map((q, i) => (
              <a className="qitem" key={i} href={`#/story/${q.story_id}`}
                 style={{ textDecoration: "none" }}>
                <div className="q" style={{ fontSize: 13.5 }}>{q.question}</div>
                <div className="src">{q.story_title} · 悬置 {ago(q.since)}</div>
              </a>
            ))}
            {!shape.open_questions.length && <Empty>没有悬置的问题</Empty>}
          </div>
        </div>
        <div className="panel panel-pad">
          <div className="uplabel" style={{ marginBottom: 12 }}>本周 tokens</div>
          <div className="bignum">{(weekTok / 1e6).toFixed(1)}M</div>
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
            {(tokens?.by_purpose || []).slice(0, 6).map((p) => {
              const t = (p.input_week || 0) + (p.output_week || 0);
              const max = Math.max(1, ...(tokens.by_purpose || []).map(
                (x) => (x.input_week || 0) + (x.output_week || 0)));
              return (
                <div key={p.purpose} style={{ display: "flex",
                     alignItems: "center", gap: 8 }}>
                  <span className="mono" style={{ width: 80, fontSize: 10.5,
                                                  color: "var(--label)" }}>
                    {p.purpose}
                  </span>
                  <span style={{ height: 8, borderRadius: 2,
                                 background: "var(--dens-5)",
                                 width: `${(t / max) * 100}%` }} />
                  <span className="mono" style={{ fontSize: 10,
                                                  color: "var(--ink-4)" }}>
                    {(t / 1e6).toFixed(2)}M
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <div className="panel">
          <div className="sect">涨 <small>velocity 正向</small></div>
          {shape.risers.filter((s) => (s.scalars?.velocity ?? 0) > 0).map((s) => (
            <a className="srow key" key={s.id} href={`#/story/${s.id}`}>
              <span className="t">{s.title}</span>
              <span className="m">
                <span className="vel">{fmtVel(s.scalars?.velocity)}</span>
                <span>{s.scalars?.docs}d</span>
                <span>{ago(s.updated_at)}</span>
              </span>
            </a>
          ))}
        </div>
        <div className="panel">
          <div className="sect">落 <small>velocity 负向</small></div>
          {shape.fallers.filter((s) => (s.scalars?.velocity ?? 0) < 0).map((s) => (
            <a className="srow rest" key={s.id} href={`#/story/${s.id}`}>
              <span className="t">{s.title}</span>
              <span className="m">
                <span>{fmtVel(s.scalars?.velocity)}</span>
                <span>{s.scalars?.docs}d</span>
              </span>
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}
