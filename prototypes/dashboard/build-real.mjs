/* 真实数据 dashboard 生成器 —— 阶段 5 前端真化
 *
 *   na snapshot        → data/snapshot.json（Postgres 导出）
 *   node build-real.mjs → real.html
 *
 * 态势室构图：源×日热力带 / 故事×日吸收矩阵 / 实体共现网络（构建时力导向）/
 * 合成故事卡片墙 / 证据层级构成 / 分歧榜。原型没有真数据支撑的版块不出现。
 * 配色全部来自 theme.mjs 的已校验 token；编码语法（docs/views.md）全局不变：
 * 色阶=密度（分位分档）· ▲▼=方向 · 形状=实体类型 · 状态色只表示越阈 ·
 * 立场 −2..+2 蓝↔红+数字。综述引用可点开 —— 最高原则 5 的前端面。
 * 代码路径零主题词汇：所有领域内容来自数据。
 */

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { css } from "./theme.mjs";

const OUT = dirname(fileURLToPath(import.meta.url));
const SNAP = JSON.parse(readFileSync(join(OUT, "data", "snapshot.json"), "utf8"));
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[c]));
const sum = a => a.reduce((x, y) => x + y, 0);

const CFG = {
  dark:  { accent:"#3987e5", ramp:["#16283f","#1b3a5c","#214d7a","#286098","#2f75b8","#3987e5"] },
  light: { accent:"#2a78d6", ramp:["#d3e4f8","#aecdf2","#86b6ef","#5e9ce4","#3f86d8","#2a78d6"] },
};
const STAGE = { 4:"爆发", 3:"升温", 2:"发展", 1:"收敛" };
const KIND = {  // 形状=实体类型（CVD-safe）；SVG 与文本双形态
  org:    { g:"■", svg:(x,y,r)=>`<rect x="${x-r}" y="${y-r}" width="${2*r}" height="${2*r}"/>` },
  person: { g:"●", svg:(x,y,r)=>`<circle cx="${x}" cy="${y}" r="${r}"/>` },
  place:  { g:"▲", svg:(x,y,r)=>`<path d="M${x} ${y-r*1.2}L${x+r*1.1} ${y+r*.9}L${x-r*1.1} ${y+r*.9}Z"/>` },
  product:{ g:"◆", svg:(x,y,r)=>`<path d="M${x} ${y-r*1.2}L${x+r*1.2} ${y}L${x} ${y+r*1.2}L${x-r*1.2} ${y}Z"/>` },
  event:  { g:"✦", svg:(x,y,r)=>`<circle cx="${x}" cy="${y}" r="${r}" fill="none" stroke-width="2"/>` },
};
const kindOf = k => KIND[k] || { g:"○", svg: KIND.event.svg };

/* ── 分位分档（编码语法：色阶=密度，非线性） ─────────────── */
function bucketer(values) {
  const pos = values.filter(v => v > 0).sort((a, b) => a - b);
  if (!pos.length) return () => 0;
  const q = p => pos[Math.min(pos.length - 1, Math.floor(p * pos.length))];
  const cuts = [q(.15), q(.35), q(.55), q(.75), q(.9)];
  return v => v <= 0 ? 0 : 1 + cuts.filter(c => v > c).length;
}
const cells = (data, bucket, tips = null) =>
  `<div class="cells" style="grid-template-columns:repeat(${data.length},1fr)">` +
  data.map((v, i) => `<i data-b="${bucket(v)}"${tips ? ` data-tip="${esc(tips(v, i))}"` : ""}></i>`).join("") + "</div>";

/* ── 通用小件 ───────────────────────────────────────────── */
const num = (v, unit = "") => `<b>${v}</b>${unit ? `<span class="u">${unit}</span>` : ""}`;
const stanceCell = v =>
  `<u data-v="${Math.max(-2, Math.min(2, v))}">${v > 0 ? "+" + v : v}</u>`;
function velTag(s) {
  const v = s.scalars.velocity;
  if (v == null) return "";
  if (v >= 100) return `<span class="new-tag">新</span>`;
  return `<span class="vel"><em class="ar">${v > 0 ? "▲" : v < 0 ? "▼" : "◆"}</em>${Math.abs(v)}%</span>`;
}
/* 库龄不足时 velocity 全为 +100%、stage 全为 4 —— 是数据年轻不是事件爆发。
   前 3 天基数为 0 的故事显示「新」徽章而非阶段章，避免整列同色噪声。 */
const stageChip = s => {
  const sc = s.scalars;
  if ((sc.velocity ?? 0) >= 100) return `<span class="new-tag">新</span>`;
  return `<span class="stage" data-s="${sc.stage ?? 2}">${STAGE[sc.stage] || "—"}</span>`;
};
const consBar = c => c == null ? "" :
  `<div class="cons" data-tip="共识度 ${c}%（claim 立场一致性）"><i style="width:${c}%;background:${c < 60 ? "var(--div-p2)" : c < 80 ? "var(--st-warning)" : "var(--accent)"}"></i></div>`;

/* ── ① 源 × 日 热力带 ───────────────────────────────────── */
const DAYS = 30;
const dayLabel = i => {
  const d = new Date(SNAP.generated_at); d.setUTCDate(d.getUTCDate() - (DAYS - 1 - i));
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
};
const srcRows = SNAP.sources.filter(s => SNAP.daily_sources[s.key]);
const allDaily = srcRows.flatMap(s => SNAP.daily_sources[s.key]);
const dBucket = bucketer(allDaily);
const pulse = `
<section class="panel c12"><header><h2>采集脉搏 · 源 × 日</h2>
  <span class="note">近 30 天逐日可用文档 · 分位分档色阶</span></header>
  <div class="body">
    ${srcRows.map(s => {
      const d = SNAP.daily_sources[s.key];
      return `<div class="lane">
        <span class="tierchip" data-t="${s.tier}">L${s.tier}</span>
        <span class="lname">${esc(s.name)}</span>
        ${cells(d, dBucket, (v, i) => `${dayLabel(i)} · ${esc(s.key)} · ${v} 篇`)}
        <span class="ltot">${sum(d)}</span>
      </div>`;
    }).join("")}
    <div class="lane axis"><span class="tierchip" style="visibility:hidden">L0</span><span class="lname"></span>
      <div class="cells" style="grid-template-columns:repeat(${DAYS},1fr)">${Array.from({ length: DAYS },
        (_, i) => `<i style="background:none;box-shadow:none;height:auto">${i % 5 === 4 ? `<s>${dayLabel(i)}</s>` : ""}</i>`).join("")}</div>
      <span class="ltot"></span></div>
  </div>
</section>`;

/* ── ② 故事 × 日 吸收矩阵 ───────────────────────────────── */
const multi = SNAP.stories.filter(s => (s.scalars.docs ?? 0) >= 2);
const sBucket = bucketer(multi.flatMap(s => s.series));
const matrix = `
<section class="panel c8"><header><h2>故事热力 · 吸收 × 日</h2>
  <span class="note">${multi.length} 个多篇故事 · 近 14 天 · <i class="mark"></i>=已合成可点入</span></header>
  <div class="body">
    ${multi.slice(0, 22).map(s => {
      const sc = s.scalars;
      const name = s.synthesized
        ? `<a href="#s${s.id}">${esc(s.title)}</a>`
        : esc(s.title);
      return `<div class="mrow${s.synthesized ? " syn" : ""}">
        <div class="mt">${name}<small>#${s.id} · ${sc.breadth ?? "?"} 源</small></div>
        ${stageChip(s)}
        ${cells(s.series, sBucket, (v, i) => `${v} 篇吸收`)}
        <span class="md">${sc.docs}</span>
        ${consBar(sc.consensus)}
      </div>`;
    }).join("")}
    <div class="scale"><span>吸收/日</span>${[0,1,2,3,4,5,6].map(b => `<i data-b="${b}" class="sw"></i>`).join("")}
      <span>0 → 高（分位）</span><span style="margin-left:auto">另有 ${SNAP.stories.length - multi.length} 个单篇故事</span></div>
  </div>
</section>`;

/* ── ③ 实体共现网络（构建时力导向布局，确定性种子） ─────── */
function layoutGraph(nodes, edges, W, H) {
  let seed = 42;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
  const P = nodes.map(() => ({ x: (rnd() - .5) * W * .8, y: (rnd() - .5) * H * .8, vx: 0, vy: 0 }));
  for (let it = 0; it < 300; it++) {
    const t = 1 - it / 300;
    for (let i = 0; i < P.length; i++) for (let j = i + 1; j < P.length; j++) {
      let dx = P[i].x - P[j].x, dy = P[i].y - P[j].y;
      const d2 = dx * dx + dy * dy + 0.01, f = 7000 / d2;
      dx *= f; dy *= f;
      P[i].vx += dx; P[i].vy += dy; P[j].vx -= dx; P[j].vy -= dy;
    }
    for (const e of edges) {
      const a = P[e.a], b = P[e.b];
      const k = 0.004 * Math.min(e.w, 8);
      a.vx += (b.x - a.x) * k; a.vy += (b.y - a.y) * k;
      b.vx += (a.x - b.x) * k; b.vy += (a.y - b.y) * k;
    }
    for (const p of P) {
      p.vx -= p.x * 0.012; p.vy -= p.y * 0.012;           // 向心
      p.x += Math.max(-14, Math.min(14, p.vx * t)); p.y += Math.max(-14, Math.min(14, p.vy * t));
      p.vx *= .5; p.vy *= .5;
    }
  }
  const xs = P.map(p => p.x), ys = P.map(p => p.y);
  const sx = (W - 90) / (Math.max(...xs) - Math.min(...xs) || 1),
        sy = (H - 60) / (Math.max(...ys) - Math.min(...ys) || 1);
  return P.map(p => ({ x: 45 + (p.x - Math.min(...xs)) * sx, y: 30 + (p.y - Math.min(...ys)) * sy }));
}
const G = SNAP.cooc, GW = 470, GH = 430;
const pos = layoutGraph(G.nodes, G.edges, GW, GH);
const maxW = Math.max(...G.edges.map(e => e.w), 1);
const maxDfN = Math.max(...G.nodes.map(n => n.df), 1);
const network = `
<section class="panel c4"><header><h2>实体共现网络</h2>
  <span class="note">df 头部 ${G.nodes.length} · 边=同文档共现</span></header>
  <div class="body net"><svg viewBox="0 0 ${GW} ${GH}" role="img" aria-label="实体共现网络">
    ${G.edges.map(e => `<line x1="${pos[e.a].x.toFixed(1)}" y1="${pos[e.a].y.toFixed(1)}"
      x2="${pos[e.b].x.toFixed(1)}" y2="${pos[e.b].y.toFixed(1)}"
      stroke="var(--accent)" stroke-opacity="${(0.12 + 0.45 * e.w / maxW).toFixed(2)}"
      stroke-width="${(0.6 + 2.4 * e.w / maxW).toFixed(1)}"/>`).join("")}
    ${G.nodes.map((n, i) => {
      const r = 3.5 + 8 * Math.sqrt(n.df / maxDfN);
      return `<g fill="var(--accent)" stroke="var(--accent)" data-tip="${esc(n.name)} · ${esc(n.kind)} · ${n.df} 篇">
        ${kindOf(n.kind).svg(pos[i].x, pos[i].y, r)}</g>` +
        (n.df / maxDfN > .3 ? `<text x="${pos[i].x.toFixed(1)}" y="${(pos[i].y - r - 4).toFixed(1)}"
          text-anchor="middle">${esc(n.name)}</text>` : "");
    }).join("")}
  </svg>
  <div class="lgrow">${Object.entries(KIND).map(([k, v]) => `<span><em class="ar">${v.g}</em>${k}</span>`).join("")}</div>
  </div>
</section>`;

/* ── ④ 合成故事卡片墙 ───────────────────────────────────── */
const synStories = SNAP.stories.filter(s => s.synthesized);
const cardWall = `
<section class="panel c8"><header><h2>已合成 · 每句带引用</h2>
  <span class="note">D23 · 无引用的句子不存在 · 点卡片进详情</span></header>
  <div class="body cardwall">
    ${synStories.map(s => {
      const sc = s.scalars, first = (s.summary || [])[0];
      return `<a class="card" href="#s${s.id}">
        <div class="ct">${stageChip(s)} ${esc(s.title)}</div>
        <div class="cs">${esc(first ? first.text : "")}</div>
        <div class="cm"><span>${sc.docs} 篇</span><span>${sc.breadth} 源</span>
          <span>${(s.summary || []).length} 句 · ${(s.timeline || []).length} 时点</span>
          <span>共识 ${sc.consensus}%</span></div>
      </a>`;
    }).join("")}
  </div>
</section>`;

/* ── ⑤ 右列：层级构成 / 分歧榜 / 实体榜 ─────────────────── */
const tierTotals = {};
for (const s of SNAP.sources) tierTotals[s.tier] = (tierTotals[s.tier] || 0) + s.docs;
const tierMax = sum(Object.values(tierTotals)) || 1;
const tierPanel = `
<section class="panel c4"><header><h2>证据层级构成</h2><span class="note">L1 锚点 → L5 时效</span></header>
  <div class="body">
    <div class="stack">${Object.entries(tierTotals).sort().map(([t, n]) =>
      `<i style="flex:${n};background:var(--s${Math.min(6, +t + 1)})" data-tip="L${t} · ${n} 篇"></i>`).join("")}</div>
    ${Object.entries(tierTotals).sort().map(([t, n]) => {
      const names = SNAP.sources.filter(s => s.tier === +t);
      return `<div class="trow"><span class="tierchip" data-t="${t}">L${t}</span>
        <span class="tn">${names.map(s => esc(s.name.split("·")[0].split("（")[0].trim())).join(" / ")}</span>
        <span class="tv">${n}<small> (${Math.round(n / tierMax * 100)}%)</small></span></div>`;
    }).join("")}
    <div class="scale" style="margin-top:8px">占比按可用文档计 · SEC 源被出口 IP 拦截暂为 0</div>
  </div>
</section>`;

const contested = multi.filter(s => s.scalars.consensus != null && s.scalars.consensus < 85)
  .sort((a, b) => a.scalars.consensus - b.scalars.consensus).slice(0, 7);
const divPanel = `
<section class="panel c4"><header><h2>分歧榜 · 共识度最低</h2><span class="note">立场方差大 = 值得看</span></header>
  <div class="body">
    ${contested.map(s => `<div class="dv-r" style="grid-template-columns:1fr 74px 34px">
      <div class="nm">${s.synthesized ? `<a href="#s${s.id}">${esc(s.title)}</a>` : esc(s.title)}</div>
      <div class="bar"><i style="left:0;width:${s.scalars.consensus}%;background:${s.scalars.consensus < 60 ? "var(--div-p2)" : "var(--st-warning)"}"></i></div>
      <div class="sc">${s.scalars.consensus}</div>
    </div>`).join("") || `<div class="scale" style="border:0">当前故事池内共识度普遍高 —— 分歧要等同事件多源对立报道</div>`}
  </div>
</section>`;

const maxDf = Math.max(...SNAP.entities.map(e => e.df), 1);
const entPanel = `
<section class="panel c4"><header><h2>实体活跃榜</h2><span class="note">规范条目 · 形状=类型</span></header>
  <div class="body">
    ${SNAP.entities.slice(0, 14).map((e, i) => `<div class="erow">
      <span class="i">${i + 1}</span><em class="ar">${kindOf(e.kind).g}</em>
      <span class="en">${esc(e.name)}</span>
      <div class="meter"><i style="width:${Math.round(e.df / maxDf * 100)}%;background:var(--accent-2)"></i></div>
      <span class="ev">${e.df}</span></div>`).join("")}
  </div>
</section>`;

/* ── 总览组装 ───────────────────────────────────────────── */
const T = SNAP.totals;
const statusStrip = `
<div class="status">
  <div>可用文档 ${num(T.docs)}</div><div>已抽取 ${num(T.extracted)}</div>
  <div>断言 ${num(T.claims)}</div><div>实体 ${num(T.entities)}</div>
  <div>活跃故事 ${num(T.stories)}</div><div>已合成 ${num(T.synthesized)}</div>
  <div class="live">最近采集 ${num(esc((T.last_fetch || "").slice(5, 16)))}</div>
  <div>快照 ${num(esc(SNAP.generated_at.slice(5, 16).replace("T", " ")))}</div>
</div>`;

const overview = `
<div class="view" id="overview">
  <div class="rail">
    <div class="brand"><span class="dot"></span><b>NEWSASSISTANT</b></div>
    <nav class="chans"><button class="chan" aria-current="true">全库总览</button></nav>
    <span class="railpad"></span><span class="real">REAL DATA</span>
  </div>
  ${statusStrip}
  <main class="grid">${pulse}${matrix}${network}${cardWall}${tierPanel}${divPanel}${entPanel}</main>
</div>`;

/* ── 故事详情节 ─────────────────────────────────────────── */
function storySection(s) {
  const sc = s.scalars;
  const order = [];
  for (const part of [...(s.summary || []), ...(s.timeline || [])])
    for (const id of part.claim_ids) if (!order.includes(id)) order.push(id);
  const refNo = new Map(order.map((id, i) => [id, i + 1]));
  const chip = id => {
    const c = SNAP.claims[id];
    return `<a class="cite" href="#s${s.id}-r${id}" data-tip="${esc(c ? `${c.source} ${c.date} · ${c.text}` : `claim ${id}`)}">${refNo.get(id)}</a>`;
  };
  const stances = order.map(id => SNAP.claims[id]?.stance ?? 0);

  const stat = `<div class="status">
    <div>阶段 <b>${stageChip(s)}</b></div>
    <div>报道 ${num(sc.docs ?? "?", "篇")}</div><div>独立源 ${num(sc.breadth ?? "?")}</div>
    <div>共识度 ${num(sc.consensus ?? "?", "%")}</div>
    <div>被引断言 ${num(order.length)}</div>
    <div>建档 ${num(esc(s.created))}</div><div>更新 ${num(esc(s.updated))}</div>
  </div>`;

  const summary = `<section class="panel c7"><header><h2>AI 综述</h2>
    <span class="note">每句带引用 · 悬停/点编号看原始断言</span></header>
    <div class="body prose">
      ${(s.summary || []).map(x => `<span>${esc(x.text)}</span>${x.claim_ids.map(chip).join("")} `).join("")}
    </div></section>`;

  const timeline = (s.timeline || []).length ? `<section class="panel c5"><header><h2>时间线</h2>
    <span class="note">只收状态变化</span></header>
    <div class="body tline">
    ${s.timeline.map(t => `<div class="tl-e"><span class="tl-w">${esc(t.when)}</span>
      <div class="tl-x">${esc(t.what)} ${t.claim_ids.map(chip).join("")}</div></div>`).join("")}
    </div></section>` : "";

  const refs = `<section class="panel c7"><header><h2>引用 · 原始断言</h2>
    <span class="note">${stances.some(v => v) ? `立场分布 <span class="stance-strip">${stances.map(stanceCell).join("")}</span>` : `${order.length} 条被引 · 立场全中性`}</span></header>
    <div class="body">${order.map(id => {
      const c = SNAP.claims[id];
      if (!c) return "";
      return `<div class="ref" id="s${s.id}-r${id}">
        <span class="rn">${refNo.get(id)}</span>
        <div class="rt">${esc(c.text)}</div>
        ${stanceCell(c.stance)}
        <span class="rs">${esc(c.source)}<br>${esc(c.date)}</span>
      </div>`;
    }).join("")}</div></section>`;

  const oq = (s.open_questions || []).length ? `<section class="panel c5"><header><h2>开放问题</h2>
    <span class="note">现有报道未回答</span></header><div class="body oq"><ul>
    ${s.open_questions.map(q => `<li><div class="q">${esc(q)}</div></li>`).join("")}
    </ul></div></section>` : "";

  const tiers = {};
  for (const d of (s.docs || [])) (tiers[d.tier] ??= []).push(d);
  const docsPanel = `<section class="panel c6"><header><h2>报道 · 按证据层级</h2>
    <span class="note">${(s.docs || []).length} 篇</span></header>
    <div class="body">${Object.keys(tiers).sort().map(t => `<div class="tier">
      <div class="th"><span class="tierchip" data-t="${t}">L${t}</span><span>${tiers[t].length} 篇</span></div>
      ${tiers[t].map(d => `<div class="drow">
        <span class="dd">${esc(d.date)}</span><span class="ds">${esc(d.source)}</span>
        <span class="dt">${esc(d.title || "(无标题)")}</span>${d.copies ? `<u class="also">${d.copies} 家转发</u>` : ""}</div>`).join("")}
    </div>`).join("")}</div></section>`;

  const events = `<section class="panel c6"><header><h2>故事履历</h2>
    <span class="note">event-sourcing · 为什么这篇在这里</span></header>
    <div class="body">${(s.events || []).map(e => {
      const p = e.payload || {};
      const why = p.reason ? ` — ${esc(String(p.reason).slice(0, 120))}` : "";
      return `<div class="ev"><span class="evt">${esc(e.at)}</span>
        <b class="evk" data-k="${esc(e.kind)}">${esc(e.kind)}</b><span class="evr">${why}</span></div>`;
    }).join("")}
    <div class="lgrow">${(s.entities || []).map(e => `<span><em class="ar">${kindOf(e.kind).g}</em>${esc(e.name)}</span>`).join("")}</div>
    </div></section>`;

  return `<div class="view" id="s${s.id}" hidden>
    <div class="rail">
      <div class="brand"><span class="dot"></span><b>故事 #${s.id}</b></div>
      <div class="chan title-chan">${esc(s.title)}</div>
      <span class="railpad"></span>
      <a class="chan back" href="#">← 返回总览</a>
    </div>
    ${stat}
    <main class="grid">${summary}${timeline}${refs}${oq}${docsPanel}${events}</main>
  </div>`;
}

/* ── 附加样式（真实页专属；token 全部来自 theme） ────────── */
const extraCss = `
.status b { font-size:15px; } .status .u { color:var(--ink-3); font-size:10px; margin-left:2px; }
.real { align-self:center; margin-right:12px; font-family:var(--mono); font-size:10px;
  letter-spacing:.11em; color:var(--st-good); border:1px solid currentColor; padding:3px 8px; }
a { color:inherit; }
.mark { display:inline-block; width:8px; height:8px; background:var(--accent); vertical-align:-1px; }

/* 脉搏带 */
.lane { display:grid; grid-template-columns:30px minmax(150px,190px) 1fr 44px; gap:9px;
  align-items:center; padding:3px 0; }
.lane .cells i { height:17px; }
.lane.axis i { position:relative; } .lane.axis s { position:absolute; left:0; top:1px;
  text-decoration:none; font-family:var(--mono); font-size:8.5px; color:var(--ink-3); white-space:nowrap; }
.lname { font-size:11.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ltot { font-family:var(--mono); font-size:11px; font-weight:600; text-align:right; font-variant-numeric:tabular-nums; }
.tierchip { font-family:var(--mono); font-size:9px; font-weight:600; text-align:center;
  padding:1.5px 0; width:26px; display:inline-block; border:1px solid var(--hairline-2); color:var(--ink-2); }
.tierchip[data-t="1"], .tierchip[data-t="2"] { color:var(--accent); border-color:color-mix(in srgb,var(--accent) 55%,transparent); }

/* 故事矩阵 */
.mrow { display:grid; grid-template-columns:minmax(180px,1fr) 34px minmax(130px,190px) 30px 44px; gap:9px;
  align-items:center; padding:4.5px 0 4.5px 8px; border-left:2px solid transparent;
  border-bottom:1px solid color-mix(in srgb,var(--hairline) 45%,transparent); }
.mrow.syn { border-left-color:var(--accent); }
.mrow .mt { font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.mrow .mt a { text-decoration:none; }
.mrow .mt a:hover { color:var(--accent); }
.mrow .mt small { display:block; font-family:var(--mono); font-size:9px; color:var(--ink-3); }
.mrow .cells i { height:13px; }
.mrow .md { font-family:var(--mono); font-size:13px; font-weight:600; text-align:right; font-variant-numeric:tabular-nums; }
.new-tag { color:var(--st-warning); border:1px solid currentColor; font-size:8.5px; padding:0 3px; margin-left:4px; }
.vel { color:var(--ink-2); margin-left:4px; }
.cons { height:4px; background:var(--surface-2); box-shadow:inset 0 0 0 1px var(--hairline); }
.cons i { display:block; height:100%; }
.sw { width:14px; height:9px; display:inline-block; background:var(--s0); box-shadow:inset 0 0 0 1px var(--hairline); }
${[1,2,3,4,5,6].map(i => `.sw[data-b="${i}"]{background:var(--s${i});box-shadow:none}`).join("")}

/* 网络 */
.net svg { width:100%; height:auto; }
.net text { font-family:var(--mono); font-size:9px; fill:var(--ink-2); paint-order:stroke; stroke:var(--surface); stroke-width:2.5px; }

/* 卡片墙 */
.cardwall { display:grid; grid-template-columns:1fr 1fr; gap:9px; }
.card { border:1px solid var(--hairline-2); padding:10px 12px; text-decoration:none;
  display:flex; flex-direction:column; gap:7px; background:var(--surface-2); }
.card:hover { border-color:var(--accent); }
.card .ct { font-size:12.5px; font-weight:600; line-height:1.4; }
.card .cs { font-size:11.5px; color:var(--ink-2); line-height:1.55; display:-webkit-box;
  -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.card .cm { display:flex; gap:10px; font-family:var(--mono); font-size:9.5px; color:var(--ink-3);
  margin-top:auto; font-variant-numeric:tabular-nums; }

/* 层级/分歧/实体 */
.trow { display:grid; grid-template-columns:30px 1fr 64px; gap:8px; align-items:center; padding:5px 0;
  border-bottom:1px solid color-mix(in srgb,var(--hairline) 45%,transparent); }
.trow .tn { font-size:11px; color:var(--ink-2); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.trow .tv { font-family:var(--mono); font-size:12px; font-weight:600; text-align:right; }
.trow .tv small { color:var(--ink-3); font-weight:400; }
.erow { display:grid; grid-template-columns:16px 14px minmax(90px,1fr) 1fr 30px; gap:7px;
  align-items:center; padding:4px 0; border-bottom:1px solid color-mix(in srgb,var(--hairline) 45%,transparent); }
.erow .i { font-family:var(--mono); font-size:10px; color:var(--ink-3); text-align:right; }
.erow .en { font-size:11.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.erow .ev { font-family:var(--mono); font-size:11px; text-align:right; font-variant-numeric:tabular-nums; }
.dv-r .nm a { text-decoration:none; }

/* 故事详情 */
.title-chan { color:var(--ink); max-width:64ch; white-space:normal; line-height:1.4; }
.back { cursor:pointer; color:var(--accent); text-decoration:none; }
.prose { font-size:14px; line-height:1.95; max-width:78ch; }
.cite { font-family:var(--mono); font-size:9.5px; color:var(--accent); text-decoration:none;
  border:1px solid color-mix(in srgb,var(--accent) 45%,transparent); padding:0 4px; margin:0 2px;
  vertical-align:2px; }
.cite:hover { background:color-mix(in srgb,var(--accent) 18%,transparent); }
.tline { position:relative; }
.tl-e { display:grid; grid-template-columns:92px 1fr; gap:10px; padding:7px 0;
  border-bottom:1px solid color-mix(in srgb,var(--hairline) 45%,transparent); }
.tl-w { font-family:var(--mono); font-size:10.5px; color:var(--accent); font-weight:600; }
.tl-x { font-size:12.5px; line-height:1.6; }
.stance-strip u { display:inline-flex; width:16px; height:11px; align-items:center; justify-content:center;
  font-size:8px; margin-left:1px; }
.ref { display:grid; grid-template-columns:24px 1fr 26px 76px; gap:9px; align-items:baseline;
  padding:6px 0; border-bottom:1px solid color-mix(in srgb,var(--hairline) 45%,transparent); }
.ref:target { background:color-mix(in srgb,var(--accent) 12%,transparent); }
.ref .rn { font-family:var(--mono); font-size:10px; color:var(--ink-2); border:1px solid var(--hairline-2);
  text-align:center; padding:0 3px; }
.ref .rt { font-size:12px; line-height:1.55; }
.ref .rs { font-family:var(--mono); font-size:9px; color:var(--ink-3); text-align:right; line-height:1.5; }
.ref u, .stance-strip u, .dm-r u { text-decoration:none; font-family:var(--mono); font-weight:600; }
.ref u { display:inline-flex; width:22px; height:15px; align-items:center; justify-content:center; font-size:9.5px; }
${[["-2","--div-n2","var(--surface)"],["-1","--div-n1","var(--ink)"],["0","--div-0","var(--ink-2)"],["1","--div-p1","var(--ink)"],["2","--div-p2","var(--surface)"]]
  .map(([v, bg, fg]) => `u[data-v="${v}"]{background:var(${bg});color:${fg};}`).join("")}
.drow { display:grid; grid-template-columns:38px 90px 1fr auto; gap:8px; font-size:12px; padding:2.5px 0; align-items:baseline; }
.drow .dd, .drow .ds { font-family:var(--mono); font-size:9.5px; color:var(--ink-3); }
.drow .dt { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.drow .also { text-decoration:none; }
.ev { display:grid; grid-template-columns:76px 84px 1fr; gap:8px; padding:4.5px 0; font-size:11.5px;
  border-bottom:1px solid color-mix(in srgb,var(--hairline) 45%,transparent); align-items:baseline; }
.ev .evt { font-family:var(--mono); font-size:9.5px; color:var(--ink-3); }
.ev .evk { font-family:var(--mono); font-size:10px; color:var(--accent); }
.ev .evk[data-k="split"] { color:var(--st-warning); }
.ev .evr { color:var(--ink-2); }
@media (max-width:1180px) { .cardwall { grid-template-columns:1fr; }
  .lane { grid-template-columns:26px minmax(90px,120px) 1fr 38px; } }
`;

/* ── 页面组装 ───────────────────────────────────────────── */
const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NewsAssistant · 实时数据总览</title>
<style>${css(CFG)}${extraCss}</style></head>
<body><div class="console">
${overview}
${synStories.map(storySection).join("")}
<footer>
  <b>编码语法</b>：色阶=密度（分位分档） · ▲▼=方向 · 形状=实体类型 · 立场 −2..+2 蓝↔红+数字 · 状态色只表示越阈
  · <b>综述每句的编号是它存在的许可证</b>（点开可见原始断言与来源）
  · 快照 ${esc(SNAP.generated_at)} · na snapshot + build-real.mjs · 全部真实数据
</footer>
<div id="tip" role="status"></div>
</div>
<script>
var views = document.querySelectorAll(".view");
function route() {
  var h = location.hash.slice(1);
  var m = /^s(\\d+)(-r\\d+)?$/.exec(h);
  var target = m ? "s" + m[1] : "overview";
  views.forEach(function (v) { v.hidden = v.id !== target; });
  if (m && m[2]) { var el = document.getElementById(h); if (el) el.scrollIntoView({ block:"center" }); }
  else window.scrollTo(0, 0);
}
addEventListener("hashchange", route); route();
var tip = document.getElementById("tip");
document.querySelectorAll("[data-tip]").forEach(function (el) {
  el.addEventListener("mouseenter", function () { tip.textContent = el.getAttribute("data-tip");
    tip.style.whiteSpace = "normal"; tip.style.maxWidth = "46ch"; tip.classList.add("on"); });
  el.addEventListener("mousemove", function (e) {
    var r = tip.getBoundingClientRect();
    tip.style.left = Math.min(innerWidth - r.width - 10, e.clientX + 12) + "px";
    tip.style.top = Math.min(innerHeight - r.height - 10, e.clientY + 14) + "px"; });
  el.addEventListener("mouseleave", function () { tip.classList.remove("on"); });
});
</script></body></html>`;

writeFileSync(join(OUT, "real.html"), html);
console.log(`real.html: ${SNAP.totals.stories} stories, ${SNAP.totals.synthesized} synthesized, ${(html.length / 1024).toFixed(0)} KB`);
