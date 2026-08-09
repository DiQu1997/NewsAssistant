// 故事详情（handoff 2b）：三栏头部（标量/立场天平/证据层级）→
// 左（综述+宣称墙）/右（时间线+实体+文档）。分歧矩阵数据需按源展开
// 立场，当前 API 以宣称行呈现（宣称墙即分歧的行视图）。
import { useEffect, useRef, useState } from "react";
import { ago, api, fmtVel, spanDays } from "../api.js";
import {
  Breadcrumbs, Empty, PanelSkeleton, StanceStrip, TierBadge,
} from "../components.jsx";

const STANCE_VARS = [
  "var(--stance-n2)", "var(--stance-n1)", "var(--stance-0)",
  "var(--stance-p1)", "var(--stance-p2)",
];

function Balance({ claims }) {
  const counts = [0, 0, 0, 0, 0];
  for (const c of claims) {
    if (c.stance != null) counts[Math.max(-2, Math.min(2, c.stance)) + 2] += 1;
  }
  const total = counts.reduce((a, b) => a + b, 0) || 1;
  return (
    <>
      <div className="uplabel" style={{ marginBottom: 8 }}>立场天平</div>
      <div className="balance">
        {counts.map((n, i) => (
          <i key={i} style={{ flex: Math.max(n / total, 0.04),
                              background: STANCE_VARS[i] }} />
        ))}
      </div>
      <div className="balcounts">
        {counts.map((n, i) => <span key={i}>{i - 2 > 0 ? `+${i - 2}` : i - 2} · {n}</span>)}
      </div>
    </>
  );
}

function TierDist({ docs }) {
  const byTier = {};
  for (const d of docs) byTier[d.evidence_tier] = (byTier[d.evidence_tier] || 0) + 1;
  const tiers = Object.keys(byTier).sort();
  const max = Math.max(...Object.values(byTier), 1);
  const synd = docs.filter((d) => d.syndication_of).length;
  return (
    <>
      <div className="uplabel" style={{ marginBottom: 8 }}>证据层级分布</div>
      {tiers.map((t) => (
        <div className="tierbar" key={t}>
          <TierBadge tier={+t} />
          <span className="bar"
                style={{ width: `${(byTier[t] / max) * 100}%`,
                         maxWidth: 130, background: "var(--dens-5)" }} />
          <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-4)" }}>
            {byTier[t]}
          </span>
        </div>
      ))}
      {synd > 0 && (
        <div className="mono" style={{ fontSize: 10.5, color: "var(--ink-4)", marginTop: 8 }}>
          转述折叠：{docs.length} 篇 → {docs.length - synd} 原发
        </div>
      )}
    </>
  );
}

/** 综述：每句后跟可点的引用码，点击滚动定位宣称墙（不用 scrollIntoView） */
function Summary({ summary, onCite }) {
  if (!summary?.length) return <Empty>尚未合成综述（synthesize 阶段随周期跑）</Empty>;
  return (
    <div className="summary">
      {summary.map((s, i) => (
        <span key={i}>
          {s.text}
          {(s.claim_ids || []).map((c) => (
            <span key={c} className="cite" onClick={() => onCite(c)}>c{c}</span>
          ))}{" "}
        </span>
      ))}
    </div>
  );
}

export default function Story({ id }) {
  const [s, setS] = useState(null);
  const [err, setErr] = useState(null);
  const [hlClaim, setHlClaim] = useState(null);
  const wallRef = useRef(null);

  useEffect(() => {
    setS(null);
    api(`/api/stories/${id}`).then(setS).catch(setErr);
  }, [id]);

  if (err) return <Empty>加载失败：{String(err)}</Empty>;
  if (!s)
    return (
      <div className="page">
        <PanelSkeleton rows={4} />
        <div className="storygrid"><PanelSkeleton rows={10} /><PanelSkeleton rows={8} /></div>
      </div>
    );

  const sc = s.scalars || {};

  function cite(claimId) {
    setHlClaim(claimId);
    const wall = wallRef.current;
    const row = wall?.querySelector(`[data-claim="${claimId}"]`);
    if (wall && row) {
      // handoff 交互契约：容器 scrollTop 计算，不用 scrollIntoView
      const top = row.offsetTop - wall.offsetTop;
      window.scrollTo({ top: wall.getBoundingClientRect().top + scrollY + top - 160,
                        behavior: "smooth" });
    }
  }

  const crumb = [{ label: "NewsAssistant", href: "#/" }];
  if (s.domains?.length) crumb.push({ label: s.domains[0] });
  if (s.nodes?.length)
    crumb.push({ labels: s.nodes.map((n) => ({ label: n.name, href: `#/node/${n.id}` })) });

  // 宣称按分歧度排序：同文本多源立场的方差近似 —— 单条宣称没有跨源标注时
  // 以 |stance| 大的靠前（有立场的信息量高于中性转述）
  const claims = [...(s.claims || [])].sort(
    (a, b) => Math.abs(b.stance ?? 0) - Math.abs(a.stance ?? 0));

  return (
    <div className="page">
      <div style={{ display: "flex", alignItems: "center" }}>
        <Breadcrumbs parts={crumb} />
        <span className="chip sm" style={{ marginLeft: "auto" }}>
          story #{s.id} · {s.state}
          {s.synthesized_at && ` · 已合成 ${ago(s.synthesized_at)}`}
        </span>
      </div>

      <div className="panel storyhead">
        <div className="sh-main">
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {(s.importance ?? 0) >= 4 && <span className="mustread">必读</span>}
            {(s.importance ?? 0) >= 4 && (sc.breadth ?? 0) <= 1 && (
              <span className="unverified">单源未印证</span>
            )}
          </div>
          <h1>{s.title}</h1>
          <div className="chipline">
            <span className="chip">{sc.docs ?? "?"} docs</span>
            <span className="chip">{sc.breadth ?? "?"} 独立源</span>
            <span className="chip"><b>{fmtVel(sc.velocity)}</b></span>
            <span className="chip">stage {sc.stage ?? "?"}</span>
            <span className="chip">一致度 {sc.consensus ?? "?"}</span>
            <span className="chip">重要度 {s.importance ?? "?"}</span>
            <span className="chip">
              跨度 {spanDays(s.created_at, s.updated_at) ?? "?"}d ·
              更新 {ago(s.updated_at)}
            </span>
          </div>
        </div>
        <div className="sh-mid"><Balance claims={s.claims || []} /></div>
        <div className="sh-side"><TierDist docs={s.docs || []} /></div>
      </div>

      <div className="storygrid">
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="panel">
            <div className="sect">综述 <small>每句带 claim 级引用，点编号看宣称原文</small></div>
            <Summary summary={s.summary} onCite={cite} />
          </div>
          <div className="panel" ref={wallRef}>
            <div className="sect">宣称墙 <small>{claims.length} 条，左缘色=立场</small></div>
            {claims.map((c) => (
              <div key={c.id} data-claim={c.id}
                   className={"claimrow" + (Math.abs(c.stance ?? 0) >= 1 ? " key" : "")
                              + (hlClaim === c.id ? " hl" : "")}
                   style={{ borderLeft: `3px solid ${
                     STANCE_VARS[Math.max(-2, Math.min(2, c.stance ?? 0)) + 2]}` }}>
                <span className="cid">c{c.id}</span>
                <span className="tx">{c.text}</span>
                <span className="meta"><span>{c.source}</span></span>
              </div>
            ))}
            {!claims.length && <Empty>还没有宣称——extract 阶段随周期跑</Empty>}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="panel">
            <div className="sect">时间线</div>
            <div className="tl">
              {(s.timeline || []).map((t, i) => (
                <div className="tlitem" key={i}
                     style={{ "--dot": i < 3 ? "var(--ink)" : i < 7
                              ? "var(--dens-4)" : "var(--dens-2)" }}>
                  <div className="ts">{t.at}</div>
                  <div className="ev">{t.text}</div>
                </div>
              ))}
              {!(s.timeline || []).length && <Empty>时间线随综述生成</Empty>}
            </div>
          </div>
          {(s.open_questions || []).length > 0 && (
            <div className="panel">
              <div className="sect">未解问题</div>
              <div style={{ padding: "10px 18px 14px", display: "flex",
                            flexDirection: "column", gap: 10 }}>
                {s.open_questions.map((q, i) => (
                  <div className="qitem" key={i}>
                    <div className="q">{typeof q === "string" ? q : q.text}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="panel">
            <div className="sect">文档 <small>{(s.docs || []).length} 篇</small></div>
            {(s.docs || []).map((d) => (
              <div className="docrow" key={d.id}>
                <TierBadge tier={d.evidence_tier} />
                <a className="t" href={d.url} target="_blank" rel="noreferrer">
                  {d.title || d.url}
                </a>
                <span className="src">
                  {d.source}
                  {d.published_at && ` · ${d.published_at.slice(5, 10)}`}
                  {d.syndication_of ? " · 转述" : " · 原发"}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
