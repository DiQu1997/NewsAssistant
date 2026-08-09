// 头版（handoff 2a × redesign-ui §三）：必读三联 + 五列域墙 + 未解问题带。
// 横向扫视的墙 —— 绝不退化成单列（验收清单第 1 条）。
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
      {data.hero.length > 0 && (
        <div className="heror">
          {data.hero.map((s, i) => (
            <HeroCard key={s.id} story={s} big={i === 0} />
          ))}
        </div>
      )}

      <div className="wall">
        {wallByCol.map(({ col, groups, standalone }) => {
          const n = groups.reduce((a, g) => a + g.events.length, 0) +
            standalone.length;
          return (
            <div className="panel wallcol" key={col.label}>
              <div className="colhead">
                <DomainDot color={col.color} />
                <span className="nm">{col.label}</span>
                <span className="ct">
                  {n} · {groups.length} 簇
                </span>
              </div>
              {groups.map((g) => (
                <div key={g.node.id}>
                  <div className="grouphead">
                    <a className="clusterlabel" href={`#/node/${g.node.id}`}
                       title={g.node.hint || ""}>
                      {g.node.name}
                    </a>
                  </div>
                  {g.events.map((s, i) => (
                    <StoryRow key={s.id} story={s}
                              tier={i < 2 && (s.importance ?? 0) >= 3
                                    ? "key" : "rest"} />
                  ))}
                </div>
              ))}
              {standalone.map((s, i) => (
                <StoryRow key={s.id} story={s}
                          tier={i < 2 && (s.importance ?? 0) >= 3
                                ? "key" : "rest"} />
              ))}
              {n === 0 && <Empty>本窗口内该域无活跃故事</Empty>}
            </div>
          );
        })}
      </div>

      {data.open_questions.length > 0 && (
        <div className="panel">
          <div className="sect">
            未解问题 <small>跨故事 · 恒在最后</small>
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
