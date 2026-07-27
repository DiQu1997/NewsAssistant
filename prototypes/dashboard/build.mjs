/* NewsAssistant 控制台原型 — 生成器
 *
 * 四个频道共用一套版式与编码规则，各自替换标识色、数据与领域专属面板。
 * 布局是要反复迭代的，所以模板只此一份：改这里，四份一起变。
 *
 *   node build.mjs        → 输出 ai-industry.html / semiconductor.html /
 *                           macro-markets.html / geopolitics.html
 *
 * 全部数据均为虚构的演示数据，仅用于验证版式与视觉编码。
 */

import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const OUT = dirname(fileURLToPath(import.meta.url));

/* ════════════════════════════ 样式 ════════════════════════════ */

const css = c => `
:root {
  color-scheme: dark;
  --ground:#0b0e13; --surface:#12161d; --surface-2:#171c24;
  --hairline:#212832; --hairline-2:#2c3441;
  --ink:#e8edf4; --ink-2:#93a1b1; --ink-3:#64717f;

  --accent:${c.dark.accent}; --accent-2:${c.dark.ramp[3]};
  --s0:#12161d; ${c.dark.ramp.map((h, i) => `--s${i + 1}:${h};`).join(" ")}

  --div-n2:#3987e5; --div-n1:#2a5a8d; --div-0:#383835; --div-p1:#8f4444; --div-p2:#e66767;
  --st-good:#0ca30c; --st-warning:#fab219; --st-serious:#ec835a; --st-critical:#d03b3b;
  --neutral:#6b7480;
  /* 堆叠条形的区域色：仅相邻两两需可分辨，已按相邻配对校验通过 */
  --gr-1:#3987e5; --gr-2:#d95926; --gr-3:#9085e9;
  /* 折线组：三条同轴指标线，已按全对配对校验通过，另加终点直标 */
  --ln-1:#3987e5; --ln-2:#d95926; --ln-3:#199e70;

  --mono: ui-monospace, "SF Mono", "JetBrains Mono", "Cascadia Mono", Menlo, Consolas, monospace;
  --sans: system-ui, -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}
@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) {${lightTokens(c)}} }
:root[data-theme="light"] {${lightTokens(c)}}

* { box-sizing:border-box; }
body { margin:0; background:var(--ground); color:var(--ink);
  font-family:var(--sans); font-size:13px; line-height:1.45; -webkit-font-smoothing:antialiased; }
#field { position:fixed; inset:0; width:100%; height:100%; z-index:0; pointer-events:none; opacity:.5; }
.console { position:relative; z-index:1; display:flex; flex-direction:column; min-height:100vh; }
.mono { font-family:var(--mono); }
.eyebrow { font-family:var(--mono); font-size:10px; letter-spacing:.13em; text-transform:uppercase;
  color:var(--ink-3); font-weight:500; }
:focus-visible { outline:2px solid var(--accent); outline-offset:1px; }
[hidden] { display:none !important; }

/* ── 顶栏 ── */
.rail { display:flex; align-items:stretch; flex-wrap:wrap;
  border-bottom:1px solid var(--hairline-2); background:var(--surface); }
.brand { display:flex; align-items:center; gap:10px; padding:10px 16px; border-right:1px solid var(--hairline); }
.brand b { font-family:var(--mono); font-size:12px; letter-spacing:.16em; font-weight:600; }
.brand .dot { width:7px; height:7px; background:var(--accent); }
.chans { display:flex; }
.chan { font-family:var(--mono); font-size:11px; letter-spacing:.07em; padding:10px 15px;
  color:var(--ink-3); border:0; border-right:1px solid var(--hairline);
  display:flex; align-items:center; background:none; cursor:default; }
.chan[aria-current="true"] { color:var(--ink); background:var(--surface-2); box-shadow:inset 0 -2px 0 var(--accent); }
.railpad { flex:1; }
.mock { align-self:center; margin-right:12px; font-family:var(--mono); font-size:10px;
  letter-spacing:.11em; color:var(--st-warning); border:1px solid currentColor; padding:3px 8px; }
.status { display:flex; flex-wrap:wrap; border-bottom:1px solid var(--hairline-2); background:var(--surface-2); }
.status div { padding:7px 16px; border-right:1px solid var(--hairline);
  font-family:var(--mono); font-size:11px; color:var(--ink-2); }
.status b { color:var(--ink); font-weight:600; font-variant-numeric:tabular-nums; }
.status .live { color:var(--st-good); }

/* ── 数值源带 ── */
.sensors { display:grid; grid-template-columns:repeat(6,1fr);
  border-bottom:1px solid var(--hairline-2); background:var(--surface); }
.sensor { padding:11px 14px 9px; border-right:1px solid var(--hairline);
  display:flex; flex-direction:column; gap:5px; min-width:0; }
.sensor:last-child { border-right:0; }
.sensor .lbl { display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.sensor .val { font-family:var(--mono); font-size:19px; font-weight:600; letter-spacing:-.01em; }
.sensor .dl { font-family:var(--mono); font-size:11px; font-variant-numeric:tabular-nums; white-space:nowrap; }
.sensor > svg { display:block; width:100%; height:22px; }
/* 方向由字符标记承载，不用颜色 —— 「报道量上升」并不等于「好」，
   把 good/critical 状态色借给方向指示会误导。状态色只留给越阈提示。 */
.up, .down { color:var(--ink); } .flat { color:var(--ink-3); }
em.ar { font-style:normal; color:var(--ink-3); font-size:.86em; padding-right:1px; }

/* ── 面板骨架 ── */
.grid { display:grid; grid-template-columns:repeat(12,1fr); flex:1; align-content:start; }
.panel { border-right:1px solid var(--hairline); border-bottom:1px solid var(--hairline);
  background:var(--surface); display:flex; flex-direction:column; min-width:0; }
.panel > header { display:flex; align-items:center; gap:10px; padding:9px 14px;
  border-bottom:1px solid var(--hairline); background:var(--surface-2); }
.panel > header h2 { margin:0; font-family:var(--mono); font-size:11px; letter-spacing:.11em;
  text-transform:uppercase; font-weight:600; }
.panel > header .note { margin-left:auto; font-family:var(--mono); font-size:10px;
  color:var(--ink-3); letter-spacing:.05em; }
.body { padding:12px 14px; overflow:auto; flex:1; }
.c3{grid-column:span 3} .c4{grid-column:span 4} .c5{grid-column:span 5}
.c6{grid-column:span 6} .c7{grid-column:span 7} .c8{grid-column:span 8} .c12{grid-column:span 12}

/* ── 故事热力带 ── */
.hs-head, .hs-row { display:grid; grid-template-columns:minmax(168px,1.5fr) minmax(210px,3fr) 196px;
  gap:12px; align-items:center; }
.hs-head { padding-bottom:6px; border-bottom:1px solid var(--hairline); margin-bottom:4px; }
.hs-head span { font-family:var(--mono); font-size:9.5px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--ink-3); }
.hs-head .mx { display:flex; justify-content:space-between; }
.hs-head .mt { display:grid; grid-template-columns:42px 50px 28px 1fr; gap:7px; white-space:nowrap; }
.hs-row { padding:3px 0; border-bottom:1px solid color-mix(in srgb, var(--hairline) 55%, transparent); }
.hs-lab { display:flex; align-items:center; gap:8px; min-width:0; }
.hs-title { font-size:12.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.stage { font-family:var(--mono); font-size:9px; letter-spacing:.06em; padding:2px 5px;
  white-space:nowrap; border:1px solid; }
.stage[data-s="4"] { color:var(--s6); border-color:var(--s6); background:color-mix(in srgb, var(--s6) 14%, transparent); }
.stage[data-s="3"] { color:var(--s5); border-color:color-mix(in srgb, var(--s5) 65%, transparent); }
.stage[data-s="2"] { color:var(--ink-2); border-color:var(--hairline-2); }
.stage[data-s="1"] { color:var(--ink-3); border-color:var(--hairline); }
.cells { display:grid; grid-template-columns:repeat(30,1fr); gap:2px; }
.cells i { display:block; height:15px; background:var(--s0);
  box-shadow:inset 0 0 0 1px color-mix(in srgb, var(--hairline) 70%, transparent); }
${[1,2,3,4,5,6].map(i => `.cells i[data-b="${i}"]{background:var(--s${i});box-shadow:none}`).join("\n")}
.hs-met { display:grid; grid-template-columns:42px 50px 28px 1fr; gap:7px; align-items:center;
  font-family:var(--mono); font-size:11px; font-variant-numeric:tabular-nums; }
.hs-met .vol { text-align:right; } .hs-met .brd { color:var(--ink-3); text-align:right; }
.meter { height:5px; background:var(--surface-2); box-shadow:inset 0 0 0 1px var(--hairline); }
.meter i { display:block; height:100%; }
.hs-foot { display:flex; align-items:center; gap:14px; flex-wrap:wrap;
  margin-top:10px; padding-top:9px; border-top:1px solid var(--hairline); }
.scale { display:flex; align-items:center; gap:5px; font-family:var(--mono); font-size:10px; color:var(--ink-3); }
.scale i { width:14px; height:9px; display:block; }
table.tv { width:100%; border-collapse:collapse; font-family:var(--mono); font-size:11px;
  font-variant-numeric:tabular-nums; }
table.tv th, table.tv td { text-align:right; padding:4px 7px; border-bottom:1px solid var(--hairline); white-space:nowrap; }
table.tv th { color:var(--ink-3); font-weight:500; font-size:10px; letter-spacing:.06em; text-transform:uppercase; }
table.tv td:first-child, table.tv th:first-child { text-align:left; font-family:var(--sans); }
.toggle { font-family:var(--mono); font-size:10px; letter-spacing:.07em; color:var(--ink-2);
  background:none; border:1px solid var(--hairline-2); padding:3px 8px; cursor:pointer; }
.toggle:hover { color:var(--ink); border-color:var(--accent); }

/* ── 动量榜 ── */
.vt { display:grid; grid-template-columns:1fr 68px 70px; gap:9px; align-items:center;
  padding:8px 0 8px 9px; border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent);
  border-left:2px solid transparent; }
.vt[data-flag="surge"] { border-left-color:var(--st-critical); }
.vt[data-flag="warn"]  { border-left-color:var(--st-warning); }
.vt .nm { font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.vt .nm small { display:block; font-family:var(--mono); font-size:9.5px; color:var(--ink-3); letter-spacing:.04em; }
.vt .pc { font-family:var(--mono); font-size:15px; font-weight:600; text-align:right;
  font-variant-numeric:tabular-nums; }
.vt svg { display:block; width:70px; height:24px; }

/* ── 分歧矩阵 ── */
.dm-h, .dm-r { display:grid; grid-template-columns:1fr repeat(7,22px) 42px; gap:3px; align-items:center; }
.dm-h { padding-bottom:6px; border-bottom:1px solid var(--hairline); margin-bottom:5px; }
.dm-h span { font-family:var(--mono); font-size:9px; color:var(--ink-3); text-align:center; letter-spacing:.03em; }
.dm-h span:first-child { text-align:left; letter-spacing:.1em; text-transform:uppercase; }
.dm-h span:last-child { text-align:right; }
.dm-r { padding:5px 0; border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent); }
.dm-r .cl { min-width:0; }
.dm-r .cl b { display:block; font-size:12px; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.dm-r .cl small { font-family:var(--mono); font-size:9.5px; color:var(--ink-3); }
.dm-r u { display:flex; align-items:center; justify-content:center; height:19px; text-decoration:none;
  font-family:var(--mono); font-size:10px; font-weight:600; color:var(--ink); }
.dm-r u[data-v="2"]  { background:var(--div-p2); color:var(--surface); }
.dm-r u[data-v="1"]  { background:var(--div-p1); }
.dm-r u[data-v="0"]  { background:var(--div-0); color:var(--ink-2); }
.dm-r u[data-v="-1"] { background:var(--div-n1); }
.dm-r u[data-v="-2"] { background:var(--div-n2); color:var(--surface); }
.dm-r .sc { font-family:var(--mono); font-size:12px; text-align:right;
  font-variant-numeric:tabular-nums; font-weight:600; }
.dm-lg { display:flex; align-items:center; gap:4px; margin-top:10px; padding-top:9px;
  border-top:1px solid var(--hairline); font-family:var(--mono); font-size:10px;
  color:var(--ink-3); flex-wrap:wrap; }
.dm-lg i { width:15px; height:9px; display:block; }

/* ── 未解问题 ── */
.oq ul { margin:0; padding:0; }
.oq li { list-style:none; padding:9px 0; border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent);
  break-inside:avoid; }
.oq .q { font-size:12.5px; margin-bottom:4px; }
.oq .m { display:flex; gap:9px; flex-wrap:wrap; font-family:var(--mono); font-size:9.5px; color:var(--ink-3); }
.oq .m b { color:var(--ink-2); font-weight:500; }
.oq .age { color:var(--st-warning); }
.oq.wide ul { columns:3; column-gap:26px; }

/* ── 领域专属面板的共用零件 ── */
.tier { padding:8px 0; border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent); }
.tier .th { display:flex; align-items:baseline; gap:8px; margin-bottom:6px; }
.tier .th b { font-size:12px; font-weight:500; }
/* 只把最后一个 span 推到右侧 —— 不限定 :last-child 会连同等级标签一起推走 */
.tier .th > span:last-child { font-family:var(--mono); font-size:9.5px; color:var(--ink-3);
  margin-left:auto; font-variant-numeric:tabular-nums; }
.cor .tier { padding:5px 0; }
.cor .note { font-family:var(--mono); font-size:10px; color:var(--ink-3); margin-bottom:4px; }
.chips { display:flex; flex-wrap:wrap; gap:4px; }
.chips u { text-decoration:none; font-family:var(--mono); font-size:10px; padding:2px 6px;
  border:1px solid var(--hairline-2); color:var(--ink-2); display:block; }
.chips u[data-hot="3"] { border-color:var(--s6); color:var(--ink); background:color-mix(in srgb,var(--s6) 22%,transparent); }
.chips u[data-hot="2"] { border-color:var(--s4); color:var(--ink); }
.chips u[data-hot="1"] { border-color:var(--s2); }
.stack { display:flex; height:15px; gap:2px; margin:3px 0 2px; }
.stack i { display:block; height:100%; }
.rowlab { display:flex; justify-content:space-between; font-family:var(--mono);
  font-size:10px; color:var(--ink-2); }
.rowlab span:last-child { color:var(--ink-3); font-variant-numeric:tabular-nums; }
.lgrow { display:flex; gap:12px; flex-wrap:wrap; margin-top:10px; padding-top:9px;
  border-top:1px solid var(--hairline); font-family:var(--mono); font-size:10px; color:var(--ink-2); }
.lgrow span { display:flex; align-items:center; gap:5px; }
.lgrow i { width:9px; height:9px; display:block; flex:none; }
.lgrow svg { display:block; flex:none; }

/* 叙事—价格背离 */
.dv-h, .dv-r { display:grid; grid-template-columns:minmax(96px,1.1fr) 1fr 1fr 40px; gap:9px; align-items:center; }
.dv-h { padding-bottom:6px; border-bottom:1px solid var(--hairline); margin-bottom:5px; }
.dv-h span { font-family:var(--mono); font-size:9px; letter-spacing:.09em; text-transform:uppercase; color:var(--ink-3); }
.dv-h span:last-child { text-align:right; }
.dv-r { padding:6px 0; border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent); }
.dv-r .nm { font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.bar { height:11px; background:var(--surface-2); box-shadow:inset 0 0 0 1px var(--hairline); position:relative; }
.bar i { position:absolute; top:0; height:100%; display:block; }
.bar.ctr::before { content:""; position:absolute; left:50%; top:-2px; bottom:-2px; width:1px; background:var(--hairline-2); }
.dv-r .sc { font-family:var(--mono); font-size:12px; font-weight:600; text-align:right;
  font-variant-numeric:tabular-nums; }

/* 升级阶梯 */
.rung { display:grid; grid-template-columns:20px 1fr; gap:9px; padding:7px 0;
  border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent); }
.rung .n { font-family:var(--mono); font-size:10px; color:var(--ink-3); text-align:right;
  padding-top:2px; font-variant-numeric:tabular-nums; }
.rung .t { font-size:12px; margin-bottom:4px; }
.rung .t b { font-weight:500; }
.rung .t em { font-style:normal; font-family:var(--mono); font-size:9.5px; color:var(--ink-3); margin-left:6px; }

/* ── 主舞台 A · 实体网络（AI 频道） ── */
.net { display:grid; grid-template-columns:1fr; gap:0; }
.net > svg { display:block; width:100%; height:auto; max-height:56vh; }
.rank li { list-style:none; display:grid; grid-template-columns:16px 1fr 44px 62px; gap:8px;
  align-items:center; padding:6px 0;
  border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent); }
.rank ul { margin:0; padding:0; }
.rank .i { font-family:var(--mono); font-size:10px; color:var(--ink-3); text-align:right;
  font-variant-numeric:tabular-nums; }
.rank .n { font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.rank .n small { display:block; font-family:var(--mono); font-size:9px; color:var(--ink-3); }
.rank .w { font-family:var(--mono); font-size:12px; text-align:right; font-variant-numeric:tabular-nums; }
.rank svg { display:block; width:62px; height:20px; }

/* ── 主舞台 B · 供应链流向（半导体频道） ── */
.flow { display:flex; align-items:stretch; gap:0; overflow-x:auto; padding-bottom:4px; }
.flow .seg { flex:1 1 0; min-width:126px; display:flex; flex-direction:column; }
.flow .arw { flex:none; width:18px; display:flex; align-items:center; justify-content:center;
  color:var(--hairline-2); font-family:var(--mono); font-size:13px; }
.flow .box { border:1px solid var(--hairline-2); border-top:3px solid var(--accent);
  padding:8px 9px; display:flex; flex-direction:column; gap:6px; flex:1; background:var(--surface-2); }
.flow .box .t { font-size:12px; font-weight:500; }
.flow .box .s { font-family:var(--mono); font-size:9.5px; color:var(--ink-3);
  display:flex; justify-content:space-between; font-variant-numeric:tabular-nums; }
.flow .box u { text-decoration:none; font-family:var(--mono); font-size:9.5px; color:var(--ink-2);
  display:block; padding:1px 0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.flow .box u b { color:var(--ink); font-weight:500; }

/* ── 主舞台 C · 双带时间轴（宏观频道） ── */
.tl > svg { display:block; width:100%; height:auto; }
.tl-lg { display:flex; gap:14px; flex-wrap:wrap; margin-top:8px; font-family:var(--mono);
  font-size:10px; color:var(--ink-2); }
.tl-lg span { display:flex; align-items:center; gap:5px; }
.tl-lg i { width:14px; height:3px; display:block; }

/* ── 主舞台 D · 升级阶梯（地缘频道） ── */
.lad2 .lv { display:grid; grid-template-columns:76px 1fr; gap:11px; padding:9px 0;
  border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent); }
.lad2 .lh { display:flex; flex-direction:column; gap:3px; }
.lad2 .lh b { font-family:var(--mono); font-size:11px; font-weight:600; }
.lad2 .lh span { font-size:11px; color:var(--ink-2); }
.lad2 .bar5 { display:flex; gap:2px; margin-top:2px; }
.lad2 .bar5 i { height:4px; flex:1; display:block; background:var(--hairline); }
.lad2 .cards { display:flex; flex-wrap:wrap; gap:5px; align-content:flex-start; }
.lad2 .card { border:1px solid var(--hairline-2); padding:4px 7px; min-width:0; }
.lad2 .card .cn { font-size:11.5px; white-space:nowrap; }
.lad2 .card .cm { font-family:var(--mono); font-size:9px; color:var(--ink-3); display:flex; gap:5px; }
.lad2 .card[data-mv="up"]   { border-left:2px solid var(--st-critical); }
.lad2 .card[data-mv="down"] { border-left:2px solid var(--st-good); }
.lad2 .card .mv { font-weight:600; }
.lad2 .card[data-mv="up"] .mv   { color:var(--st-critical); }
.lad2 .card[data-mv="down"] .mv { color:var(--st-good); }

/* ── 通用热力矩阵（行不是故事时用） ── */
.mtx-r { display:grid; grid-template-columns:minmax(96px,1fr) 3fr 54px; gap:10px;
  align-items:center; padding:3px 0; }
.mtx-r .ml { font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.mtx-r .mv { font-family:var(--mono); font-size:11px; text-align:right;
  font-variant-numeric:tabular-nums; }

#tip { position:fixed; z-index:50; pointer-events:none; background:var(--surface-2); color:var(--ink);
  border:1px solid var(--hairline-2); padding:5px 8px; font-family:var(--mono); font-size:10.5px;
  line-height:1.5; white-space:nowrap; opacity:0; transition:opacity .1s; }
#tip.on { opacity:1; }
footer { padding:12px 16px; border-top:1px solid var(--hairline-2); background:var(--surface);
  font-family:var(--mono); font-size:10px; color:var(--ink-3); line-height:1.7; }
footer b { color:var(--ink-2); font-weight:500; }

@media (max-width:1180px) {
  .sensors { grid-template-columns:repeat(3,1fr); }
  .c3,.c4,.c5,.c6,.c7,.c8 { grid-column:span 12; }
  .hs-head, .hs-row { grid-template-columns:minmax(140px,1.4fr) minmax(180px,3fr) 178px; }
  .oq.wide ul { columns:2; }
  .flow { flex-direction:column; }
  .flow .arw { width:auto; height:16px; transform:rotate(90deg); }
  .lad2 .lv { grid-template-columns:64px 1fr; }
}
@media (max-width:720px) {
  .sensors { grid-template-columns:repeat(2,1fr); }
  .hs-head { display:none; }
  .hs-row { grid-template-columns:1fr; gap:4px; }
  .dm-h, .dm-r { grid-template-columns:1fr repeat(7,18px) 36px; }
  .oq.wide ul { columns:1; }
}
@media (prefers-reduced-motion:reduce) { * { transition:none !important; animation:none !important; } }
`;

const lightTokens = c => `
  color-scheme: light;
  --ground:#eceef1; --surface:#fafbfc; --surface-2:#f2f4f7;
  --hairline:#dde1e7; --hairline-2:#c6ccd5;
  --ink:#101419; --ink-2:#4d5763; --ink-3:#79838f;
  --accent:${c.light.accent}; --accent-2:${c.light.ramp[3]};
  --s0:#fafbfc; ${c.light.ramp.map((h, i) => `--s${i + 1}:${h};`).join(" ")}
  --div-n2:#2a78d6; --div-n1:#86b6ef; --div-0:#e6e6e2; --div-p1:#efa3a2; --div-p2:#e34948;
  --neutral:#98a1ac;
  --gr-1:#2a78d6; --gr-2:#eb6834; --gr-3:#4a3aa7;
  --ln-1:#2a78d6; --ln-2:#eb6834; --ln-3:#1baf7a;
`;

/* ════════════════════════════ 核心脚本 ════════════════════════════ */

const CORE_JS = String.raw`
"use strict";
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[c]));
const sum = a => a.reduce((x, y) => x + y, 0);
const STAGE = { 4:"爆发", 3:"升温", 2:"发展", 1:"收敛" };

/* 顺序色阶分桶：0 = 当日无报道，1–6 为密度等级。
   日报道量的动态范围只有约 10 倍 —— 线性分档会把九成格子压进低段，
   对数又整个推向高段。改用分位分档：阈值跟随数据分布，六档均被用上，
   突发才读得出来。代价是档距非线性，故阈值在图例明示，精确值走 tooltip 与表格视图。 */
function makeBucketer(values) {
  const v = values.filter(x => x > 0).sort((a, b) => a - b);
  const q = p => v[Math.min(v.length - 1, Math.floor(p * v.length))];
  const br = [q(.17), q(.34), q(.50), q(.67), q(.84)];
  const fn = x => x <= 0 ? 0 : x <= br[0] ? 1 : x <= br[1] ? 2
                : x <= br[2] ? 3 : x <= br[3] ? 4 : x <= br[4] ? 5 : 6;
  fn.breaks = br;
  return fn;
}

function sparkSVG(data, w, h, stroke, fill) {
  const lo = Math.min(...data), hi = Math.max(...data), span = hi - lo || 1;
  const p = data.map((v, i) => {
    const x = 2 + i * (w - 4) / (data.length - 1);
    const y = h - 2 - (v - lo) / span * (h - 4);
    return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
  }).join(" ");
  const ly = h - 2 - (data[data.length - 1] - lo) / span * (h - 4);
  return '<svg viewBox="0 0 ' + w + ' ' + h + '" aria-hidden="true">' +
    '<path d="' + p + ' L' + (w - 2) + ' ' + h + ' L2 ' + h + ' Z" fill="' + fill + '" opacity=".22"></path>' +
    '<path d="' + p + '" fill="none" stroke="' + stroke + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>' +
    '<circle cx="' + (w - 2) + '" cy="' + ly.toFixed(1) + '" r="2.6" fill="' + stroke + '"></circle></svg>';
}

/* 共享 tooltip —— hover 与键盘 focus 走同一条路径，值不被指针独占 */
const tipEl = () => $("#tip");
function bindTip(root) {
  const show = e => {
    const el = e.target.closest("[data-tip]");
    if (!el) return;
    const t = tipEl();
    t.innerHTML = el.dataset.tip.split("|").map(esc).join("<br>");
    t.classList.add("on");
    const r = el.getBoundingClientRect(), b = t.getBoundingClientRect();
    t.style.left = Math.max(6, Math.min(innerWidth - b.width - 6, r.left + r.width / 2 - b.width / 2)) + "px";
    t.style.top = (r.top - b.height - 7 < 6 ? r.bottom + 7 : r.top - b.height - 7) + "px";
  };
  const hide = () => tipEl().classList.remove("on");
  root.addEventListener("mouseover", show); root.addEventListener("mouseout", hide);
  root.addEventListener("focusin", show);   root.addEventListener("focusout", hide);
}

function renderSensors() {
  $("#sensors").innerHTML = DATA.sensors.map(s =>
    '<div class="sensor"><div class="lbl"><span class="eyebrow">' + esc(s.k) + '</span>' +
    '<span class="dl ' + s.dir + '"><em class="ar">' +
    (s.dir === "up" ? "▲" : s.dir === "down" ? "▼" : "—") + '</em>' + esc(s.d) + '</span></div>' +
    '<div class="val">' + esc(s.v) + '</div>' +
    sparkSVG(s.s, 160, 22, "var(--accent)", "var(--accent)") + '</div>').join("");
}

function renderDisagreement() {
  const G = { "2":"++", "1":"+", "0":"·", "-1":"−", "-2":"✕" };
  const N = { "2":"强支持", "1":"支持", "0":"未表态", "-1":"质疑", "-2":"否认 / 反驳" };
  const src = DATA.sources, full = DATA.sourceNames;
  const scored = DATA.claims.map(c => {
    const m = sum(c.v) / c.v.length;
    const sd = Math.sqrt(c.v.reduce((a, b) => a + (b - m) ** 2, 0) / c.v.length);
    return { ...c, score: Math.round(sd / 2 * 100) };
  }).sort((a, b) => b.score - a.score);

  $("#dm").innerHTML = '<div class="dm-h"><span>断言</span>' +
    src.map(s => '<span title="' + esc(full[s]) + '">' + s + '</span>').join("") +
    '<span>分歧度</span></div>' +
    scored.map(c => '<div class="dm-r"><div class="cl"><b title="' + esc(c.c) + '">' + esc(c.c) +
      '</b><small>' + esc(c.n) + '</small></div>' +
      c.v.map((v, i) => '<u data-v="' + v + '" tabindex="0" data-tip="' + esc(full[src[i]]) + '|' +
        N[v] + '|「' + esc(c.c) + '」">' + G[v] + '</u>').join("") +
      '<span class="sc" style="color:' + (c.score >= 70 ? "var(--st-critical)"
        : c.score >= 45 ? "var(--st-warning)" : "var(--ink-2)") + '">' + c.score + '</span></div>').join("") +
    '<div class="dm-lg">立场 <i style="background:var(--div-n2)"></i>否认 ✕' +
    ' <i style="background:var(--div-n1)"></i>质疑 −' +
    ' <i style="background:var(--div-0)"></i>未表态 ·' +
    ' <i style="background:var(--div-p1)"></i>支持 +' +
    ' <i style="background:var(--div-p2)"></i>强支持 ++</div>';
}

function renderQuestions() {
  $("#oq").innerHTML = DATA.questions.map(q =>
    '<li><div class="q">' + esc(q.q) + '</div><div class="m">' +
    '<span><b>故事</b> ' + esc(q.s) + '</span><span><b>等待</b> ' + esc(q.w) + '</span>' +
    '<span class="age">悬置 ' + q.age + 'd</span></div></li>').join("");
}

/* 背景平面：全频道 30 天体量剪影 + 网格。真实数据，压到极低对比度。 */
function renderField() {
  const cv = $("#field"), ctx = cv.getContext("2d");
  const draw = () => {
    const dpr = Math.min(devicePixelRatio || 1, 2), w = innerWidth, h = innerHeight;
    cv.width = w * dpr; cv.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
    ctx.globalAlpha = .05;
    for (let x = 18; x < w; x += 34) for (let y = 18; y < h; y += 34) ctx.fillRect(x, y, 1, 1);
    const tot = DATA.stories[0].d.map((_, i) => sum(DATA.stories.map(s => s.d[i])));
    const mx = Math.max(...tot), base = h - 4;
    ctx.globalAlpha = .07; ctx.beginPath(); ctx.moveTo(0, base);
    tot.forEach((v, i) => ctx.lineTo(i * w / (tot.length - 1), base - v / mx * h * .42));
    ctx.lineTo(w, base); ctx.closePath(); ctx.fill(); ctx.globalAlpha = 1;
  };
  draw();
  let t; addEventListener("resize", () => { clearTimeout(t); t = setTimeout(draw, 120); });
}

/* 通用热力矩阵 —— 行不是「故事」时用（例如行是供应链环节、行是区域）。
   与故事热力带共用同一个分位分档器和格子样式，所以颜色含义在全站保持一致。 */
function renderHeatGrid(mount, rows, opts) {
  const o = opts || {};
  const bkt = makeBucketer(rows.flatMap(r => r.d));
  const today = new Date(DATA.asOf);
  const day = i => { const d = new Date(today); d.setUTCDate(d.getUTCDate() - (29 - i));
    return (d.getUTCMonth() + 1) + "/" + d.getUTCDate(); };
  $(mount).innerHTML = rows.map(r =>
    '<div class="mtx-r"><span class="ml" title="' + esc(r.label) + '">' + esc(r.label) + '</span>' +
    '<span class="cells">' + r.d.map((v, i) =>
      '<i tabindex="0" data-b="' + bkt(v) + '" data-tip="' + esc(r.label) + '|' + day(i) + ' · ' +
      v + (o.unit || " 篇") + '"></i>').join("") + '</span>' +
    '<span class="mv">' + esc(r.val) + '</span></div>').join("");
  if (o.breaksInto) $(o.breaksInto).textContent =
    "（分位分档，阈值 " + bkt.breaks.join(" / ") + (o.unit || " 篇") + "/日）";
}

/* 力导向布局 —— 定种子伪随机，结果稳定可复现，跑完再渲染，不做动画 */
function forceLayout(nodes, edges, W, H, seed) {
  let s = seed;
  const rnd = () => ((s = (s * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
  const N = nodes.map(n => ({ ...n, x: W / 2 + (rnd() - .5) * W * .7,
    y: H / 2 + (rnd() - .5) * H * .7, vx: 0, vy: 0 }));
  const idx = Object.fromEntries(N.map((n, i) => [n.id, i]));
  for (let it = 0; it < 480; it++) {
    const cool = 1 - it / 480;
    for (let i = 0; i < N.length; i++) for (let j = i + 1; j < N.length; j++) {
      const a = N[i], b = N[j], dx = b.x - a.x, dy = b.y - a.y;
      const d2 = Math.max(dx * dx + dy * dy, 4), d = Math.sqrt(d2), f = 3400 / d2;
      const fx = dx / d * f, fy = dy / d * f;
      a.vx -= fx; a.vy -= fy; b.vx += fx; b.vy += fy;
    }
    for (const [p, q, w] of edges) {
      const a = N[idx[p]], b = N[idx[q]], dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.max(Math.sqrt(dx * dx + dy * dy), .5), f = (d - 54) * (.02 + w * .004);
      const fx = dx / d * f, fy = dy / d * f;
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
    }
    for (const n of N) {
      n.vx += (W / 2 - n.x) * .010; n.vy += (H / 2 - n.y) * .014;
      n.x += n.vx * cool * .5; n.y += n.vy * cool * .5;
      n.vx *= .80; n.vy *= .80;
      n.x = Math.max(32, Math.min(W - 32, n.x));
      n.y = Math.max(26, Math.min(H - 14, n.y));   /* 顶部留标签行高，否则被 viewBox 裁掉 */
    }
  }
  return { nodes: N, idx };
}
`;

/* ════════════════════════════ 页面骨架 ════════════════════════════ */

const CHANNELS = [
  ["ai-industry", "AI 产业"], ["semiconductor", "半导体"],
  ["macro-markets", "宏观市场"], ["geopolitics", "地缘政治"],
];

const page = c => `<title>NewsAssistant · ${c.name}频道</title>

<style>${css(c)}</style>

<canvas id="field" aria-hidden="true"></canvas>

<div class="console">
  <div class="rail">
    <div class="brand"><span class="dot"></span><b>NEWSASSISTANT</b></div>
    <div class="chans">${CHANNELS.map(([id, n]) =>
      `<button class="chan"${id === c.id ? ' aria-current="true"' : " disabled"}>${n}</button>`).join("")}</div>
    <div class="railpad"></div>
    <span class="mock">示例数据 · 布局原型</span>
  </div>

  <div class="status">${c.status.map(s =>
    `<div${s.live ? ' class="live"' : ""}>${s.live ? "● " : ""}${s.k} <b>${s.v}</b>${s.u || ""}</div>`).join("")}</div>

  <div class="sensors" id="sensors"></div>

  <div class="grid">
${c.panels}
  </div>

  <footer>
    <b>这是一份布局原型。</b>面板中的全部数字、故事、断言与信源立场均为演示用的<b>虚构数据</b>，不代表任何真实事件或报道。<br>
    编码说明 — 热力带：单色顺序色阶编码日报道量，分位分档；分歧矩阵：蓝↔红发散色编码信源立场，灰色为未表态，每格另附字符标记，不依赖颜色单独传达；方向一律由 ▲▼ 承载，状态色仅用于越阈提示条，与系列色互不复用。${c.footnote || ""}
  </footer>
</div>

<div id="tip" role="status" aria-live="polite"></div>

<script>
(() => {
${CORE_JS}
const DATA = ${JSON.stringify(c.data)};
${c.extraJS || ""}
/* 四个频道共有的只有这四样 —— 主舞台由各频道自己决定，见 extraBoot */
renderSensors(); renderDisagreement(); renderQuestions(); renderField();
${c.extraBoot || ""}
bindTip(document.body);
})();
</script>
`;

/* ════════════════════════════ 频道配置 ════════════════════════════ */

const { CHANNEL_CONFIGS } = await import("./channels.mjs");

for (const c of CHANNEL_CONFIGS) {
  writeFileSync(join(OUT, c.id + ".html"), page(c));
  console.log("✓ " + c.id + ".html");
}
