/* Dashboard —— 运行时向 /api 取数。
 *
 * 这里没有一个频道的名字、没有一条领域规则：频道、它的查询、它的标识色
 * 全部来自 /api/channels（D3/D2）。页面只会做四件通用的事：
 *   列频道 → 拉该频道的故事 → 按数据结构渲染 → 点开看带引用的综述。
 *
 * 编码语法与原型一致（docs/views.md）：色阶=密度（分位分档，阈值写进图例），
 * 方向由 ▲▼ 承载不用颜色，状态色只留给越阈提示。
 */

const $ = (id) => document.getElementById(id);
const api = async (p) => {
  const r = await fetch(p);
  if (!r.ok) throw new Error(`${p} → ${r.status}`);
  return r.json();
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const state = { channels: [], channel: null, stories: [], story: null, breaks: [] };

/* ── 分位分档（D15）：日报道量动态范围只有 ~10 倍，线性会把九成格子压进最低档，
      对数又全推高。分位让六档都被用上，代价是间距非线性 —— 所以阈值必须写进图例。 */
function quantileBreaks(values) {
  const nz = values.filter((v) => v > 0).sort((a, b) => a - b);
  if (!nz.length) return [];
  const at = (q) => nz[Math.min(nz.length - 1, Math.floor(q * nz.length))];
  const raw = [at(0.17), at(0.34), at(0.5), at(0.67), at(0.84)];
  return [...new Set(raw)];                       // 去重：小样本时档位会塌缩
}
const bucket = (v, breaks) => {
  if (v <= 0) return 0;
  let b = 1;
  for (const t of breaks) if (v > t) b++;
  return Math.min(b, 6);
};

const fmtAgo = (iso) => {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return `${Math.max(0, Math.round(s))}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  if (s < 172800) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
};
const arrow = (v) => (v > 4 ? "▲" : v < -4 ? "▼" : "·");

/* ── tooltip：hover 与键盘焦点走同一条路径 ── */
const tip = $("tip");
function bindTip(el, text) {
  const show = (e) => {
    tip.textContent = text;
    tip.classList.add("on");
    const r = el.getBoundingClientRect();
    const x = e && e.clientX ? e.clientX : r.left + r.width / 2;
    tip.style.left = Math.min(x + 12, innerWidth - tip.offsetWidth - 8) + "px";
    tip.style.top = Math.max(8, r.top - tip.offsetHeight - 8) + "px";
  };
  const hide = () => tip.classList.remove("on");
  el.addEventListener("mouseenter", show);
  el.addEventListener("mousemove", show);
  el.addEventListener("mouseleave", hide);
  el.addEventListener("focus", show);
  el.addEventListener("blur", hide);
}

/* ── 频道标识色：频道是数据，颜色是它的属性，前端不硬编码 ── */
// 生效主题 = 显式选择优先，否则跟随系统。主题不是"把暗色反过来"：
// 两套色阶各自校验过，所以换主题必须重新写入色值，不能只换 CSS 变量表。
const isDark = () => {
  const explicit = document.documentElement.getAttribute("data-theme");
  if (explicit) return explicit === "dark";
  return matchMedia("(prefers-color-scheme: dark)").matches;
};

function applyPalette(ch) {
  const dark = isDark();
  const p = (ch.palette || {})[dark ? "dark" : "light"];
  const root = document.documentElement.style;
  if (!p) return;
  root.setProperty("--accent", p.accent);
  (p.ramp || []).forEach((h, i) => root.setProperty(`--s${i + 1}`, h));
  root.setProperty("--accent-2", (p.ramp || [])[3] || p.accent);
}

function renderChannels() {
  $("chans").innerHTML = state.channels.map((c) =>
    `<button class="chan" data-key="${esc(c.key)}"
      aria-current="${c.key === state.channel?.key}">${esc(c.name)}</button>`).join("");
  $("chans").querySelectorAll(".chan").forEach((b) =>
    b.onclick = () => selectChannel(b.dataset.key));
}

function renderStatus(health, stats) {
  const lr = health.last_run;
  const cls = lr?.error ? "bad" : health.scheduler ? "live" : "warn";
  const mark = lr?.error ? "✕" : health.scheduler ? "●" : "○";
  $("status").innerHTML = `
    <div><span class="${cls}">${mark}</span> 调度器 <b>${health.scheduler ? "运行中" : "关闭"}</b></div>
    <div>本轮 <b>${health.cycle_running ? "推进中" : "空闲"}</b></div>
    <div>最近阶段 <b>${esc(lr?.stage || "—")}</b> ${fmtAgo(lr?.started_at)} 前</div>
    <div>已合成 <b>${stats.synthesized}</b> / ${stats.stories} 故事</div>`;
}

function renderSensors(stats) {
  const tiles = [
    ["文档", stats.docs, "status=ok"],
    ["已抽取", stats.extracted, `${stats.docs ? Math.round(stats.extracted / stats.docs * 100) : 0}%`],
    ["断言", stats.claims, "claim 级"],
    ["实体", stats.entities, "消歧后"],
    ["活跃故事", stats.stories, "state=active"],
    ["已合成", stats.synthesized, "带引用综述"],
  ];
  $("sensors").innerHTML = tiles.map(([k, v, d]) => `
    <div class="sensor">
      <div class="lbl"><span class="eyebrow">${k}</span><span class="dl">${esc(d)}</span></div>
      <div class="val">${v ?? 0}</div>
    </div>`).join("");
}

function renderStream() {
  const el = $("stream");
  if (!state.stories.length) {
    el.innerHTML = `<p class="empty">这个频道当前没有命中的故事。
      频道是保存的查询 —— 空结果说明库里还没有匹配的数据，不是页面坏了。</p>`;
    $("streamNote").textContent = "0 个故事";
    return;
  }
  const all = state.stories.flatMap((s) => s.series || []);
  state.breaks = quantileBreaks(all);
  const days = (state.stories[0].series || []).length;

  el.innerHTML = state.stories.map((s) => {
    const sc = s.scalars || {};
    const cells = (s.series || []).map((v, i) =>
      `<i data-b="${bucket(v, state.breaks)}" data-v="${v}" data-d="${days - 1 - i}"></i>`).join("");
    const vel = Number(sc.velocity ?? 0);
    return `<button class="vt" data-id="${s.id}" aria-current="${state.story?.id === s.id}">
      <span class="nm">
        <span>${esc(s.title)}</span>
        <small>
          <span class="stage" data-s="${sc.stage ?? 2}">S${sc.stage ?? 2}</span>
          ${sc.docs ?? 0} 篇 · ${s.synthesized_at ? "已合成" : "未合成"} · ${fmtAgo(s.updated_at)} 前
        </small>
      </span>
      <span class="cells" style="grid-template-columns:repeat(${days},1fr)">${cells}</span>
      <span class="pc"><em class="ar">${arrow(vel)}</em>${vel > 0 ? "+" : ""}${vel}%</span>
      <span class="bd">${sc.breadth ?? 0} 源<span class="meter" style="margin-top:3px">
        <i style="width:${Math.min(100, (sc.breadth ?? 0) * 20)}%"></i></span></span>
    </button>`;
  }).join("") + scaleLegend();

  el.querySelectorAll(".vt").forEach((b) => b.onclick = () => selectStory(+b.dataset.id));
  el.querySelectorAll(".cells i").forEach((c) =>
    bindTip(c, `${c.dataset.d} 天前 · 吸收 ${c.dataset.v} 篇`));
  $("streamNote").textContent = `${state.stories.length} 个故事 · 近 ${days} 天`;
}

/* 图例把分位阈值写明 —— 非线性分档不写阈值就是误导 */
function scaleLegend() {
  const labels = state.breaks.length
    ? `0 · ${state.breaks.map((t) => `≤${t}`).join(" · ")} · 更多`
    : "0 · 1+（样本太少，未分档）";
  return `<div class="scale"><span>日吸收量</span>
    ${[0, 1, 2, 3, 4, 5, 6].map((b) => `<i style="background:var(--s${b})"></i>`).join("")}
    <span>${esc(labels)}</span>
    <span style="margin-left:auto">分位分档（D15）；方向用 ▲▼ 不用颜色</span></div>`;
}

async function selectStory(id) {
  const s = await api(`/api/stories/${id}`);
  state.story = s;
  renderStream();
  const claims = new Map((s.claims || []).map((c) => [c.id, c]));
  const sentences = Array.isArray(s.summary) ? s.summary
    : (s.summary?.sentences || []);
  const cite = (ids) => (ids || []).map((i) =>
    `<button class="cite" data-c="${i}">#${i}</button>`).join("");

  const tl = (s.timeline || []).map((t) =>
    `<div class="tlrow"><b>${esc(t.when || "")}</b>
       <span>${esc(t.what || "")}${cite(t.claim_ids)}</span></div>`).join("");
  const oq = (s.open_questions || []).map((q) =>
    `<li>${esc(typeof q === "string" ? q : q.text || q.question || "")}</li>`).join("");

  $("detailTitle").textContent = s.title;
  $("detailNote").textContent = s.synthesized_at
    ? `合成于 ${fmtAgo(s.synthesized_at)} 前` : "尚未合成";
  $("detail").innerHTML = `
    <div class="sum">${sentences.length
      ? sentences.map((x) => `<p>${esc(x.text)}${cite(x.claim_ids)}</p>`).join("")
      : `<p class="empty">这个故事还没有综述（合成阶段按 velocity 与新动静挑选故事）。
          下面是它已归档的断言。</p>`}</div>
    <div id="claimslot"></div>
    ${tl ? `<h3 class="eyebrow" style="margin:14px 0 4px">时间线</h3>${tl}` : ""}
    ${oq ? `<h3 class="eyebrow" style="margin:14px 0 4px">开放问题</h3>
            <div class="oq"><ul>${oq}</ul></div>` : ""}
    <h3 class="eyebrow" style="margin:14px 0 4px">断言（${(s.claims || []).length}）</h3>
    ${(s.claims || []).slice(0, 12).map((c) => claimCard(c)).join("") || '<p class="empty">无</p>'}`;

  $("detail").querySelectorAll(".cite").forEach((b) => b.onclick = () => {
    const c = claims.get(+b.dataset.c);
    $("claimslot").innerHTML = c ? claimCard(c)
      : `<div class="claimcard">引用 #${b.dataset.c} 不在本故事的断言里</div>`;
    $("claimslot").scrollIntoView({ block: "nearest" });
  });
}

const stanceWord = (v) => ({ "-2": "强烈否定", "-1": "偏否定", 0: "中立", 1: "偏肯定", 2: "强烈肯定" }[v] ?? "未标");
const claimCard = (c) => `<div class="claimcard">${esc(c.text)}
  <div class="m"><span>#${c.id}</span><span>源 ${esc(c.source)}</span>
  <span>立场 ${esc(stanceWord(c.stance))}</span></div></div>`;

async function renderRuns() {
  const runs = await api("/api/runs?limit=14");
  $("runNote").textContent = runs.length ? `最近 ${runs.length} 次阶段执行` : "尚无记录";
  $("runs").innerHTML = runs.length ? runs.map((r) => {
    const s = r.error ? r.error : Object.entries(r.stats || {})
      .map(([k, v]) => `${k}=${v}`).join(" ");
    return `<div class="run"><b>${esc(r.stage)}</b>
      <span class="st ${r.error ? "err" : ""}">${esc(s || "—")}</span>
      <span class="ago">${fmtAgo(r.started_at)}</span></div>`;
  }).join("") : `<p class="empty">调度器还没跑过一轮。</p>`;
}

/* ── 视图注册表（D4）────────────────────────────────────────
 * 键是**结构**的名字，不是领域的名字。后端说这个切片里有什么结构，
 * 这里就渲染什么；哪个当主舞台由 weight 决定，不由谁写死。
 */
const VIEWS = {
  chain: {
    title: "有向链路",
    note: (d) => `${d.evidence.stable_edges} 条稳定依赖 · ${d.evidence.depth} 层拓扑`,
    render: (d) => {
      const inbound = {};
      d.payload.edges.forEach((e) => (inbound[e.to] ||= []).push(e));
      return `<div class="flow">${d.payload.layers.map((layer, i) => `
        ${i ? '<div class="arw">→</div>' : ""}
        <div class="seg"><div class="box">
          <div class="t">第 ${i + 1} 层</div>
          ${layer.slice(0, 8).map((n) => `<u title="${esc(n)}">${esc(n)}
            ${inbound[n]?.length ? `<b>← ${inbound[n].length} 条上游</b>` : ""}</u>`).join("")}
        </div></div>`).join("")}</div>
        <div class="scale"><span>层内无先后；箭头方向来自断言的 who→whom，
        只保留重复出现 ≥${2} 次的边</span>
        <span style="margin-left:auto">环上的边已丢弃 ${d.evidence.edges_in_cycles} 条</span></div>`;
    },
  },

  network: {
    title: "共现网络",
    note: (d) => `${d.evidence.nodes} 节点 · 密度 ${d.evidence.density}`,
    render: (d) => {
      const N = d.payload.nodes, E = d.payload.edges;
      const W = 900, H = 380, cx = W / 2, cy = H / 2;
      // 确定性布局：按度数分内外两环 —— 不做动画模拟，可复现优先
      const pos = {};
      const hub = N.slice(0, Math.min(7, N.length)), rim = N.slice(hub.length);
      hub.forEach((n, i) => {
        const a = (i / hub.length) * 2 * Math.PI - Math.PI / 2;
        pos[n.name] = [cx + Math.cos(a) * 105, cy + Math.sin(a) * 88];
      });
      rim.forEach((n, i) => {
        const a = (i / Math.max(1, rim.length)) * 2 * Math.PI - Math.PI / 2;
        pos[n.name] = [cx + Math.cos(a) * 260, cy + Math.sin(a) * 155];
      });
      const maxw = Math.max(1, ...E.map((e) => e.w));
      const maxd = Math.max(1, ...N.map((n) => n.degree));
      return `<div class="net"><svg viewBox="0 0 ${W} ${H}" role="img"
        aria-label="实体共现网络：${N.length} 个实体">
        ${E.map((e) => {
          const [x1, y1] = pos[e.a] || [], [x2, y2] = pos[e.b] || [];
          if (x1 === undefined || x2 === undefined) return "";
          return `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}"
            x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="var(--hairline-2)"
            stroke-width="${(0.6 + 2 * e.w / maxw).toFixed(2)}" />`;
        }).join("")}
        ${N.map((n) => {
          const [x, y] = pos[n.name]; const r = 4 + 5 * n.degree / maxd;
          // 形状=类型的语法留给实体页；这里只有一类节点，故统一用圆
          return `<g><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}"
              fill="var(--s5)" stroke="var(--surface)" stroke-width="2"><title>${esc(n.name)} · 度 ${n.degree}</title></circle>
            <text x="${x.toFixed(1)}" y="${(y - r - 5).toFixed(1)}" text-anchor="middle"
              font-size="10" font-family="var(--mono)" fill="var(--ink-2)">${esc(n.name.slice(0, 16))}</text></g>`;
        }).join("")}
      </svg></div>
      <div class="scale"><span>连线粗细 = 共现次数；节点大小 = 加权度</span>
        <span style="margin-left:auto">出现在过半故事里的实体已排除 ${d.evidence.excluded_ubiquitous} 个（连一切=无信息）</span></div>`;
    },
  },

  disagreement: {
    title: "分歧矩阵",
    note: (d) => `${d.evidence.stories_split} / ${d.evidence.stories_with_stance} 个故事内部有跨源立场差`,
    render: (d) => {
      const srcs = d.payload.sources;
      const cols = `grid-template-columns:minmax(140px,1fr) repeat(${srcs.length},34px) 44px`;
      const cell = (v) => {
        if (v === undefined) return `<u data-v="na" title="该源无断言">·</u>`;
        const b = Math.max(-2, Math.min(2, Math.round(v)));
        const ch = { "-2": "−−", "-1": "−", 0: "○", 1: "+", 2: "++" }[b];
        return `<u data-v="${b}" title="平均立场 ${v.toFixed(2)}">${ch}</u>`;
      };
      return `<div class="dm-h" style="${cols}"><span>故事</span>
          ${srcs.map((s) => `<span>${esc(s.slice(0, 4))}</span>`).join("")}<span>跨度</span></div>
        ${d.payload.stories.map((s) => {
          const vals = srcs.map((k) => s.sources[k]?.stance);
          const got = vals.filter((v) => v !== undefined);
          const spread = Math.max(...got) - Math.min(...got);
          return `<div class="dm-r" style="${cols}">
            <span class="cl"><b title="${esc(s.title)}">${esc(s.title)}</b></span>
            ${vals.map(cell).join("")}
            <span class="sc" style="font-family:var(--mono);font-size:11px;text-align:right">${spread.toFixed(1)}</span>
          </div>`;
        }).join("")}
        <div class="dm-lg">
          <i style="background:var(--div-n2)"></i><span>−− 否定</span>
          <i style="background:var(--div-0)"></i><span>○ 中立</span>
          <i style="background:var(--div-p2)"></i><span>++ 肯定</span>
          <span style="margin-left:auto">立场同时由字符承载，不单靠颜色</span>
        </div>`;
    },
  },

  matrix: {
    title: "热力矩阵",
    note: (d) => `${d.evidence.rows} 源 × ${d.evidence.cols} 天`,
    render: (d) => {
      const map = new Map(d.payload.cells.map((c) => [`${c.r}|${c.c}`, c.v]));
      const breaks = quantileBreaks(d.payload.cells.map((c) => c.v));
      const cols = d.payload.cols;
      return d.payload.rows.map((r) => `<div class="mtx-r">
          <span class="ml">${esc(r)}</span>
          <span class="cells" style="grid-template-columns:repeat(${cols.length},1fr)">
            ${cols.map((c) => {
              const v = map.get(`${r}|${c}`) || 0;
              return `<i data-b="${bucket(v, breaks)}" data-v="${v}" data-c="${c}" data-r="${esc(r)}"></i>`;
            }).join("")}
          </span></div>`).join("") + scaleLegendFor(breaks, "源 × 日 文档数");
    },
    after: (el) => el.querySelectorAll(".cells i").forEach((c) =>
      bindTip(c, `${c.dataset.r} · ${c.dataset.c} · ${c.dataset.v} 篇`)),
  },

  composition: {
    title: "信源构成",
    note: (d) => `${d.evidence.parts} 个独立信源 · 共 ${d.evidence.total} 篇`,
    render: (d) => {
      const total = d.payload.total;
      const parts = d.payload.parts.slice(0, 6);
      return `<div class="rowlab"><span>覆盖份额（转述已折叠回源头）</span>
          <span>首位 ${(d.evidence.top_share * 100).toFixed(0)}%</span></div>
        <div class="stack">${parts.map((p, i) =>
          `<i style="width:${(p.n / total * 100).toFixed(1)}%;background:var(--s${6 - Math.min(5, i)})"
             title="${esc(p.name)} ${p.n} 篇"></i>`).join("")}</div>
        <div class="parts">${parts.map((p, i) =>
          `<span><i style="background:var(--s${6 - Math.min(5, i)})"></i>${esc(p.name)}
             ${(p.n / total * 100).toFixed(0)}% · L${p.tier}</span>`).join("")}</div>`;
    },
  },

  open_questions: {
    title: "未解问题",
    note: (d) => `${d.evidence.questions} 个 · ${d.evidence.stories} 个故事`,
    render: (d) => `<div class="oq"><ul>${d.payload.items.flatMap((it) =>
      it.questions.map((q) => `<li>${esc(typeof q === "string" ? q : q.text || "")}
        <small style="display:block;color:var(--ink-3);font-family:var(--mono);font-size:9.5px">
        ${esc(it.title)}</small></li>`)).join("")}</ul></div>`,
  },
};

function scaleLegendFor(breaks, label) {
  const txt = breaks.length ? `0 · ${breaks.map((t) => `≤${t}`).join(" · ")} · 更多`
                            : "0 · 1+（样本太少，未分档）";
  return `<div class="scale"><span>${esc(label)}</span>
    ${[0, 1, 2, 3, 4, 5, 6].map((b) => `<i style="background:var(--s${b})"></i>`).join("")}
    <span>${esc(txt)}</span><span style="margin-left:auto">分位分档（D15）</span></div>`;
}

/* 布局：weight 最重者当主舞台，次重者进分栏；未触发的进检测报告。 */
async function renderStructure(key) {
  const r = await api(`/api/channels/${encodeURIComponent(key)}/structure`);
  const shown = r.detections.filter((d) => d.triggered && d.renderable && VIEWS[d.view]);
  const [main, second] = shown;

  const put = (panel, titleEl, noteEl, bodyEl, det) => {
    if (!det) { $(panel).hidden = true; return; }
    const v = VIEWS[det.view];
    $(titleEl).textContent = v.title;
    $(noteEl).textContent = v.note(det);
    $(bodyEl).innerHTML = v.render(det);
    v.after?.($(bodyEl));
    $(panel).hidden = false;
  };
  put("stagePanel", "stageTitle", "stageNote", "stage", main);
  put("secondPanel", "secondTitle", "secondNote", "second", second);

  // 剩下的触发项也要有去处：并进分栏面板下方，不静默丢弃
  const rest = shown.slice(2);
  if (rest.length && second) {
    $("second").insertAdjacentHTML("beforeend", rest.map((d) => `
      <h3 class="eyebrow" style="margin:16px 0 6px">${esc(VIEWS[d.view].title)}
        <span style="text-transform:none;letter-spacing:0"> · ${esc(VIEWS[d.view].note(d))}</span></h3>
      ${VIEWS[d.view].render(d)}`).join(""));
    rest.forEach((d) => VIEWS[d.view].after?.($("second")));
  }

  $("detNote").textContent = `${shown.length}/${r.detections.length} 个结构成立 · 切片 ${r.slice.stories} 个故事`;
  $("detections").innerHTML = r.detections.map((d) => `
    <div class="det">
      <b class="${d.triggered ? "on" : "off"}">${d.triggered ? "●" : "○"}
        ${esc(VIEWS[d.view]?.title || d.view)}</b>
      <span class="why">${esc(d.reason)}${d.triggered && !d.renderable
        ? ' <em>（检测到但按设计不渲染）</em>' : ""}</span>
    </div>`).join("");
}

async function selectChannel(key) {
  const r = await api(`/api/channels/${encodeURIComponent(key)}/stories?limit=40`);
  state.channel = r.channel;
  state.stories = r.stories;
  state.story = null;
  applyPalette(r.channel);
  renderChannels();
  renderStream();
  $("streamTitle").textContent = `故事流 · ${r.channel.name}`;
  location.hash = key;
  $("detail").innerHTML = `<p class="empty">左侧点开一个故事：综述每句都带 claim 级引用。</p>`;
  $("detailTitle").textContent = "故事详情";
  $("detailNote").textContent = "选择左侧任一故事";
  await renderStructure(key);
}

$("theme").onclick = () => {
  document.documentElement.setAttribute("data-theme", isDark() ? "light" : "dark");
  if (state.channel) applyPalette(state.channel);
};
// 未显式选择时跟随系统切换（色阶必须跟着换，见 applyPalette）
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (!document.documentElement.getAttribute("data-theme") && state.channel)
    applyPalette(state.channel);
});

async function boot() {
  const [health, stats, channels] = await Promise.all([
    api("/health"), api("/api/stats"), api("/api/channels"),
  ]);
  state.channels = channels;
  renderStatus(health, stats);
  renderSensors(stats);
  await renderRuns();
  const want = location.hash.slice(1);
  const pick = channels.find((c) => c.key === want) || channels[0];
  if (pick) await selectChannel(pick.key);
  else $("chans").innerHTML = '<span class="chan">未配置频道（na channels sync）</span>';
  $("genAt").textContent = `· 数据取自 ${new Date().toLocaleString("zh-CN")}`;
}

boot().catch((e) => {
  $("stream").innerHTML = `<p class="empty">接口出错：${esc(e.message)}</p>`;
});
setInterval(async () => {                 // 服务是活的，页面也该是活的
  try {
    const [h, s] = await Promise.all([api("/health"), api("/api/stats")]);
    renderStatus(h, s); renderSensors(s); await renderRuns();
  } catch { /* 静默：下一轮再试 */ }
}, 30000);
