/* 故事详情页原型 — 生成器
 *
 *   node build-story.mjs   → story-export-controls.html
 *
 * 下钻层级（docs/views.md §5）：全库 → 频道 → **故事页** → 实体页。
 * 频道页负责"定位到值得看的东西"，故事页负责"看透一件事"。
 * 本页是 L2 层 story 状态（event-sourcing）的直接可视化：
 * 事件时间线（按证据层级分泳道）、断言演变、引用与独立性、故事系谱、
 * 以及每句话都带引用标记的 AI 综述 —— 无引用支撑的句子不允许出现。
 *
 * ⚠ 全部数据均为虚构（含引用条目本身），仅用于验证版式与信息架构。
 *   页面几乎全部在生成时渲染为静态 HTML；运行时只有 tooltip 与背景。
 */

import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { css } from "./theme.mjs";
import { STORIES, ASOF } from "./store.mjs";

const OUT = dirname(fileURLToPath(import.meta.url));
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[c]));
const sum = a => a.reduce((x, y) => x + y, 0);
const day = i => { const d = new Date(ASOF); d.setUTCDate(d.getUTCDate() - (29 - i));
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`; };

/* 故事标识色：跨频道故事用中性蓝（与元频道一致），不借用任何单一频道色 */
const CFG = {
  dark:  { accent:"#3987e5", ramp:["#16283f","#1b3a5c","#214d7a","#286098","#2f75b8","#3987e5"] },
  light: { accent:"#2a78d6", ramp:["#d3e4f8","#aecdf2","#86b6ef","#5e9ce4","#3f86d8","#2a78d6"] },
};

/* ═══════════════ 演示数据（虚构） ═══════════════ */

const S = STORIES.find(s => s.t === "芯片出口管制调整");
const STAGE = { 4:"爆发", 3:"升温", 2:"发展", 1:"收敛" };

const STAT = [
  ["阶段", STAGE[S.stage]], ["动量", (S.vel > 0 ? "+" : "") + S.vel + "%"],
  ["报道", "187 篇"], ["独立源", String(S.brd)],
  ["共识度", S.cons + "%"], ["未解", "3"],
];
const CHANNELS_IN = ["AI 产业", "半导体", "地缘政治"];

/* 引用库：每条带证据层级（docs/sources.md）与转述关系 */
const REFS = [
  { id:"R1",  tier:"L5", src:"路透",        date:"7/2",  t:"美拟扩大芯片出口管制，或覆盖推理芯片", copies:112 },
  { id:"R2",  tier:"L5", src:"彭博",        date:"7/2",  t:"管制草案进入部际审查程序", copies:31 },
  { id:"R3",  tier:"L7", src:"官员社媒账号", date:"7/1",  t:"公开活动讲话片段：暗示将扩大覆盖范围" },
  { id:"R4",  tier:"L5", src:"综合媒体×12", date:"7/5",  t:"转述潮（12 篇合并计），无新增事实", of:"R1" },
  { id:"R5",  tier:"L1", src:"联邦公报",    date:"7/18", t:"拟议规则 BIS-2026-xx：出口管制条目修订", anchor:true },
  { id:"R6",  tier:"L2", src:"设备商法说会", date:"7/21", t:"季度电话会 transcript：影响可控，Q4 指引不变" },
  { id:"R7",  tier:"L6", src:"智库报告",    date:"7/25", t:"新规二级效应与贸易转移测算" },
  { id:"R8",  tier:"L5", src:"日经",        date:"7/19", t:"亚洲供应链对规则文本的初步反应", copies:9 },
  { id:"R9",  tier:"L2", src:"行业协会公开信", date:"7/11", t:"致商务部：请求缩小拟议覆盖范围" },
  { id:"R10", tier:"L5", src:"金融时报",    date:"7/22", t:"分析：「指引不变」成立的三个前提" },
  { id:"R11", tier:"L5", src:"当地语种媒体", date:"7/25", t:"豁免条款执行细节遭质疑" },
  { id:"R12", tier:"L4", src:"技术博客 / arXiv", date:"7/9", t:"推理芯片性能阈值的技术口径讨论" },
];

/* 事件时间线：day = 0–29 的索引；lane 按证据层级分组（不是按主题） */
const LANES = [
  { id:0, l:"L1 / L2 · 官方与当事方" },
  { id:1, l:"L4–L6 · 媒体与分析" },
  { id:2, l:"L7 · 社群" },
];
const EVENTS = [
  { d:3,  lane:2, t:"官员公开活动暗示将扩大管制范围", refs:["R3"], dy:-1 },
  { d:4,  lane:1, t:"两家通讯社独立报道草案进入部际审查", refs:["R1","R2"], dy:-1 },
  { d:7,  lane:1, t:"转述潮：12 家媒体跟进，无新增事实", refs:["R4"], dy:1 },
  { d:11, lane:1, t:"技术社区讨论性能阈值口径", refs:["R12"], dy:-1, minor:true },
  { d:13, lane:0, t:"行业协会致信商务部请求缩小范围", refs:["R9"], dy:-1 },
  { d:20, lane:0, t:"拟议规则刊出联邦公报：范围小于传闻", refs:["R5"], anchor:true, dy:1 },
  { d:23, lane:0, t:"设备商法说会：影响可控，Q4 指引不变", refs:["R6"], dy:-1 },
  { d:24, lane:1, t:"两家媒体质疑「指引不变」的前提", refs:["R10","R8"], dy:1, minor:true },
  { d:27, lane:1, t:"智库测算二级效应；豁免条款可执行性遭质疑", refs:["R7","R11"], dy:-1 },
];
const RUMOR_SPAN = { from:4, to:20, label:"传闻 → 官方文本 · 16 天" };

/* 断言演变：events = (day, 信源, 立场)；flip 标记改口 */
const CLAIM_TRACKS = [
  { c:"新规将覆盖推理芯片", state:"已收敛：未按传闻口径纳入",
    ev:[[4,"路透",1],[4,"The Information",2],[7,"彭博",1],[13,"行业协会",-1],[20,"联邦公报",-2],[21,"路透",-1],[23,"金融时报",-1]],
    chips:["The Information 首报 7/2","路透 + → − 7/21 ↺ 改口","联邦公报 ✕ 7/18（L1 锚点）"] },
  { c:"覆盖范围包括成熟制程设备", state:"已证伪（对照 L1 文本）",
    ev:[[4,"The Information",1],[7,"华尔街日报",1],[20,"联邦公报",-2],[21,"彭博",-2]],
    chips:["传闻期存活 16 天","被 R5 文本直接否定"] },
  { c:"对设备商 Q4 出货影响可控", state:"分歧持续",
    ev:[[23,"设备商",2],[23,"路透",0],[24,"金融时报",-1],[27,"智库",-1]],
    chips:["当事方自述 ++（利益相关）","分析侧 − 占多数"] },
  { c:"豁免条款具备可执行性", state:"争议中 · 等待实施细则",
    ev:[[20,"联邦公报",1],[25,"金融时报",-1],[27,"当地语种媒体",-2]],
    chips:["官方文本含糊","执行细则未出"] },
];

const ENTS = [
  ["美商务部 BIS","机构 · 发起方"],["NVIDIA","公司 · 受影响"],["AMD","公司 · 受影响"],
  ["台积电","公司 · 间接暴露"],["行业协会","机构 · 游说方"],["欧盟委员会","机构 · 观察方"],
];

const OPEN_Q = [
  { q:"豁免条款的执行细则何时公布、由谁解释？", w:"等待 BIS 实施指引 / FAQ", age:7 },
  { q:"性能阈值的技术口径是否与技术社区讨论一致？", w:"等待规则附件的参数定义", age:9 },
  { q:"二级效应的贸易转移量，能否从镜像贸易数据估计？", w:"可自行处理：用双边贸易统计的镜像差额构造估计", age:16 },
];

const LOG = [
  ["6/28","created · 从上一轮出口管制故事延续建档"],
  ["7/5","absorbed · 吸收「设备许可传闻」（3 篇）"],
  ["7/12","split · 关键矿产相关讨论独立成新故事 →「关键矿产出口配额」"],
  ["7/18","anchor · L1 文本落地，故事进入证实期"],
  ["7/27","updated · 最近一次状态快照"],
];

/* AI 综述：每句必须带引用标记；无引用支撑的句子不允许出现 */
const SYNTH = [
  ["7 月初，两家通讯社独立报道美国拟扩大芯片出口管制、可能覆盖推理芯片。",["R1","R2"]],
  ["传闻期持续 16 天，其间新增报道以转述为主：187 篇中 81% 可溯源到三个独立首发。",["R4"]],
  ["7/18 拟议规则刊出联邦公报，覆盖范围小于传闻，推理芯片未按传闻口径纳入。",["R5"]],
  ["行业协会此前已致信请求缩小范围，与最终文本方向一致。",["R9"]],
  ["设备商在法说会上称影响可控、维持 Q4 指引，但两家媒体与一家智库对其前提提出质疑。",["R6","R10","R7"]],
  ["当前主要分歧集中在豁免条款的可执行性，等待 BIS 实施细则。",["R11"]],
];

/* ═══════════════ 渲染（全部生成时完成） ═══════════════ */

function spark(data, w, h) {
  const lo = Math.min(...data), hi = Math.max(...data), sp = hi - lo || 1;
  const p = data.map((v, i) => `${i ? "L" : "M"}${(2 + i * (w - 4) / (data.length - 1)).toFixed(1)} ${(h - 2 - (v - lo) / sp * (h - 4)).toFixed(1)}`).join(" ");
  return `<svg viewBox="0 0 ${w} ${h}" aria-hidden="true">
    <path d="${p} L${w - 2} ${h} L2 ${h} Z" fill="var(--accent)" opacity=".22"></path>
    <path d="${p}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"></path></svg>`;
}

const cite = ids => ids.map(id =>
  `<a class="cite" href="#ref-${id}">${id}</a>`).join("");

function evTimeline() {
  const W = 1200, H = 260, L = 150, R = 24, axY = 226;
  const laneY = [64, 130, 188];
  const xs = i => L + i * (W - L - R) / 29;
  const lanes = LANES.map((l, i) =>
    `<text x="10" y="${laneY[i] + 3}" font-family="var(--mono)" font-size="9.5" fill="var(--ink-3)">${esc(l.l)}</text>
     <line x1="${L - 8}" y1="${laneY[i]}" x2="${W - R}" y2="${laneY[i]}" stroke="var(--hairline)" stroke-width="1"></line>`).join("");
  const span = `<rect x="${xs(RUMOR_SPAN.from).toFixed(1)}" y="30" width="${(xs(RUMOR_SPAN.to) - xs(RUMOR_SPAN.from)).toFixed(1)}" height="${axY - 40}"
      fill="var(--accent)" opacity=".06"></rect>
    <text x="${((xs(RUMOR_SPAN.from) + xs(RUMOR_SPAN.to)) / 2).toFixed(1)}" y="24" text-anchor="middle"
      font-family="var(--mono)" font-size="9.5" fill="var(--ink-3)">${esc(RUMOR_SPAN.label)}</text>`;
  const evs = EVENTS.map(e => {
    const x = xs(e.d), y = laneY[e.lane], r = e.anchor ? 6.5 : e.minor ? 3.5 : 5;
    /* dy<0（标签在点上方）时标题在外、引用行贴近点上沿，避免引用行压在圆点上 */
    const ty = e.dy < 0 ? y - (r + 18) : y + r + 14;
    const ry = e.dy < 0 ? y - (r + 6) : ty + 12;
    const anchor = e.d > 24 ? "end" : e.d < 3 ? "start" : "middle";
    return `<g tabindex="0" data-tip="${esc(day(e.d))} · ${esc(e.t)}|引用 ${e.refs.join(" ")}">
      ${e.anchor ? `<circle cx="${x.toFixed(1)}" cy="${y}" r="10" fill="none" stroke="var(--accent)" stroke-width="1.5" opacity=".55"></circle>` : ""}
      <circle cx="${x.toFixed(1)}" cy="${y}" r="${r}" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"></circle>
      <text x="${x.toFixed(1)}" y="${ty}" text-anchor="${anchor}" font-family="var(--sans)" font-size="10.5"
        fill="${e.minor ? "var(--ink-3)" : "var(--ink-2)"}">${esc(e.t)}</text>
      <text x="${x.toFixed(1)}" y="${ry}" text-anchor="${anchor}" font-family="var(--mono)" font-size="9"
        fill="var(--ink-3)">${e.refs.map(r2 => "[" + r2 + "]").join("")}</text></g>`;
  }).join("");
  const ticks = [0, 7, 14, 21, 29].map(i =>
    `<text x="${xs(i).toFixed(1)}" y="${axY + 16}" text-anchor="middle" font-family="var(--mono)"
      font-size="9" fill="var(--ink-3)">${day(i)}</text>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img"
    aria-label="事件时间线：按证据层级分为官方与当事方、媒体与分析、社群三条泳道；阴影区为传闻到官方文本的时差">
    ${span}${lanes}
    <line x1="${L - 8}" y1="${axY}" x2="${W - R}" y2="${axY}" stroke="var(--hairline-2)" stroke-width="1"></line>
    ${ticks}${evs}</svg>`;
}

function claimTracks() {
  const B = v => v >= 1.5 ? 2 : v >= .5 ? 1 : v > -.5 ? 0 : v > -1.5 ? -1 : -2;
  const G = { "2":"++", "1":"+", "0":"·", "-1":"−", "-2":"✕" };
  return CLAIM_TRACKS.map(c => {
    const byDay = {};
    c.ev.forEach(([d, s, v]) => (byDay[d] = byDay[d] || []).push([s, v]));
    const cells = Array.from({ length: 30 }, (_, i) => {
      if (!byDay[i]) return `<u data-v="x"></u>`;
      const m = B(sum(byDay[i].map(e => e[1])) / byDay[i].length);
      return `<u data-v="${m}" tabindex="0" data-tip="${esc(day(i))} · ${esc(c.c)}|${
        byDay[i].map(([s, v]) => esc(s) + " " + G[v]).join("|")}">${G[m]}</u>`;
    }).join("");
    return `<div class="ct">
      <div class="cth"><b>${esc(c.c)}</b><span>${esc(c.state)}</span></div>
      <div class="cev">${cells}</div>
      <div class="chips">${c.chips.map(x => `<u>${esc(x)}</u>`).join("")}</div>
    </div>`;
  }).join("") + `<div class="dm-lg">立场 <i style="background:var(--div-n2)"></i>否认 ✕
    <i style="background:var(--div-n1)"></i>质疑 − <i style="background:var(--div-0)"></i>未表态 ·
    <i style="background:var(--div-p1)"></i>支持 + <i style="background:var(--div-p2)"></i>强支持 ++
    <span style="margin-left:6px">空格 = 当日无信源表态；同日多源取均值，逐源立场见 tooltip</span></div>`;
}

function refList() {
  const roots = REFS.filter(r => r.copies);
  const copyTotal = sum(roots.map(r => r.copies));
  const maxC = Math.max(...roots.map(r => r.copies));
  const synd = `<div class="synd">
    <div class="eyebrow" style="margin-bottom:6px">独立性 · 转述溯源</div>
    <div style="font-size:12px;margin-bottom:8px">187 篇报道 → <b>${S.brd} 个独立源</b>；
      ${copyTotal} 篇（${Math.round(copyTotal / 187 * 100)}%）可溯源到 ${roots.length} 个首发：</div>
    ${roots.map(r => `<div class="sr"><span class="sn">${esc(r.src)} <i>[${r.id}]</i></span>
      <span class="meter" style="flex:1"><i style="width:${(r.copies / maxC * 100).toFixed(0)}%;background:var(--accent-2)"></i></span>
      <span class="sc">${r.copies} 篇转述</span></div>`).join("")}
  </div>`;
  return synd + `<ol class="refs">` + REFS.map(r =>
    `<li id="ref-${r.id}"><span class="tier" data-t="${r.tier}">${r.tier}</span>
      <span class="rid">[${r.id}]</span>
      <span class="rb"><b>${esc(r.src)}</b> · ${r.date} — ${esc(r.t)}${
        r.of ? ` <em>转述 ${r.of}</em>` : ""}${r.anchor ? ` <em class="anch">锚点</em>` : ""}</span></li>`
  ).join("") + `</ol>`;
}

/* ═══════════════ 页面 ═══════════════ */

const STORY_CSS = `
.sh { display:flex; flex-wrap:wrap; align-items:center; gap:14px; padding:16px;
  border-bottom:1px solid var(--hairline-2); background:var(--surface); }
.sh h1 { margin:0; font-size:19px; font-weight:600; letter-spacing:.01em; }
.sh .crumb { font-family:var(--mono); font-size:10px; color:var(--ink-3); letter-spacing:.1em; width:100%; }
.sh .chipс, .sh .inch { display:flex; gap:5px; }
.sh .inch u { text-decoration:none; font-family:var(--mono); font-size:9.5px; color:var(--accent);
  border:1px solid color-mix(in srgb,var(--accent) 45%,transparent); padding:1px 6px; }
.sh .spark { margin-left:auto; width:220px; }
.sh .spark svg { display:block; width:100%; height:34px; }
.stats { display:grid; grid-template-columns:repeat(6,1fr); border-bottom:1px solid var(--hairline-2);
  background:var(--surface); }
.stats div { padding:9px 14px; border-right:1px solid var(--hairline); }
.stats div:last-child { border-right:0; }
.stats .k { font-family:var(--mono); font-size:9.5px; letter-spacing:.12em; color:var(--ink-3);
  text-transform:uppercase; }
.stats .v { font-family:var(--mono); font-size:17px; font-weight:600; }
.ev > svg { display:block; width:100%; height:auto; }

.ct { padding:9px 0; border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent); }
.cth { display:flex; align-items:baseline; gap:10px; margin-bottom:5px; }
.cth b { font-size:12.5px; font-weight:500; }
.cth span { font-family:var(--mono); font-size:9.5px; color:var(--ink-3); margin-left:auto; }
.cev { display:grid; grid-template-columns:repeat(30,1fr); gap:2px; margin-bottom:6px; }
.cev u { display:flex; align-items:center; justify-content:center; height:17px; text-decoration:none;
  font-family:var(--mono); font-size:9.5px; font-weight:600; color:var(--ink); }
.cev u[data-v="x"]  { background:var(--surface-2); box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--hairline) 70%,transparent); }
.cev u[data-v="2"]  { background:var(--div-p2); color:var(--surface); }
.cev u[data-v="1"]  { background:var(--div-p1); }
.cev u[data-v="0"]  { background:var(--div-0); color:var(--ink-2); }
.cev u[data-v="-1"] { background:var(--div-n1); }
.cev u[data-v="-2"] { background:var(--div-n2); color:var(--surface); }
.chips { display:flex; flex-wrap:wrap; gap:4px; }
.chips u { text-decoration:none; font-family:var(--mono); font-size:9.5px; padding:2px 6px;
  border:1px solid var(--hairline-2); color:var(--ink-2); }

.synd { padding-bottom:10px; margin-bottom:10px; border-bottom:1px solid var(--hairline); }
.sr { display:flex; align-items:center; gap:8px; padding:3px 0; }
.sr .sn { font-size:11.5px; width:150px; flex:none; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.sr .sn i { font-style:normal; font-family:var(--mono); font-size:9px; color:var(--ink-3); }
.sr .sc { font-family:var(--mono); font-size:10px; color:var(--ink-3); flex:none; font-variant-numeric:tabular-nums; }
.refs { margin:0; padding:0; list-style:none; }
.refs li { display:flex; gap:8px; align-items:baseline; padding:5px 0;
  border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent); }
.refs li:target { background:color-mix(in srgb,var(--accent) 12%,transparent); outline:1px solid var(--accent); }
.tier { font-family:var(--mono); font-size:9px; font-weight:600; border:1px solid; padding:1px 4px; flex:none; }
.tier[data-t="L1"] { color:var(--accent); border-color:var(--accent); }
.tier[data-t="L2"] { color:var(--ink); border-color:var(--ink-2); }
.tier[data-t="L4"], .tier[data-t="L5"], .tier[data-t="L6"] { color:var(--ink-2); border-color:var(--hairline-2); }
.tier[data-t="L7"] { color:var(--ink-3); border-color:var(--hairline); }
.refs .rid { font-family:var(--mono); font-size:10px; color:var(--ink-3); flex:none; }
.refs .rb { font-size:11.5px; min-width:0; }
.refs .rb em { font-style:normal; font-family:var(--mono); font-size:9px; color:var(--ink-3);
  border:1px solid var(--hairline-2); padding:0 4px; margin-left:4px; }
.refs .rb em.anch { color:var(--accent); border-color:var(--accent); }

.ents { display:flex; flex-wrap:wrap; gap:6px; }
.ents u { text-decoration:none; border:1px solid var(--hairline-2); padding:5px 9px; }
.ents u b { display:block; font-size:12px; font-weight:500; }
.ents u small { font-family:var(--mono); font-size:9px; color:var(--ink-3); }
.log { margin:0; padding:0; list-style:none; }
.log li { display:flex; gap:10px; padding:6px 0; font-size:11.5px;
  border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent); }
.log .d { font-family:var(--mono); font-size:10px; color:var(--ink-3); flex:none; width:34px;
  font-variant-numeric:tabular-nums; }
.log b { font-family:var(--mono); font-weight:600; font-size:10px; color:var(--accent); }

.synth p { margin:0 0 8px; font-size:13.5px; line-height:1.8; max-width:72ch; }
a.cite { font-family:var(--mono); font-size:9.5px; color:var(--accent); text-decoration:none;
  border:1px solid color-mix(in srgb,var(--accent) 45%,transparent); padding:0 4px; margin-left:3px;
  vertical-align:2px; }
a.cite:hover { background:color-mix(in srgb,var(--accent) 15%,transparent); }
.synth .rule { font-family:var(--mono); font-size:10px; color:var(--ink-3); margin-top:10px;
  padding-top:9px; border-top:1px solid var(--hairline); }
`;

const html = `<title>NewsAssistant · 故事 · ${esc(S.t)}</title>

<style>${css(CFG)}${STORY_CSS}</style>

<canvas id="field" aria-hidden="true"></canvas>

<div class="console">
  <div class="rail">
    <div class="brand"><span class="dot"></span><b>NEWSASSISTANT</b></div>
    <div class="chans"><button class="chan" aria-current="true">故事详情</button></div>
    <div class="railpad"></div>
    <span class="mock">示例数据 · 布局原型</span>
  </div>

  <div class="sh">
    <span class="crumb">全库 → 频道 → 故事 · story_id: st_export_ctrl_2026</span>
    <h1>${esc(S.t)}</h1>
    <span class="inch">${CHANNELS_IN.map(c => `<u>也在 ${c}</u>`).join("")}</span>
    <span class="spark">${spark(S.d, 220, 34)}</span>
  </div>
  <div class="stats">${STAT.map(([k, v]) =>
    `<div><div class="k">${k}</div><div class="v">${v}</div></div>`).join("")}</div>

  <div class="grid">
    <section class="panel c12">
      <header><h2>事件时间线</h2>
        <span class="note">泳道 = 证据层级 · 阴影区 = 传闻到官方文本的时差 · ◎ = L1 锚点</span></header>
      <div class="body"><div class="ev">${evTimeline()}</div></div>
    </section>

    <section class="panel c7">
      <header><h2>断言演变</h2><span class="note">谁先说 · 谁改口 · 何时收敛</span></header>
      <div class="body">${claimTracks()}</div>
    </section>

    <section class="panel c5">
      <header><h2>引用 · 独立性</h2><span class="note">${REFS.length} 条一手引用（转述合并计）</span></header>
      <div class="body">${refList()}</div>
    </section>

    <section class="panel c4">
      <header><h2>参与实体</h2><span class="note">通往实体页</span></header>
      <div class="body"><div class="ents">${ENTS.map(([n, r]) =>
        `<u tabindex="0"><b>${esc(n)}</b><small>${esc(r)}</small></u>`).join("")}</div></div>
    </section>

    <section class="panel c4">
      <header><h2>未解问题</h2><span class="note">${OPEN_Q.length} 项</span></header>
      <div class="body"><div class="oq"><ul>${OPEN_Q.map(q =>
        `<li><div class="q">${esc(q.q)}</div><div class="m"><span><b>等待</b> ${esc(q.w)}</span>
         <span class="age">悬置 ${q.age}d</span></div></li>`).join("")}</ul></div></div>
    </section>

    <section class="panel c4">
      <header><h2>故事系谱 · 事件日志</h2><span class="note">event-sourcing 摘录</span></header>
      <div class="body"><ul class="log">${LOG.map(([d, t]) => {
        const [k, rest] = t.split(" · ");
        return `<li><span class="d">${d}</span><span><b>${k}</b> · ${esc(rest)}</span></li>`;
      }).join("")}</ul></div>
    </section>

    <section class="panel c12">
      <header><h2>综述</h2><span class="note">每句话均有引用支撑 · 点击标记跳转引用</span></header>
      <div class="body"><div class="synth">
        ${SYNTH.map(([t, ids]) => `<p>${esc(t)}${cite(ids)}</p>`).join("")}
        <div class="rule">规则：无引用支撑的句子不允许出现在综述中。引用标记 → 引用面板（含证据层级与转述关系）。</div>
      </div></div>
    </section>
  </div>

  <footer>
    <b>这是一份布局原型。</b>本页全部内容 —— 包括事件、断言、立场、<b>以及引用条目本身</b> —— 均为演示用的<b>虚构数据</b>，不指向任何真实报道或文件。<br>
    架构说明 — 故事页是 L2 层 story 状态（event-sourcing）的直接可视化：时间线按证据层级分泳道（传闻→证实的时差本身是信息）；断言演变是分歧矩阵的时间维展开；独立性面板做转述溯源（187 篇 ≠ 187 个信源）。
  </footer>
</div>

<div id="tip" role="status" aria-live="polite"></div>

<script>
(() => {
"use strict";
const tip = document.querySelector("#tip");
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[c]));
const show = e => {
  const el = e.target.closest("[data-tip]");
  if (!el) return;
  tip.innerHTML = el.dataset.tip.split("|").map(esc).join("<br>");
  tip.classList.add("on");
  const r = el.getBoundingClientRect(), b = tip.getBoundingClientRect();
  tip.style.left = Math.max(6, Math.min(innerWidth - b.width - 6, r.left + r.width / 2 - b.width / 2)) + "px";
  tip.style.top = (r.top - b.height - 7 < 6 ? r.bottom + 7 : r.top - b.height - 7) + "px";
};
document.body.addEventListener("mouseover", show);
document.body.addEventListener("mouseout", () => tip.classList.remove("on"));
document.body.addEventListener("focusin", show);
document.body.addEventListener("focusout", () => tip.classList.remove("on"));

const D = ${JSON.stringify(S.d)};
const cv = document.querySelector("#field"), ctx = cv.getContext("2d");
const draw = () => {
  const dpr = Math.min(devicePixelRatio || 1, 2), w = innerWidth, h = innerHeight;
  cv.width = w * dpr; cv.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  ctx.globalAlpha = .05;
  for (let x = 18; x < w; x += 34) for (let y = 18; y < h; y += 34) ctx.fillRect(x, y, 1, 1);
  const mx = Math.max(...D), base = h - 4;
  ctx.globalAlpha = .07; ctx.beginPath(); ctx.moveTo(0, base);
  D.forEach((v, i) => ctx.lineTo(i * w / (D.length - 1), base - v / mx * h * .42));
  ctx.lineTo(w, base); ctx.closePath(); ctx.fill(); ctx.globalAlpha = 1;
};
draw();
let t; addEventListener("resize", () => { clearTimeout(t); t = setTimeout(draw, 120); });
})();
</script>
`;

writeFileSync(join(OUT, "story-export-controls.html"), html);
console.log("✓ story-export-controls.html");
