/* NewsAssistant 控制台原型 — 生成器
 *
 *   node build.mjs   → 每个频道（保存的查询）生成一个自包含静态页
 *
 * 架构（docs/architecture.md §4、docs/views.md）：
 *   store.mjs    通用存储 —— 实体/关系/状态机/序列/故事/断言/问题，条目携带 tags
 *   channels.mjs 保存的查询 —— 只有过滤器和标识色，没有版面
 *   本文件       ① buildSlice: 执行查询  ② selectViews: 按检测到的数据结构选视图
 *                ③ 视图注册表: 每种结构一个通用渲染器  ④ 布局: 默认跨度 + 行填充
 *
 * 新频道 = channels.mjs 加一行；新领域不需要新代码。
 * 全部数据均为虚构的演示数据，仅用于验证版式与视觉编码。
 */

import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { CHANNELS } from "./channels.mjs";
import { css } from "./theme.mjs";
import { META, ASOF, STORIES, SENSORS, ENTITIES, ENTITY_KINDS, LINKS, SEGMENTS,
         COMPOSITIONS, LADDER, GRIDS, EXT_SERIES, PAIRS, SOURCESETS, CLAIMS,
         QUESTIONS } from "./store.mjs";

const OUT = dirname(fileURLToPath(import.meta.url));
const NAMES = Object.fromEntries(CHANNELS.map(c => [c.query.tag, c.name]));
const sum = a => a.reduce((x, y) => x + y, 0);

/* ═══════════════ ① 执行查询 ═══════════════ */

const hasTag = (item, tag) => item.tags.includes(tag);

function buildSlice(query) {
  if (query.meta === "disagreement") {
    /* 元频道：跨全库，按分歧度取断言；故事按动量取 top12 */
    return {
      meta: { collected: sum(Object.values(META).map(m => m.collected)),
              sources: sum(Object.values(META).map(m => m.sources)), sync: "12:04" },
      stories: [...STORIES].sort((a, b) => Math.abs(b.vel) - Math.abs(a.vel)).slice(0, 12),
      claimGroups: Object.keys(SOURCESETS).map(set => ({
        label: NAMES[set], set: SOURCESETS[set],
        claims: CLAIMS.filter(c => c.set === set) })),
      questions: [...QUESTIONS].sort((a, b) => b.age - a.age).slice(0, 12),
      sensors: null, entities: [], links: [], grids: [],
      fieldStories: STORIES,
    };
  }
  const t = query.tag;
  return {
    meta: META[t],
    stories: STORIES.filter(s => hasTag(s, t)),
    sensors: SENSORS[t] || null,
    entities: ENTITIES.filter(e => hasTag(e, t)),
    links: LINKS.filter(l => hasTag(l, t)),
    segments: hasTag(SEGMENTS, t) ? SEGMENTS : null,
    compositions: hasTag(COMPOSITIONS, t) ? COMPOSITIONS : null,
    ladder: hasTag(LADDER, t) ? LADDER : null,
    grids: GRIDS.filter(g => hasTag(g, t)),
    extSeries: hasTag(EXT_SERIES, t) ? EXT_SERIES : null,
    pairs: hasTag(PAIRS, t) ? PAIRS : null,
    claimGroups: [{ label: null, set: SOURCESETS[t],
      claims: CLAIMS.filter(c => hasTag(c, t)) }],
    questions: QUESTIONS.filter(q => hasTag(q, t)),
    fieldStories: STORIES.filter(s => hasTag(s, t)),
  };
}

/* ═══════════════ ② 按数据结构选视图（docs/views.md §2） ═══════════════ */

function topoOrder(nodes, depends) {
  /* 链条顺序由拓扑排序推导，不由数组顺序决定 —— 结构检测，非人工声明 */
  const indeg = Object.fromEntries(nodes.map(n => [n.id, 0]));
  depends.forEach(([, b]) => indeg[b]++);
  const order = [], q = nodes.filter(n => !indeg[n.id]).map(n => n.id);
  while (q.length) {
    const id = q.shift(); order.push(id);
    depends.filter(([a]) => a === id).forEach(([, b]) => { if (!--indeg[b]) q.push(b); });
  }
  return order.map(id => nodes.find(n => n.id === id));
}

function selectViews(slice, chName) {
  const v = [];
  const story30 = slice.stories[0] ? slice.stories[0].d.length : 30;
  const narr = Array.from({ length: story30 }, (_, i) => sum(slice.stories.map(s => s.d[i])));

  /* 有向依赖链（可拓扑排序） → 流向图，主舞台 */
  if (slice.segments) {
    const nodes = topoOrder(slice.segments.nodes, slice.segments.depends);
    v.push({ type: "flow", span: 12, title: slice.segments.title, note: slice.segments.note,
      data: { nodes } });
  }
  /* 外生数值序列可与叙事对齐 → 共轴时间带，主舞台 */
  if (slice.extSeries) {
    v.push({ type: "timeline", span: 12, title: slice.extSeries.title,
      note: "近 30 天 · 上带叙事密度，下带指标（均归一化到基期 100）",
      data: { lines: slice.extSeries.lines, pins: slice.extSeries.pins, narr, asOf: ASOF } });
  }
  /* 无向共现关系稠密 → 网络 + 活跃度榜 */
  if (slice.links.length >= slice.entities.length && slice.entities.length) {
    v.push({ type: "network", span: 7, title: "实体网络",
      note: `近 14 天共现 · ${slice.entities.length} 个实体 / ${slice.links.length} 条关系`,
      data: { entities: slice.entities, links: slice.links, kinds: ENTITY_KINDS } });
    v.push({ type: "rank", span: 5, title: "实体活跃度",
      note: `近 14 天 · ${slice.entities.length} 个中的前 12`,
      data: { entities: slice.entities, links: slice.links, kinds: ENTITY_KINDS } });
  }
  /* 有序状态机（含上期状态） → 阶梯 + 条目清单 */
  if (slice.ladder) {
    v.push({ type: "ladder", span: 6, title: slice.ladder.title, note: slice.ladder.note,
      data: { levels: slice.ladder.levels, items: slice.ladder.items } });
    v.push({ type: "itemmeters", span: 6, title: slice.ladder.itemsTitle,
      note: `${slice.ladder.items.length} 处 · 条 = 近 30 天报道体量`,
      data: { items: slice.ladder.items } });
  }
  /* 两离散维 + 强度 → 热力矩阵（来自 grids，或从链条节点派生） */
  const grids = [...slice.grids];
  if (slice.segments) grids.push({ title: slice.segments.gridTitle, unit: " 篇",
    rows: slice.segments.nodes.map(n => ({ label: n.l, d: n.d })) });
  grids.forEach(g => v.push({ type: "heatgrid", span: 5, title: g.title,
    note: "近 30 天报道密度", data: { rows: g.rows.map(r => ({ ...r, val: sum(r.d) })),
    unit: g.unit || " 篇", asOf: ASOF } }));
  /* 份额分解 → 构成条 */
  if (slice.compositions) v.push({ type: "composition", span: 3,
    title: slice.compositions.title, note: slice.compositions.note,
    data: { regions: slice.compositions.regions, rows: slice.compositions.rows } });
  /* 叙事/观测配对 → 背离榜 */
  if (slice.pairs) v.push({ type: "divergence", span: 5, title: slice.pairs.title,
    note: "按背离度排序", data: { rows: slice.pairs.rows } });

  /* 恒在三件套：故事流、分歧矩阵、未解问题 */
  const hasStructural = v.length > 0;
  if (slice.stories.length) v.push({ type: "storylist", span: 4, title: "故事流",
    note: "按动量排序", data: { stories: slice.stories.map(s =>
      ({ ...s, also: s.tags.map(t => NAMES[t]).filter(n => n && n !== chName) })) } });
  if (slice.claimGroups.some(g => g.claims.length)) {
    const dm = { type: "disagreement", span: 4, title: "分歧矩阵", note: "按分歧度排序",
      data: { groups: slice.claimGroups } };
    /* 元频道没有结构视图 → 分歧矩阵升为主舞台 */
    if (!hasStructural) { dm.span = 8; v.unshift(dm); } else v.push(dm);
  }
  if (slice.questions.length) v.push({ type: "questions", span: 3, title: "未解问题",
    note: `${slice.questions.length} 项`, data: { questions: slice.questions.slice(0, 12) } });

  return pack(v);
}

/* 布局：默认跨度 + 行填充 —— 每行凑满 12，行尾落单的面板扩展占满 */
function pack(views) {
  let col = 0;
  views.forEach((v, i) => {
    if (col + v.span > 12) { views[i - 1].span += 12 - col; col = 0; }
    col = (col + v.span) % 12;
  });
  if (col !== 0) views[views.length - 1].span += 12 - col;
  views.forEach(v => { if (v.type === "questions" && v.span >= 8) v.wide = true; });
  return views;
}

/* ═══════════════ ③ 样式 ═══════════════ */

/* ═══════════════ ④ 运行时：助手 + 视图注册表 ═══════════════ */

const CORE_JS = String.raw`
"use strict";
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[c]));
const sum = a => a.reduce((x, y) => x + y, 0);
const STAGE = { 4:"爆发", 3:"升温", 2:"发展", 1:"收敛" };
const dayFn = asOf => { const t = new Date(asOf); return i => {
  const d = new Date(t); d.setUTCDate(d.getUTCDate() - (29 - i));
  return (d.getUTCMonth() + 1) + "/" + d.getUTCDate(); }; };

/* 分位分档：日量动态范围仅约 10 倍，线性压低段、对数推高段，分位让六档都被用上 */
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

/* tooltip：hover 与键盘 focus 同路径 */
function bindTip(root) {
  const tip = $("#tip");
  const show = e => {
    const el = e.target.closest("[data-tip]");
    if (!el) return;
    tip.innerHTML = el.dataset.tip.split("|").map(esc).join("<br>");
    tip.classList.add("on");
    const r = el.getBoundingClientRect(), b = tip.getBoundingClientRect();
    tip.style.left = Math.max(6, Math.min(innerWidth - b.width - 6, r.left + r.width / 2 - b.width / 2)) + "px";
    tip.style.top = (r.top - b.height - 7 < 6 ? r.bottom + 7 : r.top - b.height - 7) + "px";
  };
  const hide = () => tip.classList.remove("on");
  root.addEventListener("mouseover", show); root.addEventListener("mouseout", hide);
  root.addEventListener("focusin", show);   root.addEventListener("focusout", hide);
}

function renderSensors() {
  if (!DATA.sensors) return;
  $("#sensors").innerHTML = DATA.sensors.map(s =>
    '<div class="sensor"><div class="lbl"><span class="eyebrow">' + esc(s.k) + '</span>' +
    '<span class="dl ' + s.dir + '"><em class="ar">' +
    (s.dir === "up" ? "▲" : s.dir === "down" ? "▼" : "—") + '</em>' + esc(s.d) + '</span></div>' +
    '<div class="val">' + esc(s.v) + '</div>' +
    sparkSVG(s.s, 160, 22, "var(--accent)", "var(--accent)") + '</div>').join("");
}

function renderField() {
  const cv = $("#field"), ctx = cv.getContext("2d");
  const draw = () => {
    const dpr = Math.min(devicePixelRatio || 1, 2), w = innerWidth, h = innerHeight;
    cv.width = w * dpr; cv.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
    ctx.globalAlpha = .05;
    for (let x = 18; x < w; x += 34) for (let y = 18; y < h; y += 34) ctx.fillRect(x, y, 1, 1);
    const tot = DATA.field[0].map((_, i) => sum(DATA.field.map(s => s[i])));
    const mx = Math.max(...tot), base = h - 4;
    ctx.globalAlpha = .07; ctx.beginPath(); ctx.moveTo(0, base);
    tot.forEach((v, i) => ctx.lineTo(i * w / (tot.length - 1), base - v / mx * h * .42));
    ctx.lineTo(w, base); ctx.closePath(); ctx.fill(); ctx.globalAlpha = 1;
  };
  draw();
  let t; addEventListener("resize", () => { clearTimeout(t); t = setTimeout(draw, 120); });
}

/* 力导向 —— 定种子伪随机，结果可复现，跑完再渲染 */
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
      a.vx -= dx / d * f; a.vy -= dy / d * f; b.vx += dx / d * f; b.vy += dy / d * f;
    }
    for (const [p, q, w] of edges) {
      const a = N[idx[p]], b = N[idx[q]], dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.max(Math.sqrt(dx * dx + dy * dy), .5), f = (d - 54) * (.02 + w * .004);
      a.vx += dx / d * f; a.vy += dy / d * f; b.vx -= dx / d * f; b.vy -= dy / d * f;
    }
    for (const n of N) {
      n.vx += (W / 2 - n.x) * .010; n.vy += (H / 2 - n.y) * .014;
      n.x += n.vx * cool * .5; n.y += n.vy * cool * .5;
      n.vx *= .80; n.vy *= .80;
      n.x = Math.max(32, Math.min(W - 32, n.x));
      n.y = Math.max(26, Math.min(H - 14, n.y));
    }
  }
  return { nodes: N, idx };
}

/* ───────── 视图注册表：每种数据结构一个通用渲染器 ───────── */
const REG = {};

/* 实体类型用形状编码，不用色相 —— 抗色觉缺陷；颜色让给频道标识 */
const SHAPE = (x, y, r, fill) => ({
  1: '<circle cx="'+x+'" cy="'+y+'" r="'+r+'" fill="'+fill+'"></circle>',
  2: '<rect x="'+(x-r*.9)+'" y="'+(y-r*.9)+'" width="'+(r*1.8)+'" height="'+(r*1.8)+'" fill="'+fill+'"></rect>',
  3: '<rect x="'+(x-r*.82)+'" y="'+(y-r*.82)+'" width="'+(r*1.64)+'" height="'+(r*1.64)+
     '" transform="rotate(45 '+x+' '+y+')" fill="'+fill+'"></rect>' });

REG.network = (m, d) => {
  const W = 700, H = 380;
  const { nodes, idx } = forceLayout(d.entities, d.links.map(l => [l.a, l.b, l.w]), W, H, 20260727);
  const links = d.links.map(l => {
    const a = nodes[idx[l.a]], b = nodes[idx[l.b]];
    return '<line x1="'+a.x.toFixed(1)+'" y1="'+a.y.toFixed(1)+'" x2="'+b.x.toFixed(1)+'" y2="'+b.y.toFixed(1)+
      '" stroke="var(--hairline-2)" stroke-width="'+(.5+l.w*.15).toFixed(2)+'" opacity=".9"></line>';
  }).join("");
  const marks = nodes.map(n => {
    const r = 3.6 + Math.sqrt(n.w) * 1.35, x = +n.x.toFixed(1), y = +n.y.toFixed(1);
    const deg = d.links.filter(l => l.a === n.id || l.b === n.id).length;
    const sh = SHAPE(x, y, r, "var(--accent)"), sh2 = SHAPE(x, y, r + 2, "var(--surface)");
    return '<g tabindex="0" data-tip="'+esc(n.l)+'|'+(d.kinds[n.t]||"实体")+'|活跃度 '+n.w+' · 共现 '+deg+' 个实体">' +
      (sh2[n.t]||sh2[1]) + (sh[n.t]||sh[1]) +
      '<text x="'+x+'" y="'+(y-r-5).toFixed(1)+'" text-anchor="middle" font-family="var(--mono)"' +
      ' font-size="9.5" fill="var(--ink-2)">'+esc(n.l)+'</text></g>';
  }).join("");
  $(m).innerHTML = '<div class="net"><svg viewBox="0 0 '+W+' '+H+'" role="img"' +
    ' aria-label="实体共现网络：形状区分类型，大小表示活跃度，线宽表示共现强度">' + links + marks + '</svg>' +
    '<div class="lgrow">' +
    '<span><svg width="11" height="11" viewBox="0 0 11 11" aria-hidden="true"><circle cx="5.5" cy="5.5" r="4.4" fill="var(--accent)"/></svg>'+esc(d.kinds[1]||"")+'</span>' +
    '<span><svg width="11" height="11" viewBox="0 0 11 11" aria-hidden="true"><rect x="1.5" y="1.5" width="8" height="8" fill="var(--accent)"/></svg>'+esc(d.kinds[2]||"")+'</span>' +
    '<span><svg width="11" height="11" viewBox="0 0 11 11" aria-hidden="true"><rect x="1.9" y="1.9" width="7.2" height="7.2" transform="rotate(45 5.5 5.5)" fill="var(--accent)"/></svg>'+esc(d.kinds[3]||"")+'</span>' +
    '<span style="color:var(--ink-3)">大小 = 活跃度　线宽 = 共现强度</span></div></div>';
};

REG.rank = (m, d) => {
  $(m).innerHTML = '<div class="rank"><ul>' +
    [...d.entities].sort((a, b) => b.w - a.w).slice(0, 12).map((n, i) => {
      const deg = d.links.filter(l => l.a === n.id || l.b === n.id).length;
      return '<li><span class="i">'+(i+1)+'</span>' +
        '<span class="n">'+esc(n.l)+'<small>'+(d.kinds[n.t]||"实体")+' · 共现 '+deg+'</small></span>' +
        '<span class="w">'+n.w+'</span>' +
        sparkSVG(n.s, 62, 20, "var(--ink-2)", "var(--ink-3)") + '</li>';
    }).join("") + '</ul></div>';
};

REG.storylist = (m, d) => {
  $(m).innerHTML = [...d.stories].sort((a, b) => b.vel - a.vel).map(r =>
    '<div class="vt"><div class="nm" title="'+esc(r.t)+'">'+esc(r.t)+
      (r.also.length ? r.also.map(a => '<u class="also">也在 '+esc(a)+'</u>').join("") : "") +
      '<small>'+r.brd+' 源 · 共识 '+r.cons+'% · '+STAGE[r.stage]+'</small></div>' +
    '<div class="pc '+(r.vel>0?"up":"down")+'"><em class="ar">'+(r.vel>0?"▲":"▼")+'</em>'+
      (r.vel>0?"+":"")+r.vel+'%</div>' +
    sparkSVG(r.d.slice(-14), 70, 24, "var(--ink-2)", "var(--ink-3)") + '</div>').join("");
};

/* 有向链路：瓶颈落在哪一段是这个结构唯一要一眼看到的事 */
REG.flow = (m, d) => {
  $(m).innerHTML = '<div class="flow">' + d.nodes.map((t, i) => {
    const col = t.stress >= 85 ? "var(--st-critical)" : t.stress >= 60 ? "var(--st-warning)" : "var(--accent)";
    const top = [...t.members].sort((a, b) => b.h - a.h).slice(0, 4);
    return (i ? '<div class="arw" aria-hidden="true">▶</div>' : "") +
      '<div class="seg"><div class="box" style="border-top-color:'+col+'" tabindex="0" ' +
      'data-tip="'+esc(t.l)+'|紧张度 '+t.stress+' / 100|'+
      (t.stress>=85?"瓶颈环节":t.stress>=60?"偏紧":"宽松")+'|近 30 天 '+sum(t.d)+' 篇">' +
      '<div class="t">'+esc(t.l)+'</div>' +
      '<div class="s"><span>紧张度</span><span style="color:'+col+'">'+t.stress+'</span></div>' +
      '<span class="meter"><i style="width:'+t.stress+'%;background:'+col+'"></i></span>' +
      top.map(p => '<u>'+(p.h>=3?'<b>'+esc(p.n)+'</b>':esc(p.n))+'</u>').join("") +
      '</div></div>';
  }).join("") + '</div>' +
  '<div class="lgrow"><span><i style="background:var(--st-critical)"></i>紧张度 ≥ 85 瓶颈</span>' +
  '<span><i style="background:var(--st-warning)"></i>60–84 偏紧</span>' +
  '<span><i style="background:var(--accent)"></i>&lt; 60 宽松</span>' +
  '<span style="color:var(--ink-3)">块内为该环节近 30 天故事密度最高的成员</span></div>';
};

REG.heatgrid = (m, d) => {
  const bkt = makeBucketer(d.rows.flatMap(r => r.d));
  const day = dayFn(d.asOf);
  $(m).innerHTML = d.rows.map(r =>
    '<div class="mtx-r"><span class="ml" title="'+esc(r.label)+'">'+esc(r.label)+'</span>' +
    '<span class="cells">' + r.d.map((v, i) =>
      '<i tabindex="0" data-b="'+bkt(v)+'" data-tip="'+esc(r.label)+'|'+day(i)+' · '+v+d.unit+'"></i>').join("") +
    '</span><span class="mv">'+r.val+'</span></div>').join("") +
    '<div class="scale">低 <i style="background:var(--s0);box-shadow:inset 0 0 0 1px var(--hairline)"></i>' +
    [1,2,3,4,5,6].map(i => '<i style="background:var(--s'+i+')"></i>').join("") +
    ' 高 <span>（分位分档，阈值 '+bkt.breaks.join(" / ")+d.unit+'/日）</span></div>';
};

REG.composition = (m, d) => {
  $(m).innerHTML = d.rows.map(r => {
    const top = d.regions[r.v.indexOf(Math.max(...r.v))].n;
    return '<div style="margin-bottom:9px"><div class="rowlab"><span>'+esc(r.n)+
      '</span><span>'+esc(top)+' '+Math.max(...r.v)+'%</span></div><div class="stack">' +
      r.v.map((v, i) => v <= 0 ? "" :
        '<i tabindex="0" style="width:'+v+'%;background:'+d.regions[i].c+'" data-tip="'+esc(r.n)+'|'+
        esc(d.regions[i].n)+' '+v+'%"></i>').join("") + '</div></div>';
  }).join("") + '<div class="lgrow">' + d.regions.map(x =>
    '<span><i style="background:'+x.c+'"></i>'+esc(x.n)+'</span>').join("") +
    '<span style="color:var(--ink-3)">最大占比已直接标注</span></div>';
};

/* 有序阶梯：级别的升降比当前级别更值钱 */
REG.ladder = (m, d) => {
  const byLvl = {};
  d.items.forEach(c => (byLvl[c.lvl] = byLvl[c.lvl] || []).push(c));
  $(m).innerHTML = '<div class="lad2">' + d.levels.map(r => {
    const items = (byLvl[r.n] || []).sort((a, b) => b.vol - a.vol);
    return '<div class="lv"><div class="lh"><b>L'+r.n+' '+esc(r.t)+'</b>' +
      '<span style="font-size:10.5px;color:var(--ink-3)">'+esc(r.d)+'</span>' +
      '<span class="bar5" aria-hidden="true">' + [1,2,3,4,5].map(i =>
        '<i'+(i <= r.n ? ' style="background:var(--s'+Math.max(1,r.n)+')"' : "")+'></i>').join("") +
      '</span></div><div class="cards">' +
      (items.length ? items.map(c => {
        const mv = c.lvl > c.prev ? "up" : c.lvl < c.prev ? "down" : "";
        const mvTxt = mv === "up" ? "▲ L"+c.prev+"→L"+c.lvl
                    : mv === "down" ? "▼ L"+c.prev+"→L"+c.lvl : "持平";
        return '<div class="card"'+(mv ? ' data-mv="'+mv+'"' : "")+' tabindex="0" ' +
          'data-tip="'+esc(c.n)+'|L'+c.lvl+' '+esc(r.t)+' · '+esc(c.k)+'|上周 L'+c.prev+
          '|体量 '+c.vol+' / 100|'+esc(c.note)+'">' +
          '<div class="cn">'+esc(c.n)+'</div>' +
          '<div class="cm"><span class="mv">'+mvTxt+'</span><span>'+esc(c.k)+'</span>' +
          '<span>体量 '+c.vol+'</span></div></div>';
      }).join("") : '<span style="font-family:var(--mono);font-size:10px;color:var(--ink-3)">—</span>') +
      '</div></div>';
  }).join("") + '</div>' +
  '<div class="lgrow"><span><i style="background:var(--st-critical);height:14px;width:2px"></i>本周升级</span>' +
  '<span><i style="background:var(--st-good);height:14px;width:2px"></i>本周降级</span>' +
  '<span style="color:var(--ink-3)">分级依据是已发生的行为，不含对意图的判断</span></div>';
};

REG.itemmeters = (m, d) => {
  $(m).innerHTML = [...d.items].sort((a, b) => b.lvl - a.lvl || b.vol - a.vol)
    .map(c => '<div class="tier"><div class="th">' +
      '<span class="stage" data-s="'+Math.min(4, c.lvl - 1)+'">L'+c.lvl+'</span>' +
      '<b>'+esc(c.n)+'</b><span>'+esc(c.k)+' · 体量 '+c.vol+'</span></div>' +
      '<div class="note">'+esc(c.note)+'</div>' +
      '<span class="meter" tabindex="0" style="display:block" data-tip="'+esc(c.n)+'|级别 L'+c.lvl+
        ' · '+esc(c.k)+'|近 30 天报道体量 '+c.vol+' / 100|'+esc(c.note)+'">' +
      '<i style="width:'+c.vol+'%;background:var(--s'+Math.max(1, c.lvl)+')"></i></span></div>').join("");
};

/* 共轴时间带：量纲不同的序列归一化到基期 100 共用一根轴 —— 绝不双轴 */
REG.timeline = (m, d) => {
  const W = 1200, L = 46, R = 104;
  const topY = 20, topH = 100, axY = 140, botY = 174, botH = 106, H = 300;
  const N = 30, xs = i => L + i * (W - L - R) / (N - 1);
  const day = dayFn(d.asOf);
  const nMax = Math.max(...d.narr);
  const nY = v => topY + topH - v / nMax * topH;
  const area = d.narr.map((v, i) => (i ? "L" : "M") + xs(i).toFixed(1) + " " + nY(v).toFixed(1)).join(" ");
  const norm = d.lines.map(l => ({ ...l, z: l.s.map(v => v / l.s[0] * 100) }));
  const all = norm.flatMap(l => l.z);
  const lo = Math.min(...all), hi = Math.max(...all);
  const bY = v => botY + botH - (v - lo) / (hi - lo || 1) * botH;
  const grid = [lo, (lo + hi) / 2, hi].map(v =>
    '<line x1="'+L+'" y1="'+bY(v).toFixed(1)+'" x2="'+(W-R)+'" y2="'+bY(v).toFixed(1)+
    '" stroke="var(--hairline)" stroke-width="1"></line>' +
    '<text x="'+(L-6)+'" y="'+(bY(v)+3).toFixed(1)+'" text-anchor="end" font-family="var(--mono)"' +
    ' font-size="9" fill="var(--ink-3)">'+v.toFixed(0)+'</text>').join("");
  const lines = norm.map(l => {
    const p = l.z.map((v, i) => (i ? "L" : "M") + xs(i).toFixed(1) + " " + bY(v).toFixed(1)).join(" ");
    const ly = bY(l.z[N - 1]);
    return '<path d="'+p+'" fill="none" stroke="'+l.c+'" stroke-width="2" stroke-linejoin="round"></path>' +
      '<circle cx="'+xs(N-1).toFixed(1)+'" cy="'+ly.toFixed(1)+'" r="3" fill="'+l.c+
      '" stroke="var(--surface)" stroke-width="2"></circle>' +
      '<text x="'+(xs(N-1)+8)+'" y="'+(ly+3).toFixed(1)+'" font-family="var(--mono)" font-size="9.5"' +
      ' fill="'+l.c+'">'+esc(l.sn)+'</text>';
  }).join("");
  const pins = d.pins.map(p =>
    '<g tabindex="0" data-tip="'+esc(p.l)+'|'+day(p.i)+'">' +
    '<line x1="'+xs(p.i).toFixed(1)+'" y1="'+topY+'" x2="'+xs(p.i).toFixed(1)+'" y2="'+(botY+botH)+
    '" stroke="var(--hairline-2)" stroke-width="1"></line>' +
    '<rect x="'+(xs(p.i)-2.5).toFixed(1)+'" y="'+(axY-9)+'" width="5" height="5" fill="var(--ink-2)"></rect>' +
    '<text x="'+(xs(p.i)+6).toFixed(1)+'" y="'+(axY-4)+'" font-family="var(--mono)" font-size="9"' +
    ' fill="var(--ink-2)">'+esc(p.l)+'</text></g>').join("");
  const ticks = [0, 7, 14, 21, 29].map(i =>
    '<text x="'+xs(i).toFixed(1)+'" y="'+(axY+15)+'" text-anchor="middle"' +
    ' font-family="var(--mono)" font-size="9" fill="var(--ink-3)">'+day(i)+'</text>').join("");
  const hits = d.narr.map((v, i) =>
    '<rect x="'+(xs(i)-(W-L-R)/(N-1)/2).toFixed(1)+'" y="'+topY+'" width="'+((W-L-R)/(N-1)).toFixed(1)+
    '" height="'+topH+'" fill="transparent" tabindex="0" data-tip="'+day(i)+'|叙事密度 '+v+' 篇|'+
    norm.map(l => esc(l.n)+' '+l.z[i].toFixed(1)).join("|")+'"></rect>').join("");
  $(m).innerHTML = '<div class="tl"><svg viewBox="0 0 '+W+' '+H+'" role="img"' +
    ' aria-label="上下双带共用一根时间轴：上带每日叙事密度，下带归一化指标线，竖线为事件标记">' +
    '<path d="'+area+' L'+xs(N-1).toFixed(1)+' '+(topY+topH)+' L'+L+' '+(topY+topH)+' Z"' +
      ' fill="var(--accent)" opacity=".26"></path>' +
    '<path d="'+area+'" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"></path>' +
    '<text x="'+L+'" y="'+(topY-6)+'" font-family="var(--mono)" font-size="9.5" fill="var(--ink-3)">' +
      '↑ 叙事密度 篇/日 · 峰值 '+nMax+'　　↓ 指标 归一化 基期=100 · 单一纵轴</text>' +
    grid + pins +
    '<line x1="'+L+'" y1="'+axY+'" x2="'+(W-R)+'" y2="'+axY+'" stroke="var(--hairline-2)" stroke-width="1"></line>' +
    ticks + lines + hits + '</svg>' +
    '<div class="lgrow"><span><i style="background:var(--accent);height:8px"></i>叙事密度（上带）</span>' +
    d.lines.map(l => '<span><i style="background:'+l.c+'"></i>'+esc(l.n)+
      ' <span style="color:var(--ink-3)">'+esc(l.raw)+'</span></span>').join("") +
    '<span style="color:var(--ink-3)">▪ 事件标记　三线归一化后共用一根纵轴，非双轴</span></div></div>';
};

/* 背离度比幅度不比方向 —— 无符号强度 vs 有符号收益率不可直接相减 */
REG.divergence = (m, d) => {
  const P = Math.max(...d.rows.map(r => Math.abs(r.price)));
  const rows = d.rows.map(r => ({ ...r,
    score: Math.round(Math.abs(r.narr / 100 - Math.abs(r.price) / P) * 100) }))
    .sort((a, b) => b.score - a.score);
  $(m).innerHTML = '<div class="dv-h"><span>标的</span><span>叙事热度</span>' +
    '<span>价格变动 30d</span><span>背离度</span></div>' +
    rows.map(r => {
      const half = Math.abs(r.price) / P * 50;
      const col = r.price >= 0 ? "var(--div-p2)" : "var(--div-n2)";
      return '<div class="dv-r"><div class="nm" title="'+esc(r.note)+'">'+esc(r.n)+'</div>' +
        '<span class="bar" tabindex="0" data-tip="'+esc(r.n)+'|叙事热度 '+r.narr+' / 100">' +
          '<i style="left:0;width:'+r.narr+'%;background:var(--accent)"></i></span>' +
        '<span class="bar ctr" tabindex="0" data-tip="'+esc(r.n)+'|价格变动 '+
          (r.price>0?"+":"")+r.price+'%|'+esc(r.note)+'">' +
          '<i style="'+(r.price>=0 ? "left:50%" : "left:"+(50-half)+"%")+';width:'+half+
          '%;background:'+col+'"></i></span>' +
        '<span class="sc" style="color:'+(r.score>=45?"var(--st-critical)":r.score>=30?"var(--st-warning)":"var(--ink-2)")+
          '">'+r.score+'</span></div>';
    }).join("") +
    '<div class="lgrow"><span><i style="background:var(--accent)"></i>叙事热度 0–100</span>' +
    '<span><i style="background:var(--div-p2)"></i>价格上行</span>' +
    '<span><i style="background:var(--div-n2)"></i>价格下行</span>' +
    '<span style="color:var(--ink-3)">背离度 = 两者幅度标准化后之差（不比方向）</span></div>';
};

REG.disagreement = (m, d) => {
  const G = { "2":"++", "1":"+", "0":"·", "-1":"−", "-2":"✕" };
  const NM = { "2":"强支持", "1":"支持", "0":"未表态", "-1":"质疑", "-2":"否认 / 反驳" };
  const scoreOf = c => {
    const mean = sum(c.v) / c.v.length;
    return Math.round(Math.sqrt(c.v.reduce((a, b) => a + (b - mean) ** 2, 0) / c.v.length) / 2 * 100);
  };
  const groups = d.groups.map(g => ({ ...g,
    claims: g.claims.map(c => ({ ...c, score: scoreOf(c) })).sort((a, b) => b.score - a.score) }))
    .sort((a, b) => (b.claims[0]?.score || 0) - (a.claims[0]?.score || 0));
  $(m).innerHTML = groups.map(g =>
    (g.label ? '<div class="dm-glabel">'+esc(g.label)+'</div>' : "") +
    '<div class="dm-h"><span>断言</span>' +
    g.set.cols.map(s => '<span title="'+esc(g.set.names[s])+'">'+s+'</span>').join("") +
    '<span>分歧度</span></div>' +
    g.claims.map(c => '<div class="dm-r"><div class="cl"><b title="'+esc(c.c)+'">'+esc(c.c)+
      '</b><small>'+esc(c.n)+'</small></div>' +
      c.v.map((v, i) => '<u data-v="'+v+'" tabindex="0" data-tip="'+esc(g.set.names[g.set.cols[i]])+'|'+
        NM[v]+'|「'+esc(c.c)+'」">'+G[v]+'</u>').join("") +
      '<span class="sc" style="color:'+(c.score >= 70 ? "var(--st-critical)"
        : c.score >= 45 ? "var(--st-warning)" : "var(--ink-2)")+'">'+c.score+'</span></div>').join("")
  ).join("") +
  '<div class="dm-lg">立场 <i style="background:var(--div-n2)"></i>否认 ✕' +
  ' <i style="background:var(--div-n1)"></i>质疑 −' +
  ' <i style="background:var(--div-0)"></i>未表态 ·' +
  ' <i style="background:var(--div-p1)"></i>支持 +' +
  ' <i style="background:var(--div-p2)"></i>强支持 ++</div>';
};

REG.questions = (m, d) => {
  $(m).innerHTML = '<ul>' + d.questions.map(q =>
    '<li><div class="q">'+esc(q.q)+'</div><div class="m">' +
    '<span><b>故事</b> '+esc(q.s)+'</span><span><b>等待</b> '+esc(q.w)+'</span>' +
    '<span class="age">悬置 '+q.age+'d</span></div></li>').join("") + '</ul>';
};

/* 启动：视图列表由生成时的结构检测决定，这里只按注册表逐个渲染 */
renderSensors(); renderField();
VIEWS.forEach(v => { if (REG[v.type]) REG[v.type]("#" + v.mount, v.data); });
bindTip(document.body);
`;

/* ═══════════════ ⑤ 页面模板 ═══════════════ */

const MOUNT_CLASS = { questions: "oq", itemmeters: "cor" };

function page(c, slice, views) {
  const statItems = [
    ["采集", slice.meta.collected.toLocaleString("en-US"), " 篇 / 24h"],
    ["信源", slice.meta.sources.toLocaleString("en-US"), " 个"],
    ["活跃故事", slice.stories.length, ""],
    ["断言", sum(slice.claimGroups.map(g => g.claims.length)), ""],
    ["未解问题", slice.questions.length, ""],
  ];
  views.forEach((v, i) => { v.mount = "m" + i; });

  return `<title>NewsAssistant · ${c.name}</title>

<style>${css(c)}</style>

<canvas id="field" aria-hidden="true"></canvas>

<div class="console">
  <div class="rail">
    <div class="brand"><span class="dot"></span><b>NEWSASSISTANT</b></div>
    <div class="chans">${CHANNELS.map(x =>
      `<button class="chan"${x.id === c.id ? ' aria-current="true"' : " disabled"}>${x.name}</button>`).join("")}</div>
    <div class="railpad"></div>
    <span class="mock">示例数据 · 布局原型</span>
  </div>

  <div class="status">${statItems.map(([k, v, u]) =>
    `<div>${k} <b>${v}</b>${u}</div>`).join("")}
    <div class="live">● 上次同步 ${slice.meta.sync} UTC</div></div>

  ${slice.sensors ? '<div class="sensors" id="sensors"></div>' : ""}

  <div class="grid">
${views.map(v => `    <section class="panel c${v.span}">
      <header><h2>${v.title}</h2><span class="note">${v.note || ""}</span></header>
      <div class="body"><div id="${v.mount}"${MOUNT_CLASS[v.type]
        ? ` class="${MOUNT_CLASS[v.type]}${v.wide ? " wide" : ""}"` : ""}></div></div>
    </section>`).join("\n")}
  </div>

  <footer>
    <b>这是一份布局原型。</b>面板中的全部数字、故事、断言与信源立场均为演示用的<b>虚构数据</b>，不代表任何真实事件或报道。<br>
    架构说明 — 频道是对通用存储的<b>保存查询</b>；本页版面由查询结果中检测到的数据结构自动选择（docs/views.md）。
    编码语法全局一致：色阶=密度（分位分档），▲▼=方向，蓝↔红+字符=立场，状态色仅表示越阈。
  </footer>
</div>

<div id="tip" role="status" aria-live="polite"></div>

<script>
(() => {
const DATA = ${JSON.stringify({ sensors: slice.sensors, field: slice.fieldStories.map(s => s.d) })};
const VIEWS = ${JSON.stringify(views.map(({ type, mount, data }) => ({ type, mount, data })))};
${CORE_JS}
})();
</script>
`;
}

/* ═══════════════ 生成 ═══════════════ */

for (const c of CHANNELS) {
  const slice = buildSlice(c.query);
  const views = selectViews(slice, c.name);
  writeFileSync(join(OUT, c.id + ".html"), page(c, slice, views));
  console.log(`✓ ${c.id}.html  [${views.map(v => `${v.type}:${v.span}`).join(" ")}]`);
}
