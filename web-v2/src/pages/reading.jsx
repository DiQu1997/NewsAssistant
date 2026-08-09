// 阅读板块（handoff 3a）：精读 2 卡 + 四列队列 + 已消化。
// 读时估算当前 API 未提供 —— 按空态原则用重要度（significance）代位并明示，
// 不假装有数据。
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Empty, PanelSkeleton } from "../components.jsx";

const KIND_COLS = [
  { key: "paper", label: "论文", color: "#6A4BB5" },
  { key: "engineering", label: "工程实践", color: "#2F5D8C" },
  { key: "analysis", label: "深度分析", color: "#1E7A63" },
  { key: "release", label: "发布与讨论", color: "#B5761E",
    match: (k) => ["release", "discussion", "blog"].includes(k) },
];

function DeepCard({ it }) {
  const [digest, setDigest] = useState(null);
  useEffect(() => {
    if (it.has_digest)
      api(`/api/reading/${it.id}/digest`).then((d) => setDigest(d.digest)).catch(() => {});
  }, [it.id, it.has_digest]);
  const cells = digest
    ? [
        { label: "主张", text: digest.core_claims?.join("；") || digest.summary, cl: "var(--ink)" },
        { label: "新在哪", text: digest.novelty, cl: "var(--dens-4)" },
        { label: "方法与证据", text: digest.method || digest.evidence, cl: "var(--dens-4)" },
        { label: "存疑", text: digest.caveats, cl: "var(--stance-p2)" },
      ].filter((c) => c.text)
    : [];
  return (
    <div className="panel deepcard">
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <span className="chip sm">{it.kind}</span>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-4)" }}>
          {it.source_name}
        </span>
        <span className="chip sm" style={{ marginLeft: "auto" }}>
          重要度 {it.significance}
        </span>
      </div>
      <h3>{it.title}</h3>
      {it.why_read && (
        <p className="serif" style={{ margin: "2px 0 0", fontSize: 14.5,
                                      lineHeight: 1.55, color: "var(--ink-2)" }}>
          {it.why_read}
        </p>
      )}
      {cells.length > 0 && (
        <div className="digest4">
          {cells.map((c) => (
            <div className="cell" key={c.label} style={{ "--cl": c.cl }}>
              <div className="uplabel">{c.label}</div>
              <p>{String(c.text).slice(0, 260)}</p>
            </div>
          ))}
        </div>
      )}
      <div style={{ marginTop: 12, paddingTop: 10,
                    borderTop: "1px solid var(--line-soft)",
                    display: "flex", alignItems: "center" }}>
        <span className="chipline">
          {(it.tags || []).slice(0, 4).map((t) => (
            <span className="chip sm" key={t}>{t}</span>
          ))}
        </span>
        <a href={it.url} target="_blank" rel="noreferrer"
           style={{ marginLeft: "auto", color: "var(--mark)", fontWeight: 600,
                    fontSize: 12 }}>
          读原文 ↗
        </a>
      </div>
    </div>
  );
}

export default function Reading() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api("/api/reading?days=7").then(setData).catch(setErr);
  }, []);

  if (err) return <Empty>加载失败：{String(err)}</Empty>;
  if (!data)
    return (
      <div className="page">
        <div className="readgrid2"><PanelSkeleton rows={7} /><PanelSkeleton rows={7} /></div>
      </div>
    );

  const items = data.items || [];
  const deep = items.filter((i) => i.significance >= 5).slice(0, 2);
  const deepIds = new Set(deep.map((i) => i.id));
  const queue = items.filter((i) => !deepIds.has(i.id) && !i.has_digest);
  const done = items.filter((i) => !deepIds.has(i.id) && i.has_digest).slice(0, 12);

  const cols = KIND_COLS.map((c) => ({
    ...c,
    items: queue
      .filter((i) => (c.match ? c.match(i.kind) : i.kind === c.key))
      .slice(0, 10),
  }));

  return (
    <div className="page">
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <span className="uplabel">阅读 · 预消化</span>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-4)" }}>
          未读 {queue.length} · 本周 {items.length} · 读时估算待接入（先按重要度）
        </span>
      </div>

      {deep.length > 0 && (
        <div className="readgrid2">
          {deep.map((it) => <DeepCard key={it.id} it={it} />)}
        </div>
      )}

      <div className="readgrid4">
        {cols.map((c) => (
          <div className="panel" key={c.key}>
            <div className="colhead" style={{ display: "flex", gap: 7,
                 alignItems: "center", padding: "12px 14px",
                 borderBottom: "1px solid var(--line-soft)" }}>
              <span className="domdot" style={{ background: c.color }} />
              <span className="serif" style={{ fontWeight: 600, fontSize: 14,
                                               color: "var(--ink)" }}>
                {c.label}
              </span>
              <span className="mono" style={{ marginLeft: "auto", fontSize: 10,
                                              color: "var(--ink-4)" }}>
                {c.items.length}
              </span>
            </div>
            {c.items.map((it) => (
              <a className="rrow" key={it.id} href={it.url} target="_blank"
                 rel="noreferrer">
                <div className="t">{it.title}</div>
                {it.why_read && <div className="one">{it.why_read}</div>}
                <div className="m">
                  <span>重要度 {it.significance}</span>
                  <span>{it.source_name}</span>
                </div>
              </a>
            ))}
            {!c.items.length && <Empty>队列空</Empty>}
          </div>
        ))}
      </div>

      {done.length > 0 && (
        <div className="panel">
          <div className="sect">已消化 <small>{done.length} 篇（已生成阅读版本）</small></div>
          <div style={{ padding: "10px 24px 14px", display: "grid",
                        gridTemplateColumns: "repeat(3, 1fr)", gap: "6px 24px" }}>
            {done.map((it) => (
              <div className="donearow" key={it.id}>
                <span className="d">
                  {(it.published_at || "").slice(5, 10)}
                </span>
                <a className="t" href={it.url} target="_blank" rel="noreferrer">
                  {it.title}
                </a>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
