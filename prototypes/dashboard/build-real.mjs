/* 真实数据 dashboard 生成器 —— 阶段 5 前端真化第一步
 *
 *   na snapshot                      → data/snapshot.json（Postgres 导出）
 *   node build-real.mjs              → real.html
 *
 * 与原型（build.mjs / build-story.mjs）的关系：同一套 theme 与编码语法，
 * 但数据从虚构 store.mjs 换成真实快照。原型里没有真数据支撑的版块
 * （数值源带、断言演变轨道、传闻区间）**直接不出现** —— 不做假数据混排。
 *
 * 单文件输出：总览 + 每个已合成故事的详情节，hash 路由切换。
 * 综述引用是可点开的（chip → 引用卡片），不是装饰 —— 最高原则 5 的前端面。
 * 代码路径零主题词汇：所有领域内容都来自数据。
 */

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { css } from "./theme.mjs";

const OUT = dirname(fileURLToPath(import.meta.url));
const SNAP = JSON.parse(readFileSync(join(OUT, "data", "snapshot.json"), "utf8"));
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[c]));

/* 中性蓝（与故事页原型一致：不属于任何频道的标识色） */
const CFG = {
  dark:  { accent:"#3987e5", ramp:["#16283f","#1b3a5c","#214d7a","#286098","#2f75b8","#3987e5"] },
  light: { accent:"#2a78d6", ramp:["#d3e4f8","#aecdf2","#86b6ef","#5e9ce4","#3f86d8","#2a78d6"] },
};
const STAGE = { 4:"爆发", 3:"升温", 2:"发展", 1:"收敛" };
const KIND_GLYPH = { org:"■", person:"●", place:"▲", product:"◆", event:"✦" };  // 形状=类型（CVD-safe）

/* ── 小部件 ─────────────────────────────────────────────── */

function spark(data, w = 70, h = 24) {
  const hi = Math.max(...data, 1);
  const bw = (w - 2) / data.length;
  const bars = data.map((v, i) =>
    `<rect x="${(1 + i * bw).toFixed(1)}" y="${(h - 2 - (v / hi) * (h - 6)).toFixed(1)}" width="${Math.max(bw - 1.2, 1).toFixed(1)}" height="${((v / hi) * (h - 6) + 1).toFixed(1)}" fill="${v ? "var(--accent)" : "color-mix(in srgb,var(--hairline) 80%,transparent)"}" opacity="${v ? .85 : .6}"/>`).join("");
  return `<svg viewBox="0 0 ${w} ${h}" aria-hidden="true">${bars}</svg>`;
}
const meter = (v, max, color = "var(--accent)") =>
  `<div class="meter"><i style="width:${Math.min(100, Math.round(v / (max || 1) * 100))}%;background:${color}"></i></div>`;
const vel = v => v == null ? "" :
  `<em class="ar">${v > 0 ? "▲" : v < 0 ? "▼" : "◆"}</em>${Math.abs(v)}%`;
const stanceCell = v =>
  `<u data-v="${Math.max(-2, Math.min(2, v))}" title="本文立场 ${v > 0 ? "+" + v : v}">${v > 0 ? "+" + v : v}</u>`;

/* ── 总览 ───────────────────────────────────────────────── */

const T = SNAP.totals;
const statusStrip = `
<div class="status">
  <div>可用文档 <b>${T.docs}</b></div>
  <div>已抽取 <b>${T.extracted}</b></div>
  <div>断言 <b>${T.claims}</b></div>
  <div>实体 <b>${T.entities}</b></div>
  <div>活跃故事 <b>${T.stories}</b></div>
  <div>已合成 <b>${T.synthesized}</b></div>
  <div class="live">最近采集 <b>${esc((T.last_fetch || "").slice(5, 16))}</b></div>
  <div>快照 <b>${esc(SNAP.generated_at.slice(5, 16).replace("T", " "))}</b></div>
</div>`;

function storyRow(s) {
  const sc = s.scalars, syn = s.synthesized;
  const name = syn
    ? `<a href="#s${s.id}" style="color:var(--ink);text-decoration:none">${esc(s.title)}<u class="also">综述</u></a>`
    : esc(s.title);
  return `<div class="vt" style="border-left-color:${syn ? "var(--accent)" : "transparent"}">
    <div class="nm">${name}
      <small>#${s.id} · 源 ${sc.breadth ?? "?"} · 共识 ${sc.consensus ?? "?"}% · ${esc(s.updated)}</small></div>
    <div class="pc">${sc.docs ?? "?"}<span style="font-size:10px;color:var(--ink-3)"> 篇</span><br>
      <span style="font-size:10px;font-weight:400">${vel(sc.velocity)}</span></div>
    ${spark(s.series)}
  </div>`;
}

const multi = SNAP.stories.filter(s => (s.scalars.docs ?? 0) >= 2);
const single = SNAP.stories.length - multi.length;
const storiesPanel = `
<section class="panel c7"><header><h2>故事流 · 多篇活跃故事</h2>
  <span class="note">按文档数 · 火花线 = 近 14 天逐日吸收</span></header>
  <div class="body">${multi.map(storyRow).join("")}
  <div class="scale" style="border-top:0;margin-top:8px">另有 ${single} 个单篇故事未列出 ·
    <span style="color:var(--accent)">▎</span> 左缘标记 = 已合成（可点入）</div></div>
</section>`;

const maxSrc = Math.max(...SNAP.sources.map(s => s.docs), 1);
const srcPanel = `
<section class="panel c5"><header><h2>来源构成</h2><span class="note">L1–L7 证据层级</span></header>
  <div class="body"><ul class="rank" style="margin:0;padding:0">${SNAP.sources.map((s, i) => `
    <li><span class="i">${i + 1}</span>
      <span class="n">${esc(s.name)}<small>L${s.tier} · ${esc(s.key)}</small></span>
      <span class="w">${s.docs}</span>
      <span>${meter(s.docs, maxSrc)}</span></li>`).join("")}
  </ul></div>
</section>`;

const maxDf = Math.max(...SNAP.entities.map(e => e.df), 1);
const entPanel = `
<section class="panel c5"><header><h2>实体活跃榜</h2>
  <span class="note">规范条目 · 形状=类型</span></header>
  <div class="body"><ul class="rank" style="margin:0;padding:0">${SNAP.entities.slice(0, 24).map((e, i) => `
    <li><span class="i">${i + 1}</span>
      <span class="n"><em class="ar">${KIND_GLYPH[e.kind] || "○"}</em> ${esc(e.name)}<small>${esc(e.kind)}</small></span>
      <span class="w">${e.df}</span>
      <span>${meter(e.df, maxDf, "var(--accent-2)")}</span></li>`).join("")}
  </ul></div>
</section>`;

const synPanel = `
<section class="panel c7"><header><h2>已合成故事 · 每句带引用</h2>
  <span class="note">D23 · 无引用的句子不存在</span></header>
  <div class="body">${SNAP.stories.filter(s => s.synthesized).map(s => `
    <div class="vt" style="grid-template-columns:1fr 90px">
      <div class="nm"><a href="#s${s.id}" style="color:var(--ink);text-decoration:none">${esc(s.title)}</a>
        <small>${(s.summary || []).length} 句综述 · ${(s.timeline || []).length} 时间线 · ${(s.open_questions || []).length} 开放问题</small></div>
      <div class="pc" style="font-size:11px;font-weight:400"><span class="stage" data-s="${s.scalars.stage ?? 2}">${STAGE[s.scalars.stage] || "—"}</span></div>
    </div>`).join("")}</div>
</section>`;

/* ── 故事详情节 ─────────────────────────────────────────── */

function storySection(s) {
  const sc = s.scalars;
  /* 引用编号：按综述+时间线首次出现顺序 */
  const order = [];
  for (const part of [...(s.summary || []), ...(s.timeline || [])])
    for (const id of part.claim_ids) if (!order.includes(id)) order.push(id);
  const refNo = new Map(order.map((id, i) => [id, i + 1]));
  const chip = id => {
    const c = SNAP.claims[id];
    const tip = c ? `${c.source} ${c.date} · ${c.text}` : `claim ${id}`;
    return `<a class="cite" href="#s${s.id}-r${id}" data-tip="${esc(tip)}">${refNo.get(id)}</a>`;
  };

  const stat = `<div class="status" style="border-top:1px solid var(--hairline-2)">
    <div>阶段 <b><span class="stage" data-s="${sc.stage ?? 2}">${STAGE[sc.stage] || "—"}</span></b></div>
    <div>动量 <b>${vel(sc.velocity) || "—"}</b></div>
    <div>报道 <b>${sc.docs ?? "?"} 篇</b></div>
    <div>独立源 <b>${sc.breadth ?? "?"}</b></div>
    <div>共识度 <b>${sc.consensus ?? "?"}%</b></div>
    <div>建档 <b>${esc(s.created)}</b> · 更新 <b>${esc(s.updated)}</b></div>
  </div>`;

  const summary = `<section class="panel c7"><header><h2>AI 综述</h2>
    <span class="note">每句带引用 · 点编号看原始断言</span></header>
    <div class="body" style="font-size:13.5px;line-height:1.85">
      ${(s.summary || []).map(x => `<span>${esc(x.text)}</span>${x.claim_ids.map(chip).join("")} `).join("")}
    </div></section>`;

  const timeline = (s.timeline || []).length ? `<section class="panel c5"><header><h2>时间线</h2>
    <span class="note">只收状态变化</span></header><div class="body oq"><ul>
    ${s.timeline.map(t => `<li><div class="q"><b style="font-family:var(--mono);font-size:11px;color:var(--ink-2)">${esc(t.when)}</b> · ${esc(t.what)} ${t.claim_ids.map(chip).join("")}</div></li>`).join("")}
    </ul></div></section>` : "";

  const oq = (s.open_questions || []).length ? `<section class="panel c5"><header><h2>开放问题</h2>
    <span class="note">现有报道未回答</span></header><div class="body oq"><ul>
    ${s.open_questions.map(q => `<li><div class="q">${esc(q)}</div></li>`).join("")}
    </ul></div></section>` : "";

  const refs = `<section class="panel c7"><header><h2>引用 · 原始断言</h2>
    <span class="note">${order.length} 条被引 / 立场 −2..+2</span></header>
    <div class="body">${order.map(id => {
      const c = SNAP.claims[id];
      if (!c) return "";
      return `<div class="dm-r" id="s${s.id}-r${id}" style="grid-template-columns:26px 1fr 22px 110px">
        <u style="background:var(--surface-2);color:var(--ink-2)">${refNo.get(id)}</u>
        <div class="cl"><b style="white-space:normal">${esc(c.text)}</b></div>
        ${stanceCell(c.stance)}
        <small style="font-family:var(--mono);font-size:9.5px;color:var(--ink-3);text-align:right">${esc(c.source)} · ${esc(c.date)}</small>
      </div>`;
    }).join("")}</div></section>`;

  const tiers = {};
  for (const d of (s.docs || [])) (tiers[d.tier] ??= []).push(d);
  const docsPanel = `<section class="panel c6"><header><h2>报道 · 按证据层级</h2>
    <span class="note">${(s.docs || []).length} 篇</span></header>
    <div class="body">${Object.keys(tiers).sort().map(t => `<div class="tier">
      <div class="th"><b>L${t}</b><span>${tiers[t].length} 篇</span></div>
      ${tiers[t].map(d => `<div style="padding:2px 0;font-size:12px">
        <span style="font-family:var(--mono);font-size:9.5px;color:var(--ink-3)">${esc(d.date)} ${esc(d.source)}</span>
        ${esc(d.title || "(无标题)")}${d.copies ? ` <u class="also" style="text-decoration:none">${d.copies} 家转发</u>` : ""}</div>`).join("")}
    </div>`).join("")}</div></section>`;

  const events = `<section class="panel c6"><header><h2>故事履历</h2>
    <span class="note">event-sourcing · 为什么这篇在这里</span></header>
    <div class="body">${(s.events || []).map(e => {
      const p = e.payload || {};
      const why = p.reason ? ` — ${esc(String(p.reason).slice(0, 110))}` : "";
      return `<div style="padding:4px 0;border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent);font-size:11.5px">
        <span style="font-family:var(--mono);font-size:10px;color:var(--ink-3)">${esc(e.at)}</span>
        <b style="font-family:var(--mono);font-size:10px;color:var(--accent)"> ${esc(e.kind)}</b>${why}</div>`;
    }).join("")}
    <div class="lgrow">${(s.entities || []).map(e => `<span><em class="ar">${KIND_GLYPH[e.kind] || "○"}</em>${esc(e.name)}</span>`).join("")}</div>
    </div></section>`;

  return `<div class="view" id="s${s.id}" hidden>
    <div class="rail" style="border-top:1px solid var(--hairline-2)">
      <div class="brand"><span class="dot"></span><b>故事 #${s.id}</b></div>
      <div class="chan" style="color:var(--ink);max-width:60ch;white-space:normal">${esc(s.title)}</div>
      <span class="railpad"></span>
      <a class="chan" href="#" style="cursor:pointer;color:var(--accent);text-decoration:none">← 返回总览</a>
    </div>
    ${stat}
    <main class="grid">${summary}${timeline}${refs}${oq}${docsPanel}${events}</main>
  </div>`;
}

/* ── 页面组装 ───────────────────────────────────────────── */

const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NewsAssistant · 实时数据总览</title>
<style>${css(CFG)}
.cite { font-family:var(--mono); font-size:9.5px; color:var(--accent); text-decoration:none;
  border:1px solid color-mix(in srgb,var(--accent) 45%,transparent); padding:0 4px; margin:0 2px;
  vertical-align:2px; }
.cite:hover { background:color-mix(in srgb,var(--accent) 18%,transparent); }
.dm-r:target { background:color-mix(in srgb,var(--accent) 12%,transparent); }
.real { align-self:center; margin-right:12px; font-family:var(--mono); font-size:10px;
  letter-spacing:.11em; color:var(--st-good); border:1px solid currentColor; padding:3px 8px; }
</style></head>
<body><div class="console">
<div class="view" id="overview">
  <div class="rail">
    <div class="brand"><span class="dot"></span><b>NEWSASSISTANT</b></div>
    <nav class="chans"><button class="chan" aria-current="true">全库总览</button></nav>
    <span class="railpad"></span><span class="real">REAL DATA</span>
  </div>
  ${statusStrip}
  <main class="grid">${storiesPanel}${srcPanel}${synPanel}${entPanel}</main>
</div>
${SNAP.stories.filter(s => s.synthesized).map(storySection).join("")}
<footer>
  <b>编码语法</b>：▲▼=方向（不用颜色） · 阶段框=阈值状态色 · 形状=实体类型 · 立场 −2..+2 蓝↔红+数字
  · <b>综述每句的编号是它存在的许可证</b>（点开可见原始断言与来源） ·
  快照 ${esc(SNAP.generated_at)} · 由 na snapshot + build-real.mjs 生成，全部真实数据
</footer>
<div id="tip" role="status"></div>
</div>
<script>
/* hash 路由 + 引用 tooltip —— 页面其余部分全部为生成时静态渲染 */
const views = document.querySelectorAll(".view");
function route() {
  const h = location.hash.slice(1);
  const target = /^s\\d+$/.test(h) ? h : (/^s(\\d+)-r\\d+$/.exec(h)?.[1] ? "s" + /^s(\\d+)-r\\d+$/.exec(h)[1] : "overview");
  views.forEach(v => v.hidden = v.id !== target);
  if (/-r\\d+$/.test(h)) document.getElementById(h)?.scrollIntoView({ block:"center" });
  else window.scrollTo(0, 0);
}
addEventListener("hashchange", route); route();
const tip = document.getElementById("tip");
document.querySelectorAll("[data-tip]").forEach(el => {
  el.addEventListener("mouseenter", () => { tip.textContent = el.dataset.tip;
    tip.style.whiteSpace = "normal"; tip.style.maxWidth = "46ch"; tip.classList.add("on"); });
  el.addEventListener("mousemove", e => {
    const r = tip.getBoundingClientRect();
    tip.style.left = Math.min(innerWidth - r.width - 10, e.clientX + 12) + "px";
    tip.style.top = Math.min(innerHeight - r.height - 10, e.clientY + 14) + "px"; });
  el.addEventListener("mouseleave", () => tip.classList.remove("on"));
});
</script></body></html>`;

writeFileSync(join(OUT, "real.html"), html);
console.log(`real.html: ${SNAP.totals.stories} stories, ${SNAP.totals.synthesized} synthesized, ${(html.length / 1024).toFixed(0)} KB`);
