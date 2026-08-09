// 每日画报（handoff 4b）：报头大字判断 + 域×小时热力矩阵 + 三栏底部。
// 六页里唯一允许留白的一页。
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Empty, PanelSkeleton } from "../components.jsx";

const DENS_VARS = [
  "var(--dens-0)", "var(--dens-1)", "var(--dens-2)", "var(--dens-3)",
  "var(--dens-4)", "var(--dens-5)", "var(--dens-6)", "var(--dens-7)",
];

export default function Pictorial() {
  const [shape, setShape] = useState(null);
  const [pic, setPic] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api("/api/daily-shape").then(setShape).catch(setErr);
    api("/api/picture?desk=general").then((d) => setPic(d.picture)).catch(() => {});
  }, []);

  if (err) return <Empty>加载失败：{String(err)}</Empty>;
  if (!shape) return <div className="page"><PanelSkeleton rows={10} /></div>;

  const doms = Object.keys(shape.heat);
  const maxCell = Math.max(1, ...doms.flatMap((d) => shape.heat[d]));
  const domTotals = doms.map((d) => [d, shape.heat[d].reduce((a, b) => a + b, 0)]);
  const lead = domTotals.sort((a, b) => b[1] - a[1])[0];
  const today = new Date();
  const wd = "日一二三四五六"[today.getDay()];

  return (
    <div className="page" style={{ maxWidth: 1080, margin: "0 auto", width: "100%" }}>
      <div className="panel pictorialhead">
        <div style={{ display: "flex", alignItems: "baseline" }}>
          <span className="uplabel">
            画报 · {today.toISOString().slice(0, 10)} · 周{wd}
          </span>
          <span className="mono" style={{ marginLeft: "auto", fontSize: 10.5,
                                          color: "var(--ink-4)" }}>
            {shape.docs_today} 篇归档 · {shape.born.length} 个新故事 ·
            {" "}{shape.dormant.length} 个转入沉寂
          </span>
        </div>
        <h1>
          {pic?.payload?.headline ||
            (lead
              ? `${lead[0]}占了今天 ${Math.round(
                  (lead[1] / Math.max(1, shape.docs_today)) * 100)}% 的归档量`
              : "今天还没有形状")}
        </h1>
      </div>

      <div className="panel panel-pad">
        <div style={{ display: "flex", alignItems: "baseline", marginBottom: 10 }}>
          <span className="uplabel">域 × 小时 热力</span>
          <span className="mono" style={{ marginLeft: "auto", fontSize: 10,
                                          color: "var(--ink-4)" }}>
            0 – {maxCell} 篇/时 · 分位分档
          </span>
        </div>
        <div className="heat">
          {doms.map((d) => (
            <div className="hrow" key={d}>
              <span className="hlabel"
                    style={{ fontWeight: lead && d === lead[0] ? 600 : 400 }}>
                {d}
              </span>
              {shape.heat[d].map((n, h) => (
                <i key={h} title={`${d} ${h}:00 · ${n} 篇`}
                   style={{ background:
                     DENS_VARS[Math.min(7, Math.round((n / maxCell) * 7))] }} />
              ))}
            </div>
          ))}
          <div className="hrow">
            <span className="hlabel" />
            {Array.from({ length: 24 }).map((_, h) => (
              <span key={h} style={{ flex: 1, textAlign: "center",
                fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-4)" }}>
                {[0, 6, 12, 18, 23].includes(h) ? String(h).padStart(2, "0") : ""}
              </span>
            ))}
          </div>
        </div>
        {!doms.length && <Empty>今天还没有带域标注的文档（V2 字段随新抽取产生）</Empty>}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
        <div className="panel">
          <div className="sect">今日新生</div>
          {shape.born.map((s) => (
            <a className="srow rest" key={s.id} href={`#/story/${s.id}`}>
              <span className="t">{s.title}</span>
              <span className="m"><span>重要度 {s.importance ?? "?"}</span></span>
            </a>
          ))}
          {!shape.born.length && <Empty>今天没有新故事</Empty>}
        </div>
        <div className="panel">
          <div className="sect">转入沉寂 <small>沉寂不等于结束</small></div>
          {shape.dormant.map((s) => (
            <a className="srow rest" key={s.id} href={`#/story/${s.id}`}>
              <span className="t">{s.title}</span>
            </a>
          ))}
          {!shape.dormant.length && <Empty>今天没有故事转入沉寂</Empty>}
        </div>
        <div className="panel">
          <div className="sect">今日实体</div>
          <div style={{ padding: "10px 14px", display: "flex",
                        flexDirection: "column", gap: 7 }}>
            {shape.entities.map((e) => (
              <div key={e.name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ flexBasis: 130, flexShrink: 0, fontSize: 12,
                               color: "var(--ink-2)", overflow: "hidden",
                               textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {e.name}
                </span>
                <span style={{ height: 8, borderRadius: 2, background: "var(--dens-5)",
                  width: `${(e.n / Math.max(1, shape.entities[0]?.n)) * 100}%` }} />
                <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>
                  {e.n}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
