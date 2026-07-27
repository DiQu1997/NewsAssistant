/* 共享主题 —— 频道页与故事页共用的设计 token 与全部面板样式。
   只此一份：改这里，所有页面一起变。 */

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

export const css = c => `
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
  --gr-1:#3987e5; --gr-2:#d95926; --gr-3:#9085e9;
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
.eyebrow { font-family:var(--mono); font-size:10px; letter-spacing:.13em; text-transform:uppercase;
  color:var(--ink-3); font-weight:500; }
:focus-visible { outline:2px solid var(--accent); outline-offset:1px; }
[hidden] { display:none !important; }

.rail { display:flex; align-items:stretch; flex-wrap:wrap;
  border-bottom:1px solid var(--hairline-2); background:var(--surface); }
.brand { display:flex; align-items:center; gap:10px; padding:10px 16px; border-right:1px solid var(--hairline); }
.brand b { font-family:var(--mono); font-size:12px; letter-spacing:.16em; font-weight:600; }
.brand .dot { width:7px; height:7px; background:var(--accent); }
.chans { display:flex; flex-wrap:wrap; }
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

.sensors { display:grid; grid-template-columns:repeat(6,1fr);
  border-bottom:1px solid var(--hairline-2); background:var(--surface); }
.sensor { padding:11px 14px 9px; border-right:1px solid var(--hairline);
  display:flex; flex-direction:column; gap:5px; min-width:0; }
.sensor:last-child { border-right:0; }
.sensor .lbl { display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.sensor .val { font-family:var(--mono); font-size:19px; font-weight:600; letter-spacing:-.01em; }
.sensor .dl { font-family:var(--mono); font-size:11px; font-variant-numeric:tabular-nums; white-space:nowrap; }
.sensor > svg { display:block; width:100%; height:22px; }
/* 方向由字符标记承载，不用颜色 —— 状态色只留给越阈提示 */
.up, .down { color:var(--ink); } .flat { color:var(--ink-3); }
em.ar { font-style:normal; color:var(--ink-3); font-size:.86em; padding-right:1px; }

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
${[3,4,5,6,7,8,9,10,11,12].map(i => `.c${i}{grid-column:span ${i}}`).join(" ")}

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
.meter { height:5px; background:var(--surface-2); box-shadow:inset 0 0 0 1px var(--hairline); }
.meter i { display:block; height:100%; }
.scale { display:flex; align-items:center; gap:5px; font-family:var(--mono); font-size:10px;
  color:var(--ink-3); flex-wrap:wrap; margin-top:10px; padding-top:9px; border-top:1px solid var(--hairline); }
.scale i { width:14px; height:9px; display:block; }
.lgrow { display:flex; gap:12px; flex-wrap:wrap; margin-top:10px; padding-top:9px;
  border-top:1px solid var(--hairline); font-family:var(--mono); font-size:10px; color:var(--ink-2); }
.lgrow span { display:flex; align-items:center; gap:5px; }
.lgrow i { width:9px; height:9px; display:block; flex:none; }
.lgrow svg { display:block; flex:none; }

/* 故事流 */
.vt { display:grid; grid-template-columns:1fr 68px 70px; gap:9px; align-items:center;
  padding:8px 0 8px 9px; border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent);
  border-left:2px solid transparent; }
.vt .nm { font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.vt .nm small { display:block; font-family:var(--mono); font-size:9.5px; color:var(--ink-3); letter-spacing:.04em; }
.vt .nm u.also { text-decoration:none; font-family:var(--mono); font-size:9px; color:var(--accent);
  border:1px solid color-mix(in srgb,var(--accent) 45%,transparent); padding:0 4px; margin-left:5px; }
.vt .pc { font-family:var(--mono); font-size:15px; font-weight:600; text-align:right; font-variant-numeric:tabular-nums; }
.vt svg { display:block; width:70px; height:24px; }

/* 网络 + 活跃度榜 */
.net > svg { display:block; width:100%; height:auto; max-height:56vh; }
.rank li { list-style:none; display:grid; grid-template-columns:16px 1fr 44px 62px; gap:8px;
  align-items:center; padding:6px 0; border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent); }
.rank ul { margin:0; padding:0; }
.rank .i { font-family:var(--mono); font-size:10px; color:var(--ink-3); text-align:right; font-variant-numeric:tabular-nums; }
.rank .n { font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.rank .n small { display:block; font-family:var(--mono); font-size:9px; color:var(--ink-3); }
.rank .w { font-family:var(--mono); font-size:12px; text-align:right; font-variant-numeric:tabular-nums; }
.rank svg { display:block; width:62px; height:20px; }

/* 流向图 */
.flow { display:flex; align-items:stretch; overflow-x:auto; padding-bottom:4px; }
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

/* 时间轴 */
.tl > svg { display:block; width:100%; height:auto; }

/* 阶梯 */
.lad2 .lv { display:grid; grid-template-columns:76px 1fr; gap:11px; padding:9px 0;
  border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent); }
.lad2 .lh { display:flex; flex-direction:column; gap:3px; }
.lad2 .lh b { font-family:var(--mono); font-size:11px; font-weight:600; }
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

/* 条目清单（meter 列表） */
.tier { padding:5px 0; border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent); }
.tier .th { display:flex; align-items:baseline; gap:8px; margin-bottom:6px; }
.tier .th b { font-size:12px; font-weight:500; }
.tier .th > span:last-child { font-family:var(--mono); font-size:9.5px; color:var(--ink-3);
  margin-left:auto; font-variant-numeric:tabular-nums; }
.tier .note { font-family:var(--mono); font-size:10px; color:var(--ink-3); margin-bottom:4px; }

/* 热力矩阵 */
.mtx-r { display:grid; grid-template-columns:minmax(96px,1fr) 3fr 54px; gap:10px;
  align-items:center; padding:3px 0; }
.mtx-r .ml { font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.mtx-r .mv { font-family:var(--mono); font-size:11px; text-align:right; font-variant-numeric:tabular-nums; }

/* 构成条 */
.rowlab { display:flex; justify-content:space-between; font-family:var(--mono);
  font-size:10px; color:var(--ink-2); }
.rowlab span:last-child { color:var(--ink-3); font-variant-numeric:tabular-nums; }
.stack { display:flex; height:15px; gap:2px; margin:3px 0 2px; }
.stack i { display:block; height:100%; }

/* 背离榜 */
.dv-h, .dv-r { display:grid; grid-template-columns:minmax(96px,1.1fr) 1fr 1fr 40px; gap:9px; align-items:center; }
.dv-h { padding-bottom:6px; border-bottom:1px solid var(--hairline); margin-bottom:5px; }
.dv-h span { font-family:var(--mono); font-size:9px; letter-spacing:.09em; text-transform:uppercase; color:var(--ink-3); }
.dv-h span:last-child { text-align:right; }
.dv-r { padding:6px 0; border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent); }
.dv-r .nm { font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.bar { height:11px; background:var(--surface-2); box-shadow:inset 0 0 0 1px var(--hairline); position:relative; }
.bar i { position:absolute; top:0; height:100%; display:block; }
.bar.ctr::before { content:""; position:absolute; left:50%; top:-2px; bottom:-2px; width:1px; background:var(--hairline-2); }
.dv-r .sc { font-family:var(--mono); font-size:12px; font-weight:600; text-align:right; font-variant-numeric:tabular-nums; }

/* 分歧矩阵 */
.dm-glabel { font-family:var(--mono); font-size:10px; letter-spacing:.1em; color:var(--accent);
  margin:12px 0 4px; text-transform:uppercase; }
.dm-glabel:first-child { margin-top:0; }
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
.dm-r .sc { font-family:var(--mono); font-size:12px; text-align:right; font-variant-numeric:tabular-nums; font-weight:600; }
.dm-lg { display:flex; align-items:center; gap:4px; margin-top:10px; padding-top:9px;
  border-top:1px solid var(--hairline); font-family:var(--mono); font-size:10px; color:var(--ink-3); flex-wrap:wrap; }
.dm-lg i { width:15px; height:9px; display:block; }

/* 未解问题 */
.oq ul { margin:0; padding:0; }
.oq li { list-style:none; padding:9px 0; border-bottom:1px solid color-mix(in srgb,var(--hairline) 55%,transparent);
  break-inside:avoid; }
.oq .q { font-size:12.5px; margin-bottom:4px; }
.oq .m { display:flex; gap:9px; flex-wrap:wrap; font-family:var(--mono); font-size:9.5px; color:var(--ink-3); }
.oq .m b { color:var(--ink-2); font-weight:500; }
.oq .age { color:var(--st-warning); }
.oq.wide ul { columns:3; column-gap:26px; }

#tip { position:fixed; z-index:50; pointer-events:none; background:var(--surface-2); color:var(--ink);
  border:1px solid var(--hairline-2); padding:5px 8px; font-family:var(--mono); font-size:10.5px;
  line-height:1.5; white-space:nowrap; opacity:0; transition:opacity .1s; }
#tip.on { opacity:1; }
footer { padding:12px 16px; border-top:1px solid var(--hairline-2); background:var(--surface);
  font-family:var(--mono); font-size:10px; color:var(--ink-3); line-height:1.7; }
footer b { color:var(--ink-2); font-weight:500; }

@media (max-width:1180px) {
  .sensors { grid-template-columns:repeat(3,1fr); }
  ${[3,4,5,6,7,8,9,10,11].map(i => `.c${i}`).join(",")} { grid-column:span 12; }
  .flow { flex-direction:column; }
  .flow .arw { width:auto; height:16px; transform:rotate(90deg); }
  .oq.wide ul { columns:2; }
}
@media (max-width:720px) {
  .sensors { grid-template-columns:repeat(2,1fr); }
  .dm-h, .dm-r { grid-template-columns:1fr repeat(7,18px) 36px; }
  .oq.wide ul { columns:1; }
}
@media (prefers-reduced-motion:reduce) { * { transition:none !important; animation:none !important; } }
`;
