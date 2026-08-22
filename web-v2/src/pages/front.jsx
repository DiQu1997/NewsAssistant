// 头版 5a：报纸头版 —— 唯一头条大卡（带「为何在头版」）+ 刚刚更新流 +
// 今天该知道的第二件事 | 五列板块综述行（每列 1 主 + 2 次）| 今天新问题带。
// 只放最新且最重要的，不是全部故事的索引（验收：板块列不出第 4 条、不出加载更多）。
import { useEffect, useState } from "react";
import { ago, api, fmtVel, spanDays } from "../api.js";
import {
  DensityBand, DomainDot, Empty, MetricLine, PanelSkeleton, StanceStrip,
  StoryRow,
} from "../components.jsx";

// UI 五列：经济+金融并为一列（handoff 的墙就是五列）
const COLS = [
  { label: "政治", domains: ["政治"], color: "#9E2B25" },
  { label: "地缘", domains: ["地缘政治"], color: "#B5761E" },
  { label: "经济·金融", domains: ["经济", "金融"], color: "#1E7A63" },
  { label: "科技", domains: ["科技"], color: "#6A4BB5" },
  { label: "Business", domains: ["business"], color: "#2F5D8C" },
];

function HeroCard({ story, big }) {
  const sc = story.scalars || {};
  const crumbNode = story.nodes?.[0];
  const singleSource = (story.importance ?? 0) >= 4 && (sc.breadth ?? 0) <= 1;
  return (
    <a className={"panel herocard" + (big ? "" : " sub")}
       href={`#/story/${story.id}`} style={{ textDecoration: "none" }}>
      <span className="crumb">
        <span className="mustread">必读</span>
        <span>
          {(story.domains || [])[0] || ""}
          {crumbNode && ` → ${crumbNode.name}`}
        </span>
        {singleSource && <span className="unverified">单源未印证</span>}
        <span style={{ marginLeft: "auto", fontFamily: "var(--mono)",
                       fontSize: 10.5, color: "var(--ink-4)" }}>
          跨度 {spanDays(story.created_at, story.updated_at) ?? "?"}d ·
          更新 {ago(story.updated_at)}
        </span>
      </span>
      <h2>{story.title}</h2>
      {big && story.lede && <p className="lede">{story.lede}</p>}
      {big && story.reason && (
        <div style={{
          display: "flex", gap: 12, alignItems: "baseline",
          background: "var(--panel-alt)", border: "1px solid var(--line-soft)",
          borderRadius: 6, padding: "10px 14px", margin: "10px 0 12px",
        }}>
          <span style={{
            flex: "0 0 auto", fontFamily: "var(--sans, 'IBM Plex Sans')",
            fontSize: 10, fontWeight: 600, letterSpacing: ".12em",
            textTransform: "uppercase", color: "var(--label)",
          }}>为何在头版</span>
          <span style={{
            fontFamily: "Newsreader, serif", fontSize: 14, lineHeight: 1.55,
            color: "var(--ink-2)", textWrap: "pretty",
          }}>{story.reason.text}</span>
        </div>
      )}
      <span className="chipline">
        <span className="chip">{sc.docs ?? "?"} docs</span>
        <span className="chip">{sc.breadth ?? "?"} 独立源</span>
        <span className="chip"><b>{fmtVel(sc.velocity)}</b></span>
        {story.stance && (
          <span className="chip" style={{ display: "flex", gap: 6,
                                          alignItems: "center" }}>
            分歧 <StanceStrip counts={story.stance} card />
          </span>
        )}
      </span>
      {big && story.series && (
        <div>
          <div className="uplabel" style={{ marginBottom: 4 }}>14 日吸收量</div>
          <DensityBand series={story.series} height={13} />
        </div>
      )}
    </a>
  );
}

// 管线进度条：采集→抽取→归编漏斗（近24h）+ V2 字段覆盖率（回填进行时
// 就是回填的实时进度）。30s 轮询，处理中时能看着它走。
function PipelineBar() {
  const [p, setP] = useState(null);
  useEffect(() => {
    let alive = true;
    const load = () => api("/api/pipeline").then((d) => alive && setP(d))
      .catch(() => {});
    load();
    const t = setInterval(load, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (!p) return null;
  const v2pct = p.v2.total ? Math.round((p.v2.done / p.v2.total) * 100) : null;
  const lastIngest = p.stages?.ingest?.finished_at;
  const time = (iso) => iso ? new Date(iso).toLocaleTimeString("zh-CN",
    { hour: "2-digit", minute: "2-digit" }) : "—";
  const Step = ({ label, n, base }) => (
    <span style={{ display: "inline-flex", alignItems: "baseline", gap: 5 }}>
      <span style={{ fontSize: 10.5, color: "var(--ink-4)" }}>{label}</span>
      <span className="mono" style={{ fontSize: 12, fontWeight: 600 }}>{n}</span>
      {base > 0 && n < base && (
        <span className="mono" style={{ fontSize: 9.5, color: "var(--ink-4)" }}>
          {Math.round((n / base) * 100)}%
        </span>
      )}
    </span>
  );
  return (
    <div className="panel" style={{ padding: "7px 14px", display: "flex",
                                    alignItems: "center", gap: 14,
                                    flexWrap: "wrap" }}>
      <span className="uplabel" style={{ fontSize: 10 }}>管线 · 近24h</span>
      <Step label="采集" n={p.fetched} base={0} />
      <span style={{ color: "var(--ink-4)", fontSize: 10 }}>→</span>
      <Step label="保留" n={p.kept} base={p.fetched} />
      {p.off_topic > 0 && (
        <span className="mono" style={{ fontSize: 9.5, color: "var(--ink-4)" }}>
          （筛掉 {p.off_topic}）
        </span>
      )}
      <span style={{ color: "var(--ink-4)", fontSize: 10 }}>→</span>
      <Step label="抽取" n={p.extracted} base={p.kept} />
      <span style={{ color: "var(--ink-4)", fontSize: 10 }}>→</span>
      <Step label="归编" n={p.assigned} base={p.extracted} />
      <span style={{ flex: 1 }} />
      {v2pct != null && (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 10.5, color: "var(--ink-4)" }}>
            V2 字段 72h{v2pct < 100 ? " · 回填中" : ""}
          </span>
          <span style={{ width: 90, height: 7, borderRadius: 4,
                         background: "var(--dens-0)", overflow: "hidden" }}>
            <span style={{ display: "block", height: "100%",
                           width: `${v2pct}%`, borderRadius: 4,
                           background: v2pct < 100 ? "var(--dens-4)"
                                       : "var(--up)" }} />
          </span>
          <span className="mono" style={{ fontSize: 10.5, fontWeight: 600 }}>
            {v2pct}%
          </span>
        </span>
      )}
      <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>
        上次采集 {time(lastIngest)} · {p.ingest_schedule}
      </span>
    </div>
  );
}

const hm = (iso) => iso
  ? new Date(iso).toLocaleTimeString("zh-CN",
      { hour: "2-digit", minute: "2-digit", hour12: false })
  : "";

// 刚刚更新流（5a 右上）：按写入时间倒序，近 6h。写的是这次更新，不是故事简介。
function UpdatesStream({ updates }) {
  return (
    <div className="panel">
      <div className="sect">刚刚更新 <small>按写入时间倒序 · 近 6h</small></div>
      <div style={{ padding: "2px 0 6px" }}>
        {(updates || []).map((u, i) => (
          <a key={u.id} href={`#/story/${u.id}`}
             style={{ display: "flex", gap: 10, alignItems: "baseline",
                      padding: "7px 18px", textDecoration: "none",
                      borderTop: i ? "1px solid var(--row-line)" : "none" }}>
            <span className="mono" style={{ flex: "0 0 36px", fontSize: 10.5,
                   color: "var(--ink-4)", whiteSpace: "nowrap" }}>{hm(u.at)}</span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: "Newsreader, serif",
                     fontSize: i < 2 ? 14.5 : 14, fontWeight: i < 2 ? 500 : 400,
                     color: i < 2 ? "var(--ink)" : "var(--ink-2)",
                     lineHeight: 1.35 }}>{u.title}</div>
              <div className="mono" style={{ fontSize: 10, color: "var(--ink-4)",
                     marginTop: 2 }}>
                {u.domain}{u.new_claims ? ` · +${u.new_claims} 断言` : ""}
              </div>
            </span>
          </a>
        ))}
        {!(updates || []).length && <Empty>近 6h 无写入</Empty>}
      </div>
    </div>
  );
}

// 今天该知道的第二件事（5a 右下）：hero[1] 的紧凑卡。
function SecondThing({ story }) {
  if (!story) return null;
  const sc = story.scalars || {};
  return (
    <a className="panel" href={`#/story/${story.id}`}
       style={{ display: "block", padding: "14px 18px", textDecoration: "none" }}>
      <div className="uplabel" style={{ marginBottom: 6 }}>今天该知道的第二件事</div>
      <div style={{ fontFamily: "Newsreader, serif", fontSize: 19, fontWeight: 600,
             lineHeight: 1.26, color: "var(--ink)", textWrap: "pretty" }}>
        {story.title}</div>
      {story.lede && (
        <p style={{ fontFamily: "Newsreader, serif", fontSize: 14.5,
               lineHeight: 1.55, color: "var(--ink-2)", margin: "8px 0 10px",
               textWrap: "pretty" }}>{story.lede}</p>)}
      <span className="chipline">
        <span className="chip">{sc.docs ?? "?"} docs</span>
        <span className="chip">{sc.breadth ?? "?"} 独立源</span>
        <span className="chip"><b>{fmtVel(sc.velocity)}</b></span>
        {story.stance && (
          <span className="chip" style={{ display: "flex", gap: 6,
                 alignItems: "center" }}>
            分歧 <StanceStrip counts={story.stance} card /></span>)}
      </span>
    </a>
  );
}

// 板块综述列（5a 板块综述行）：一段模型综述 + 1 主 + 2 次 + 进入。
// 纪律：只露 1 主 + 2 次，剩下走板块页 —— 不是一长串（验收第 1 条）。
function SectionColumn({ col, groups, standalone, digest }) {
  const stories = groups.flatMap((g) => g.events).concat(standalone);
  const shown = stories.slice(0, 3);
  const more = Math.max(stories.length - shown.length, 0);
  const enter = `#/s/${encodeURIComponent(col.domains[0])}`;
  return (
    <div className="panel wallcol" style={{ display: "flex",
           flexDirection: "column" }}>
      <div className="colhead">
        <DomainDot color={col.color} />
        <a className="nm" href={enter}
           style={{ textDecoration: "none", color: "inherit" }}>{col.label}</a>
        <span className="ct">
          {digest?.new_claims ? `今日 ${digest.new_claims} 断言`
                              : `${stories.length} 在追`}
        </span>
      </div>
      {digest && (
        <div style={{ fontFamily: "Newsreader, serif", fontSize: 13.5,
               lineHeight: 1.6,
               color: digest.has_new ? "var(--ink-2)" : "var(--ink-4)",
               fontStyle: digest.has_new ? "normal" : "italic",
               padding: "9px 14px 11px", borderBottom: "1px solid var(--hairline)",
               marginBottom: 6, textWrap: "pretty" }}>{digest.theme}</div>
      )}
      {shown.map((s, i) => (
        <StoryRow key={s.id} story={s} tier={i === 0 ? "key" : "rest"} />
      ))}
      {!shown.length && <Empty>本窗口内该域无活跃故事</Empty>}
      <a href={enter} style={{ marginTop: "auto", padding: "10px 14px 12px",
             fontFamily: "var(--mono)", fontSize: 11, color: "var(--label)",
             textDecoration: "none" }}>
        进入{col.label}{more ? ` · 另有 ${more} 条在追` : ""} →
      </a>
    </div>
  );
}

export default function Front({ windowH }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setData(null);
    api(`/api/front?window_hours=${windowH}`).then(setData).catch(setErr);
  }, [windowH]);

  if (err) return <Empty>头版加载失败：{String(err)}</Empty>;
  if (!data)
    return (
      <div className="page">
        <div className="heror">
          <PanelSkeleton rows={6} /><PanelSkeleton rows={4} /><PanelSkeleton rows={4} />
        </div>
        <div className="wall">
          {COLS.map((c) => <PanelSkeleton key={c.label} rows={8} />)}
        </div>
      </div>
    );

  // 合并经济+金融两个后端域到一列
  const wallByCol = COLS.map((col) => {
    const walls = data.walls.filter((w) => col.domains.includes(w.domain));
    const groups = walls.flatMap((w) => w.groups);
    const standalone = walls.flatMap((w) => w.standalone);
    return { col, groups, standalone };
  });

  return (
    <div className="page">
      <PipelineBar />

      {/* 头条区：唯一头条大卡 | 刚刚更新流 + 今天该知道的第二件事 */}
      {data.hero.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "1.62fr 1fr",
               gap: 14, marginBottom: 14 }}>
          <HeroCard story={data.hero[0]} big />
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <UpdatesStream updates={data.updates} />
            <SecondThing story={data.hero[1]} />
          </div>
        </div>
      )}

      {/* 板块综述行：五列，每列一段模型综述 + 1 主 + 2 次 + 进入板块 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)",
             gap: 14, marginBottom: 14 }}>
        {wallByCol.map(({ col, groups, standalone }) => {
          const digest = col.domains
            .map((d) => data.section_digests?.[d])
            .filter(Boolean)
            .sort((a, b) => (b.new_claims || 0) - (a.new_claims || 0))[0];
          return (
            <SectionColumn key={col.label} col={col} groups={groups}
                           standalone={standalone} digest={digest} />
          );
        })}
      </div>

      {/* 今天新出现的问题：仅列今日新增，存量在板块页 */}
      {data.open_questions.length > 0 && (
        <div className="panel">
          <div className="sect">
            今天新出现的问题 <small>仅列今日新增 · 存量在板块页</small>
          </div>
          <div className="qband">
            {data.open_questions.map((q, i) => (
              <a className="qitem" key={i} href={`#/story/${q.story_id}`}
                 style={{ textDecoration: "none" }}>
                <div className="q">{q.question}</div>
                <div className="src">{q.node || q.story_title}</div>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
