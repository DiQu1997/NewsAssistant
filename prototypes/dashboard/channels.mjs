/* 四个频道的配置 —— 标识色、演示数据、领域专属面板。
 *
 * ⚠ 全部数据均为虚构，仅用于验证版式与视觉编码，不代表任何真实事件、
 *   报道、机构立场或市场数值。
 *
 * 日序列由定种子伪随机生成，动量与阶段从序列推导 —— 热力带、火花线、
 * 百分比三者因此永远自洽，不会出现「图在涨、数字在跌」的假数据穿帮。
 */

/* ── 序列生成 ── */
const mkSeries = (base, endMul, seed) => {
  let s = seed >>> 0;
  const rnd = () => ((s = (s * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
  return Array.from({ length: 30 }, (_, i) => {
    const t = i / 29;
    const trend = base * (1 + (endMul - 1) * Math.pow(t, 1.7));
    return Math.max(1, Math.round(trend * (0.74 + rnd() * 0.52)));
  });
};
const velOf = d => {
  const a = (d[27] + d[28] + d[29]) / 3, b = (d[21] + d[22] + d[23]) / 3;
  return Math.round((a - b) / b * 100);
};
const stageOf = v => v >= 45 ? 4 : v >= 16 ? 3 : v >= -12 ? 2 : 1;

/** 展开故事：{t, brd, cons, base, mul, seed} → 带 d / vel / stage 的完整记录 */
const stories = list => list.map(s => {
  const d = mkSeries(s.base, s.mul, s.seed);
  const vel = velOf(d);
  return { t: s.t, brd: s.brd, cons: s.cons, d, vel, stage: stageOf(vel) };
});

/* ═════════════════ 1 · AI 产业 ═════════════════ */

const AI = {
  id: "ai-industry", name: "AI 产业",
  dark:  { accent: "#9085e9", ramp: ["#2b2555","#3a3273","#4c4292","#6155b3","#7869d0","#9085e9"] },
  light: { accent: "#4a3aa7", ramp: ["#ded9f5","#c3baec","#a294dd","#8071c9","#6152b3","#4a3aa7"] },
  status: [
    { k: "采集", v: "2,847", u: " 篇 / 24h" }, { k: "信源", v: "184", u: " 个" },
    { k: "活跃故事", v: "34" }, { k: "待裁决分歧", v: "12" },
    { k: "未解问题", v: "27" }, { k: "去重率", v: "63.1%" },
    { k: "上次同步", v: "12:04", u: " UTC", live: true },
  ],
  data: {
    asOf: "2026-07-27T12:00:00Z",
    stories: stories([
      { t: "前沿模型发布窗口期",       brd: 31, cons: 34, base: 5,  mul: 9.0, seed: 11 },
      { t: "AI 资本开支回报之争",      brd: 29, cons: 19, base: 5,  mul: 8.2, seed: 23 },
      { t: "数据中心电力并网瓶颈",     brd: 27, cons: 71, base: 7,  mul: 5.4, seed: 37 },
      { t: "芯片出口管制调整",         brd: 26, cons: 38, base: 7,  mul: 3.3, seed: 41 },
      { t: "推理芯片交付节奏",         brd: 24, cons: 52, base: 13, mul: 2.3, seed: 53 },
      { t: "欧盟 AI Act 第二阶段落地", brd: 19, cons: 66, base: 3,  mul: 5.1, seed: 67 },
      { t: "开源权重模型能力追赶",     brd: 22, cons: 43, base: 9,  mul: 2.0, seed: 71 },
      { t: "智能体安全与评测标准",     brd: 14, cons: 58, base: 3,  mul: 3.4, seed: 83 },
      { t: "端侧推理与小模型",         brd: 12, cons: 74, base: 6,  mul: 1.6, seed: 97 },
      { t: "训练数据版权诉讼",         brd: 17, cons: 47, base: 15, mul: 0.42,seed: 103 },
      { t: "实验室人才流动",           brd: 15, cons: 61, base: 12, mul: 0.34,seed: 109 },
      { t: "企业采纳率调查口径分歧",   brd: 9,  cons: 28, base: 10, mul: 0.26,seed: 127 },
    ]),
    sensors: [
      { k: "B200 现货溢价", v: "+18.4%", d: "+3.1pt", dir: "up",
        s: [9,10,11,10,12,13,12,14,15,14,16,17,16,18,18.4] },
      { k: "前沿实验室在招岗位", v: "3,412", d: "−4.7%", dir: "down",
        s: [3810,3790,3840,3760,3720,3690,3710,3650,3600,3580,3540,3510,3480,3440,3412] },
      { k: "arXiv cs.AI 月投稿", v: "6,840", d: "+9.2%", dir: "up",
        s: [4900,5050,5180,5240,5410,5520,5680,5740,5910,6020,6180,6310,6470,6620,6840] },
      { k: "H100 云端时租", v: "$2.18", d: "−11.4%", dir: "down",
        s: [3.10,3.02,2.94,2.88,2.79,2.71,2.66,2.58,2.51,2.44,2.39,2.33,2.28,2.22,2.18] },
      { k: "AI 融资额 30d", v: "$14.2B", d: "+26.8%", dir: "up",
        s: [7.1,7.8,8.2,7.9,8.8,9.4,9.1,10.2,10.8,11.1,11.9,12.4,13.0,13.6,14.2] },
      { k: "SWE-bench SOTA", v: "79.4%", d: "+0.0pt", dir: "flat",
        s: [68.1,69.4,71.0,71.0,72.8,74.1,74.1,75.6,76.2,77.0,77.0,78.3,79.4,79.4,79.4] },
    ],
    sources: ["RTR","BBG","FT","INF","WSJ","OFF","TEC"],
    sourceNames: { RTR:"路透", BBG:"彭博", FT:"金融时报", INF:"The Information",
      WSJ:"华尔街日报", OFF:"官方公告 / IR", TEC:"技术博客 / arXiv" },
    claims: [
      { c:"AI 资本开支已超出近期可实现回报", n:"分析师立场分裂，无官方口径", v:[1,-1,2,1,-2,-2,0] },
      { c:"单次训练算力预算超过 10^27 FLOP", n:"公开数值区间 3×10^26 – 2×10^27", v:[1,2,0,2,0,-2,-1] },
      { c:"下一代旗舰模型将在 Q4 前发布", n:"报道时间窗跨度 11 周", v:[2,1,0,2,1,-2,0] },
      { c:"出口管制新规覆盖推理芯片", n:"规则文本尚未公布，均为转述", v:[1,0,1,2,0,-2,0] },
      { c:"B200 供给短缺将持续至明年上半年", n:"交付周期报道 26–44 周不等", v:[2,2,1,1,2,-1,0] },
      { c:"开源权重模型已在编码任务追平闭源", n:"依赖 benchmark 选择，口径不一", v:[0,-1,0,1,-1,0,2] },
      { c:"电力并网是明年产能的首要约束", n:"多为运营商侧信息，交叉验证弱", v:[2,1,2,0,1,1,0] },
    ],
    questions: [
      { q:"训练算力预算的公开数值相差近一个数量级，哪个口径成立？", s:"前沿模型发布窗口期",
        w:"等待任一实验室的技术报告或监管备案", age:19 },
      { q:"电力并网瓶颈是全国性的，还是集中在少数几个电网节点？", s:"数据中心电力并网瓶颈",
        w:"等待电网运营商季度并网队列披露", age:12 },
      { q:"B200 交付周期报道从 26 周到 44 周，差异来自客户分层还是口径？", s:"推理芯片交付节奏",
        w:"等待供应链厂商法说会问答", age:8 },
      { q:"出口管制新规是否把推理芯片纳入？现有报道全是转述。", s:"芯片出口管制调整",
        w:"等待规则原文在联邦公报刊出", age:6 },
      { q:"「开源已追平」的结论对 benchmark 选择有多敏感？", s:"开源权重模型能力追赶",
        w:"等待第三方在统一评测集上复现", age:23 },
      { q:"企业采纳率调查的分母定义不同，能否统一口径重算？", s:"企业采纳率调查口径分歧",
        w:"可自行处理：需拿到三家调查的原始问卷", age:31 },
    ],
    graph: {
      nodes: [
        { id:"OAI", l:"OpenAI", t:1, w:26 },   { id:"ANT", l:"Anthropic", t:1, w:24 },
        { id:"GDM", l:"DeepMind", t:1, w:21 }, { id:"NVDA",l:"NVIDIA", t:1, w:29 },
        { id:"MSFT",l:"微软", t:1, w:18 },      { id:"META",l:"Meta", t:1, w:16 },
        { id:"AMD", l:"AMD", t:1, w:13 },      { id:"TSMC",l:"台积电", t:1, w:15 },
        { id:"EUC", l:"欧盟委员会", t:1, w:12 },{ id:"BIS", l:"美商务部 BIS", t:1, w:11 },
        { id:"SA",  l:"S. Altman", t:2, w:17 },{ id:"DA",  l:"D. Amodei", t:2, w:15 },
        { id:"DH",  l:"D. Hassabis", t:2, w:12 },{ id:"JH", l:"J. Huang", t:2, w:16 },
        { id:"GPT", l:"GPT 系列", t:3, w:19 }, { id:"CLA", l:"Claude", t:3, w:17 },
        { id:"GEM", l:"Gemini", t:3, w:15 },   { id:"LLA", l:"Llama", t:3, w:11 },
        { id:"B200",l:"B200", t:3, w:20 },     { id:"MI4", l:"MI400", t:3, w:10 },
      ],
      edges: [
        ["OAI","SA",9],["OAI","GPT",9],["OAI","MSFT",7],["OAI","NVDA",6],
        ["ANT","DA",9],["ANT","CLA",9],["ANT","NVDA",5],["ANT","GDM",3],
        ["GDM","DH",8],["GDM","GEM",9],["META","LLA",8],["META","NVDA",4],
        ["NVDA","JH",8],["NVDA","B200",9],["NVDA","TSMC",7],["NVDA","BIS",5],
        ["AMD","MI4",8],["AMD","TSMC",5],["TSMC","B200",6],["BIS","TSMC",4],
        ["EUC","OAI",4],["EUC","GDM",3],["EUC","META",3],["MSFT","GPT",5],
        ["GPT","CLA",4],["CLA","GEM",3],["B200","MI4",4],["SA","JH",3],
      ],
      types: { 1:"公司 / 实验室", 2:"人物", 3:"模型 / 产品" },
    },
  },
  panels: `    <section class="panel c4">
      <header><h2>实体星图</h2><span class="note">近 14 天共现</span></header>
      <div class="body"><div class="cons">
        <svg id="cons" viewBox="0 0 400 300" role="img"
          aria-label="实体共现关系图：节点为公司、人物与模型产品，形状区分类型，大小表示近期活跃度，连线表示在同一故事中共同出现"></svg>
        <div class="lgrow">
          <span><svg width="11" height="11" viewBox="0 0 11 11" aria-hidden="true"><circle cx="5.5" cy="5.5" r="4.4" fill="var(--accent)"/></svg>公司 / 实验室</span>
          <span><svg width="11" height="11" viewBox="0 0 11 11" aria-hidden="true"><rect x="1.5" y="1.5" width="8" height="8" fill="var(--accent)"/></svg>人物</span>
          <span><svg width="11" height="11" viewBox="0 0 11 11" aria-hidden="true"><rect x="1.9" y="1.9" width="7.2" height="7.2" transform="rotate(45 5.5 5.5)" fill="var(--accent)"/></svg>模型 / 产品</span>
          <span style="color:var(--ink-3)">大小 = 近期活跃度</span>
        </div></div></div>
    </section>

    <section class="panel c5">
      <header><h2>分歧矩阵</h2><span class="note">按分歧度排序</span></header>
      <div class="body"><div class="dm" id="dm"></div></div>
    </section>

    <section class="panel c3">
      <header><h2>未解问题</h2><span class="note">27 项 · 显示 6</span></header>
      <div class="body"><div class="oq"><ul id="oq"></ul></div></div>
    </section>`,
  extraJS: `
/* 实体类型用形状编码，不用色相 —— 抗色觉缺陷，印刷与 forced-colors 下同样成立，
   颜色因此可以整个让给频道标识色，尺寸留给活跃度。 */
function renderConstellation() {
  const G = DATA.graph, W = 400, H = 300;
  const { nodes, idx } = forceLayout(G.nodes, G.edges, W, H, 20260727);
  const shape = (x, y, r, fill) => ({
    1: '<circle cx="'+x+'" cy="'+y+'" r="'+r+'" fill="'+fill+'"></circle>',
    2: '<rect x="'+(x-r*.9)+'" y="'+(y-r*.9)+'" width="'+(r*1.8)+'" height="'+(r*1.8)+'" fill="'+fill+'"></rect>',
    3: '<rect x="'+(x-r*.82)+'" y="'+(y-r*.82)+'" width="'+(r*1.64)+'" height="'+(r*1.64)+
       '" transform="rotate(45 '+x+' '+y+')" fill="'+fill+'"></rect>' });
  const links = G.edges.map(([p, q, w]) => {
    const a = nodes[idx[p]], b = nodes[idx[q]];
    return '<line x1="'+a.x.toFixed(1)+'" y1="'+a.y.toFixed(1)+'" x2="'+b.x.toFixed(1)+'" y2="'+b.y.toFixed(1)+
      '" stroke="var(--hairline-2)" stroke-width="'+(.5+w*.13).toFixed(2)+'" opacity=".85"></line>';
  }).join("");
  const marks = nodes.map(n => {
    const r = 3.2 + Math.sqrt(n.w) * 1.15, x = +n.x.toFixed(1), y = +n.y.toFixed(1);
    const deg = G.edges.filter(e => e[0] === n.id || e[1] === n.id).length;
    return '<g tabindex="0" data-tip="'+esc(n.l)+'|'+G.types[n.t]+'|活跃度 '+n.w+' · 共现 '+deg+' 个实体">' +
      shape(x, y, r + 2, "var(--surface)")[n.t] + shape(x, y, r, "var(--accent)")[n.t] +
      '<text x="'+x+'" y="'+(y-r-4.5).toFixed(1)+'" text-anchor="middle" font-family="var(--mono)"' +
      ' font-size="8.5" fill="var(--ink-2)">'+esc(n.l)+'</text></g>';
  }).join("");
  $("#cons").innerHTML = links + marks;
}`,
  extraBoot: "renderConstellation();",
};

/* ═════════════════ 2 · 半导体 ═════════════════ */

const SEMI = {
  id: "semiconductor", name: "半导体",
  dark:  { accent: "#22bd80", ramp: ["#0f4232","#12583f","#15704f","#18885f","#1ba26f","#22bd80"] },
  light: { accent: "#128257", ramp: ["#d0eee0","#a8ddc6","#7ac9a8","#4bb388","#279a6d","#128257"] },
  status: [
    { k: "采集", v: "1,930", u: " 篇 / 24h" }, { k: "信源", v: "142", u: " 个" },
    { k: "含一手备案", v: "311", u: " 篇" }, { k: "活跃故事", v: "28" },
    { k: "待裁决分歧", v: "9" }, { k: "去重率", v: "58.4%" },
    { k: "上次同步", v: "11:47", u: " UTC", live: true },
  ],
  data: {
    asOf: "2026-07-27T12:00:00Z",
    stories: stories([
      { t: "HBM 供给与分配",           brd: 28, cons: 41, base: 6,  mul: 7.6, seed: 211 },
      { t: "先进封装产能扩张",         brd: 25, cons: 55, base: 8,  mul: 4.9, seed: 223 },
      { t: "存储涨价周期",             brd: 24, cons: 33, base: 9,  mul: 4.2, seed: 227 },
      { t: "High-NA EUV 导入进度",     brd: 18, cons: 62, base: 4,  mul: 4.4, seed: 233 },
      { t: "设备出口许可变动",         brd: 23, cons: 29, base: 7,  mul: 2.8, seed: 239 },
      { t: "成熟制程价格战",           brd: 21, cons: 47, base: 11, mul: 2.1, seed: 251 },
      { t: "美国 Fab 建设与人力缺口",  brd: 17, cons: 68, base: 6,  mul: 1.9, seed: 257 },
      { t: "汽车芯片库存去化",         brd: 15, cons: 73, base: 8,  mul: 1.4, seed: 263 },
      { t: "硅片长约重议",             brd: 12, cons: 59, base: 5,  mul: 1.5, seed: 269 },
      { t: "封测环节涨价传导",         brd: 14, cons: 44, base: 7,  mul: 1.2, seed: 271 },
      { t: "EDA 授权与合规审查",       brd: 11, cons: 51, base: 9,  mul: 0.44,seed: 277 },
      { t: "功率半导体产能过剩",       brd: 10, cons: 36, base: 11, mul: 0.29,seed: 281 },
    ]),
    sensors: [
      { k: "台积电月营收 YoY", v: "+31.2%", d: "+2.4pt", dir: "up",
        s: [19.4,20.8,22.1,21.6,23.9,25.2,24.8,26.4,27.1,26.9,28.3,29.0,28.8,30.1,31.2] },
      { k: "DRAM DDR5 现货", v: "$4.86", d: "+7.9%", dir: "up",
        s: [3.10,3.18,3.26,3.22,3.41,3.55,3.62,3.78,3.90,3.99,4.18,4.31,4.44,4.62,4.86] },
      { k: "NAND 512Gb 现货", v: "$3.22", d: "+4.1%", dir: "up",
        s: [2.44,2.48,2.51,2.56,2.61,2.63,2.70,2.76,2.81,2.85,2.94,3.01,3.08,3.14,3.22] },
      { k: "设备 B/B 比", v: "1.18", d: "+0.04", dir: "up",
        s: [0.96,0.98,0.97,1.01,1.03,1.02,1.06,1.08,1.07,1.10,1.12,1.11,1.14,1.16,1.18] },
      { k: "硅片出货 MSI", v: "3,684", d: "−1.2%", dir: "down",
        s: [3810,3796,3802,3771,3760,3748,3752,3731,3722,3714,3703,3698,3701,3690,3684] },
      { k: "先进封装稼动率", v: "97.1%", d: "+0.0pt", dir: "flat",
        s: [88.2,89.4,90.1,91.6,92.4,93.0,94.1,94.8,95.3,96.0,96.4,96.9,97.1,97.1,97.1] },
    ],
    sources: ["RTR","BBG","NIK","DIG","TRD","OFF","SUP"],
    sourceNames: { RTR:"路透", BBG:"彭博", NIK:"日经", DIG:"DigiTimes",
      TRD:"TrendForce", OFF:"法说会 / 备案", SUP:"供应链访谈" },
    claims: [
      { c:"存储涨价将延续至明年二季度", n:"各机构拐点预测相差两个季度", v:[1,-1,2,2,2,0,-2] },
      { c:"HBM 明年产能已被长约锁定超过八成", n:"锁定比例报道 62%–90%", v:[2,1,0,2,-1,-2,1] },
      { c:"设备出口新规将影响成熟制程扩产", n:"许可细则未公布，均为转述", v:[1,0,1,2,-1,-2,0] },
      { c:"先进封装是当前最紧的单一环节", n:"与硅片、测试环节口径冲突", v:[2,2,1,2,1,0,1] },
      { c:"成熟制程价格已触底", n:"分区域差异大，全球口径不成立", v:[0,-1,1,-1,1,0,-2] },
      { c:"High-NA 将在明年进入量产导入", n:"设备商与晶圆厂说法不一致", v:[1,1,2,0,0,-1,-2] },
      { c:"汽车芯片库存去化基本完成", n:"依赖 Tier-1 口径，缺交叉验证", v:[0,1,0,-1,1,2,-1] },
    ],
    questions: [
      { q:"HBM 长约锁定比例从 62% 到 90%，差异是口径还是时点？", s:"HBM 供给与分配",
        w:"等待三家存储厂法说会的口径对齐", age:14 },
      { q:"先进封装稼动率 97% 之上，新增产能实际何时贡献出货？", s:"先进封装产能扩张",
        w:"等待设备到机与验证周期的公开时间表", age:21 },
      { q:"设备出口新规是否覆盖成熟制程扩产？现有报道全为转述。", s:"设备出口许可变动",
        w:"等待许可细则原文公布", age:9 },
      { q:"存储涨价拐点预测相差两个季度，谁的库存假设更接近实际？", s:"存储涨价周期",
        w:"等待渠道库存周数的第三方统计", age:17 },
      { q:"成熟制程「触底」是全球现象还是仅限特定区域？", s:"成熟制程价格战",
        w:"可自行处理：按区域拆分现有报价数据重算", age:26 },
      { q:"High-NA 量产导入时点，设备商与晶圆厂为何口径不一？", s:"High-NA EUV 导入进度",
        w:"等待任一方给出具体产品与节点", age:33 },
    ],
    chain: [
      { tier:"设计 / IP", stress:38, players:[
        {n:"NVIDIA",h:3},{n:"AMD",h:2},{n:"Apple",h:1},{n:"Qualcomm",h:1},{n:"Arm",h:2},{n:"Broadcom",h:2}] },
      { tier:"制造 / 晶圆", stress:64, players:[
        {n:"TSMC",h:3},{n:"Samsung Foundry",h:2},{n:"Intel Foundry",h:2},{n:"GlobalFoundries",h:1},{n:"SMIC",h:2}] },
      { tier:"存储", stress:88, players:[
        {n:"SK Hynix",h:3},{n:"Samsung",h:3},{n:"Micron",h:3},{n:"Kioxia",h:1}] },
      { tier:"封装 / 测试", stress:93, players:[
        {n:"TSMC CoWoS",h:3},{n:"ASE",h:3},{n:"Amkor",h:2},{n:"JCET",h:1},{n:"PTI",h:2}] },
      { tier:"设备", stress:57, players:[
        {n:"ASML",h:3},{n:"Applied Materials",h:2},{n:"Lam Research",h:2},{n:"Tokyo Electron",h:2},{n:"KLA",h:1}] },
      { tier:"材料 / 硅片", stress:31, players:[
        {n:"信越化学",h:1},{n:"SUMCO",h:2},{n:"JSR",h:1},{n:"环球晶圆",h:1}] },
    ],
    geo: {
      regions: [
        { n:"中国台湾", c:"var(--gr-1)" }, { n:"韩国", c:"var(--gr-2)" },
        { n:"美国", c:"var(--gr-3)" }, { n:"其他", c:"var(--neutral)" },
      ],
      rows: [
        { n:"≤ 3nm 逻辑",   v:[86, 14, 0, 0] },
        { n:"3–7nm 逻辑",   v:[71, 17, 6, 6] },
        { n:"7–16nm 逻辑",  v:[54, 15, 12, 19] },
        { n:"成熟制程",     v:[24, 8, 11, 57] },
        { n:"HBM",          v:[9, 82, 9, 0] },
        { n:"先进封装",     v:[63, 12, 8, 17] },
      ],
    },
  },
  panels: `    <section class="panel c4">
      <header><h2>供应链环节紧张度</h2><span class="note">故事密度加权</span></header>
      <div class="body"><div id="chain"></div>
        <div class="lgrow">
          <span><i style="background:var(--s6)"></i>该环节故事密度 高</span>
          <span><i style="background:var(--s2)"></i>低</span>
          <span style="color:var(--ink-3)">条 = 紧张度指数 0–100</span>
        </div></div>
    </section>

    <section class="panel c4">
      <header><h2>产能地理集中度</h2><span class="note">按制程分</span></header>
      <div class="body"><div id="geo"></div></div>
    </section>

    <section class="panel c4">
      <header><h2>分歧矩阵</h2><span class="note">按分歧度排序</span></header>
      <div class="body"><div class="dm" id="dm"></div></div>
    </section>

    <section class="panel c12">
      <header><h2>未解问题</h2><span class="note">31 项 · 显示 6</span></header>
      <div class="body"><div class="oq wide"><ul id="oq"></ul></div></div>
    </section>`,
  extraJS: `
function renderChain() {
  $("#chain").innerHTML = DATA.chain.map(t => {
    const col = t.stress >= 85 ? "var(--st-critical)" : t.stress >= 60 ? "var(--st-warning)" : "var(--accent)";
    return '<div class="tier"><div class="th"><b>'+esc(t.tier)+'</b>' +
      '<span>紧张度 '+t.stress+'</span></div>' +
      '<span class="meter" tabindex="0" data-tip="'+esc(t.tier)+'|紧张度指数 '+t.stress+' / 100|' +
        (t.stress>=85?"瓶颈环节":t.stress>=60?"偏紧":"宽松")+'" style="display:block;margin-bottom:6px">' +
      '<i style="width:'+t.stress+'%;background:'+col+'"></i></span>' +
      '<div class="chips">' + t.players.map(p =>
        '<u data-hot="'+p.h+'" tabindex="0" data-tip="'+esc(p.n)+'|'+esc(t.tier)+
        '|近 30 天故事密度 '+["低","低","中","高"][p.h]+'">'+esc(p.n)+'</u>').join("") +
      '</div></div>';
  }).join("");
}

function renderGeo() {
  const R = DATA.geo.regions;
  $("#geo").innerHTML = DATA.geo.rows.map(r => {
    const top = R[r.v.indexOf(Math.max(...r.v))].n;
    return '<div style="margin-bottom:9px"><div class="rowlab"><span>'+esc(r.n)+
      '</span><span>'+top+' '+Math.max(...r.v)+'%</span></div><div class="stack">' +
      r.v.map((v, i) => v <= 0 ? "" :
        '<i tabindex="0" style="width:'+v+'%;background:'+R[i].c+'" data-tip="'+esc(r.n)+'|'+
        esc(R[i].n)+' '+v+'%"></i>').join("") + '</div></div>';
  }).join("") +
  '<div class="lgrow">' + R.map(x =>
    '<span><i style="background:'+x.c+'"></i>'+esc(x.n)+'</span>').join("") +
  '<span style="color:var(--ink-3)">最大占比已直接标注</span></div>';
}`,
  extraBoot: "renderChain(); renderGeo();",
  footnote: "　产能地理集中度为堆叠条形，四段颜色仅相邻两两需可分辨，最大占比一段另附文字直标。",
};

/* ═════════════════ 3 · 宏观市场 ═════════════════ */

const MACRO = {
  id: "macro-markets", name: "宏观市场",
  dark:  { accent: "#c98500", ramp: ["#3d2c05","#553d07","#6f5009","#8a640b","#a5780d","#c98500"] },
  light: { accent: "#8a6000", ramp: ["#f6e6c4","#ecd097","#dcb463","#c4952f","#a67a10","#8a6000"] },
  status: [
    { k: "采集", v: "4,116", u: " 篇 / 24h" }, { k: "信源", v: "207", u: " 个" },
    { k: "含官方发布", v: "48", u: " 篇" }, { k: "活跃故事", v: "31" },
    { k: "叙事—价格背离", v: "5", u: " 项" }, { k: "去重率", v: "71.6%" },
    { k: "上次同步", v: "12:00", u: " UTC", live: true },
  ],
  data: {
    asOf: "2026-07-27T12:00:00Z",
    stories: stories([
      { t: "联储降息路径分歧",         brd: 34, cons: 26, base: 9,  mul: 6.8, seed: 311 },
      { t: "私募信贷估值透明度",       brd: 21, cons: 22, base: 5,  mul: 6.1, seed: 313 },
      { t: "服务业通胀粘性",           brd: 29, cons: 44, base: 8,  mul: 3.9, seed: 317 },
      { t: "日银政策正常化节奏",       brd: 24, cons: 51, base: 6,  mul: 3.6, seed: 331 },
      { t: "关税成本传导",             brd: 27, cons: 35, base: 9,  mul: 2.6, seed: 337 },
      { t: "就业市场降温信号",         brd: 26, cons: 58, base: 10, mul: 2.0, seed: 347 },
      { t: "商业地产再融资墙",         brd: 18, cons: 47, base: 7,  mul: 1.8, seed: 349 },
      { t: "欧洲财政规则重议",         brd: 16, cons: 63, base: 5,  mul: 1.6, seed: 353 },
      { t: "高收益信用利差走阔",       brd: 20, cons: 54, base: 8,  mul: 1.3, seed: 359 },
      { t: "原油供给侧扰动",           brd: 22, cons: 61, base: 11, mul: 0.86,seed: 367 },
      { t: "美元融资条件",             brd: 14, cons: 69, base: 9,  mul: 0.47,seed: 373 },
      { t: "新兴市场资金流向",         brd: 12, cons: 40, base: 10, mul: 0.31,seed: 379 },
    ]),
    sensors: [
      { k: "2s10s 利差", v: "+62bp", d: "+9bp", dir: "up",
        s: [12,18,15,24,29,26,34,38,35,42,47,44,53,58,62] },
      { k: "美元指数 DXY", v: "101.4", d: "−1.8%", dir: "down",
        s: [106.2,105.8,106.1,105.2,104.9,105.3,104.4,104.0,103.6,103.9,103.1,102.6,102.2,101.8,101.4] },
      { k: "WTI 原油", v: "$68.30", d: "−4.2%", dir: "down",
        s: [78.4,77.1,76.8,75.2,74.6,75.1,73.4,72.8,72.1,71.4,70.8,70.2,69.6,68.9,68.3] },
      { k: "10Y 实际利率", v: "1.84%", d: "−12bp", dir: "down",
        s: [2.31,2.28,2.24,2.26,2.19,2.14,2.16,2.09,2.04,2.01,1.97,1.94,1.90,1.87,1.84] },
      { k: "高收益利差 OAS", v: "418bp", d: "+34bp", dir: "up",
        s: [302,309,304,318,324,319,336,344,351,347,364,378,391,404,418] },
      { k: "黄金", v: "$3,412", d: "+2.7%", dir: "up",
        s: [3040,3078,3061,3124,3159,3141,3198,3236,3221,3274,3301,3288,3346,3381,3412] },
    ],
    sources: ["RTR","BBG","FT","WSJ","ECO","OFF","SEL"],
    sourceNames: { RTR:"路透", BBG:"彭博", FT:"金融时报", WSJ:"华尔街日报",
      ECO:"经济学人", OFF:"央行 / 统计局发布", SEL:"卖方研究" },
    claims: [
      { c:"年内还有两次以上降息", n:"点阵图与市场定价背离", v:[1,2,-1,1,-2,-2,2] },
      { c:"服务业通胀已实质性回落", n:"取决于住房项处理方式", v:[0,-1,1,-1,2,1,-2] },
      { c:"私募信贷存在系统性估值虚高", n:"无统一披露口径，全为推断", v:[1,2,2,1,1,-2,-1] },
      { c:"关税成本主要由进口商吸收", n:"学术与业界估算差异大", v:[1,0,2,-1,1,0,-2] },
      { c:"就业市场降温尚未触及衰退阈值", n:"依赖修订前后的口径", v:[2,1,1,0,1,2,0] },
      { c:"商业地产再融资风险已被定价", n:"分物业类型差异极大", v:[-1,0,-1,1,0,0,2] },
      { c:"日银将在本财年内再次加息", n:"官方措辞与市场解读不一", v:[1,1,0,2,0,-1,1] },
    ],
    questions: [
      { q:"点阵图与市场定价的降息次数差了两次，哪一侧在调整？", s:"联储降息路径分歧",
        w:"等待下一次会议纪要与官员讲话", age:11 },
      { q:"私募信贷估值缺乏统一披露口径，能否用可比公开债反推？", s:"私募信贷估值透明度",
        w:"可自行处理：用同评级公开债利差构造代理指标", age:24 },
      { q:"服务业通胀的结论对住房项处理方式有多敏感？", s:"服务业通胀粘性",
        w:"可自行处理：剔除住房项重算三种口径", age:18 },
      { q:"关税成本的实际承担比例，学术与业界估算为何差三倍？", s:"关税成本传导",
        w:"等待海关单价与零售价的配对数据", age:29 },
      { q:"叙事热度在降，但高收益利差在走阔 —— 谁先反应？", s:"高收益信用利差走阔",
        w:"持续观察：已列入背离监控", age:7 },
      { q:"日银官方措辞与市场解读的差异，是翻译问题还是实质分歧？", s:"日银政策正常化节奏",
        w:"等待日文原文与英译本的逐句比对", age:15 },
    ],
    /* 叙事热度（0–100，报道量与情绪加权）对比同期价格变动（%）。
       两者符号或幅度不一致即为背离 —— 这是本频道最该被一眼看到的东西。 */
    divergence: [
      { n:"高收益信用",   narr: 34, price: 12.4, note:"利差走阔但报道量在降" },
      { n:"私募信贷",     narr: 88, price:  1.2, note:"叙事沸腾，可观测价格几乎未动" },
      { n:"黄金",         narr: 41, price: 12.2, note:"价格创高但叙事平淡" },
      { n:"美元",         narr: 62, price: -4.5, note:"方向一致，幅度相称" },
      { n:"原油",         narr: 71, price:-12.9, note:"方向一致，幅度相称" },
      { n:"美债长端",     narr: 79, price:  6.8, note:"方向一致，叙事略超前" },
      { n:"商业地产",     narr: 46, price: -8.1, note:"价格下行快于叙事" },
      { n:"新兴市场股",   narr: 22, price:  9.4, note:"几乎无人报道，价格已动" },
    ],
  },
  panels: `    <section class="panel c5">
      <header><h2>叙事 — 价格背离</h2><span class="note">近 30 天 · 按背离度排序</span></header>
      <div class="body"><div id="dv"></div>
        <div class="lgrow">
          <span><i style="background:var(--accent)"></i>叙事热度 0–100</span>
          <span><i style="background:var(--div-p2)"></i>价格上行</span>
          <span><i style="background:var(--div-n2)"></i>价格下行</span>
          <span style="color:var(--ink-3)">背离度 = 两者幅度标准化后之差（不比方向）</span>
        </div></div>
    </section>

    <section class="panel c4">
      <header><h2>分歧矩阵</h2><span class="note">按分歧度排序</span></header>
      <div class="body"><div class="dm" id="dm"></div></div>
    </section>

    <section class="panel c3">
      <header><h2>未解问题</h2><span class="note">33 项 · 显示 6</span></header>
      <div class="body"><div class="oq"><ul id="oq"></ul></div></div>
    </section>`,
  extraJS: `
/* 两条量纲不同的序列绝不共用一根坐标轴（双轴图会凭空造出相关性），
   而是各占一栏、各自有量程。
   背离度比的是**幅度**不是方向：叙事热度是无符号强度，价格变动是有符号收益率，
   直接相减等于把两个不可比的量强行对齐。两者各自标准化到 0–1 后取绝对值之差 ——
   「叙事沸腾但价格没动」与「价格已动但没人报道」都算背离，方向由色条单独承载。 */
function renderDivergence() {
  const P = Math.max(...DATA.divergence.map(r => Math.abs(r.price)));
  const rows = DATA.divergence.map(r => ({ ...r,
    score: Math.round(Math.abs(r.narr / 100 - Math.abs(r.price) / P) * 100) }))
    .sort((a, b) => b.score - a.score);

  $("#dv").innerHTML = '<div class="dv-h"><span>标的</span><span>叙事热度</span>' +
    '<span>价格变动 30d</span><span>背离度</span></div>' +
    rows.map(r => {
      const half = Math.abs(r.price) / P * 50;
      const col = r.price >= 0 ? "var(--div-p2)" : "var(--div-n2)";
      return '<div class="dv-r"><div class="nm" title="'+esc(r.note)+'">'+esc(r.n)+'</div>' +
        '<span class="bar" tabindex="0" data-tip="'+esc(r.n)+'|叙事热度 '+r.narr+' / 100">' +
          '<i style="left:0;width:'+r.narr+'%;background:var(--accent)"></i></span>' +
        '<span class="bar ctr" tabindex="0" data-tip="'+esc(r.n)+'|价格变动 '+
          (r.price>0?"+":"")+r.price+'%|'+esc(r.note)+'">' +
          '<i style="'+(r.price>=0 ? "left:50%" : "left:"+(50-half)+"%")+';width:'+half+'%;background:'+col+'"></i></span>' +
        '<span class="sc" style="color:'+(r.score>=35?"var(--st-critical)":r.score>=22?"var(--st-warning)":"var(--ink-2)")+
          '">'+r.score+'</span></div>';
    }).join("");
}`,
  extraBoot: "renderDivergence();",
  footnote: "　叙事—价格背离面板中两条量纲不同的序列各占一栏、各有量程，不共用坐标轴；背离度比较的是幅度而非方向。",
};

/* ═════════════════ 4 · 地缘政治 ═════════════════ */

const GEO = {
  id: "geopolitics", name: "地缘政治",
  dark:  { accent: "#d95926", ramp: ["#40190d","#5a2412","#753017","#913d1c","#b04920","#d95926"] },
  light: { accent: "#c44f18", ramp: ["#fadfd0","#f4c0a4","#ec9d75","#e07d4d","#d2652d","#c44f18"] },
  status: [
    { k: "采集", v: "3,502", u: " 篇 / 24h" }, { k: "信源", v: "231", u: " 个" },
    { k: "语种", v: "14" }, { k: "活跃故事", v: "37" },
    { k: "官方表态待核", v: "16" }, { k: "去重率", v: "68.9%" },
    { k: "上次同步", v: "11:52", u: " UTC", live: true },
  ],
  data: {
    asOf: "2026-07-27T12:00:00Z",
    stories: stories([
      { t: "红海航运安全与保险费率",   brd: 33, cons: 37, base: 7,  mul: 7.2, seed: 401 },
      { t: "关键矿产出口配额",         brd: 26, cons: 24, base: 6,  mul: 6.4, seed: 409 },
      { t: "海底电缆与通信基础设施",   brd: 19, cons: 45, base: 4,  mul: 5.2, seed: 419 },
      { t: "多边贸易机制改革谈判",     brd: 28, cons: 52, base: 8,  mul: 3.1, seed: 421 },
      { t: "制裁机制的二级效应",       brd: 24, cons: 31, base: 9,  mul: 2.7, seed: 431 },
      { t: "粮食出口协议续期",         brd: 21, cons: 58, base: 7,  mul: 2.2, seed: 433 },
      { t: "北极航道通航季延长",       brd: 13, cons: 71, base: 3,  mul: 2.4, seed: 439 },
      { t: "军费开支占比上修",         brd: 25, cons: 64, base: 8,  mul: 1.5, seed: 443 },
      { t: "能源走廊过境费重议",       brd: 17, cons: 42, base: 6,  mul: 1.4, seed: 449 },
      { t: "边境管控与人员流动",       brd: 20, cons: 49, base: 9,  mul: 1.1, seed: 457 },
      { t: "国际组织席位与投票权",     brd: 14, cons: 66, base: 8,  mul: 0.51,seed: 461 },
      { t: "跨境数据流动规则",         brd: 11, cons: 39, base: 10, mul: 0.33,seed: 463 },
    ]),
    sensors: [
      { k: "布伦特原油", v: "$71.90", d: "−3.6%", dir: "down",
        s: [82.1,81.4,80.8,79.6,78.9,79.4,77.8,77.1,76.4,75.8,74.9,74.1,73.4,72.6,71.9] },
      { k: "波罗的海干散货", v: "1,842", d: "+11.3%", dir: "up",
        s: [1290,1318,1301,1376,1412,1394,1468,1521,1497,1583,1642,1618,1704,1771,1842] },
      { k: "苏伊士日通行量", v: "31", u:" 艘", d: "−52%", dir: "down",
        s: [68,66,64,61,58,59,54,51,48,46,42,39,36,33,31] },
      { k: "TTF 天然气", v: "€38.4", d: "+6.8%", dir: "up",
        s: [28.1,28.9,28.4,30.1,31.2,30.7,32.4,33.1,32.8,34.2,35.1,34.8,36.3,37.4,38.4] },
      { k: "小麦期货", v: "$614", d: "+4.9%", dir: "up",
        s: [521,528,524,539,547,543,558,566,571,578,589,584,598,606,614] },
      { k: "战争险附加费率", v: "0.72%", d: "+0.18pt", dir: "up",
        s: [0.21,0.23,0.22,0.26,0.29,0.28,0.33,0.37,0.41,0.44,0.49,0.54,0.61,0.67,0.72] },
    ],
    sources: ["RTR","AFP","ALJ","NIK","ECO","OFF","LOC"],
    sourceNames: { RTR:"路透", AFP:"法新社", ALJ:"半岛电视台", NIK:"日经",
      ECO:"经济学人", OFF:"官方声明 / 公报", LOC:"当地语种媒体" },
    claims: [
      { c:"红海绕行已成为多数承运人的常态安排", n:"绕行比例报道 41%–88%", v:[2,1,2,1,0,-2,2] },
      { c:"关键矿产配额收紧将持续到年底", n:"配额文本未公布，均为转述", v:[1,0,2,2,-1,-2,1] },
      { c:"海底电缆事故率高于历史均值", n:"统计口径与时间窗差异大", v:[1,2,0,1,-1,0,-2] },
      { c:"制裁的二级效应已显著影响第三国贸易", n:"缺乏统一的贸易转移测算", v:[2,1,1,0,2,-2,1] },
      { c:"粮食出口协议将如期续期", n:"各方公开表态相互矛盾", v:[0,1,-1,0,1,2,-2] },
      { c:"多边谈判在核心议题上已接近文本", n:"仅有匿名消息源，无官方确认", v:[1,2,0,1,0,-2,0] },
      { c:"北极航道商业通航尚不具备经济性", n:"取决于保险与破冰成本假设", v:[-1,0,-1,2,1,0,1] },
    ],
    questions: [
      { q:"红海绕行比例报道从 41% 到 88%，分母是航次还是运力？", s:"红海航运安全与保险费率",
        w:"可自行处理：用 AIS 航迹数据按运力重算", age:13 },
      { q:"关键矿产配额的具体品类与额度，是否有官方文本？", s:"关键矿产出口配额",
        w:"等待配额清单在官方公报刊出", age:10 },
      { q:"海底电缆事故率「高于历史均值」，用的是哪个时间窗？", s:"海底电缆与通信基础设施",
        w:"可自行处理：取 ICPC 公开事故库统一时间窗重算", age:22 },
      { q:"制裁二级效应的贸易转移量，能否从镜像贸易数据估计？", s:"制裁机制的二级效应",
        w:"可自行处理：用双边贸易统计的镜像差额构造估计", age:28 },
      { q:"粮食协议各方表态相互矛盾，哪些是正式立场哪些是谈判姿态？", s:"粮食出口协议续期",
        w:"等待正式公报或谈判方联合声明", age:16 },
      { q:"多边谈判「接近文本」只有匿名源，能否交叉验证？", s:"多边贸易机制改革谈判",
        w:"等待第二个独立信源或官方确认", age:6 },
    ],
    /* 不画世界地图 —— 手绘海岸线数据无法保证准确，而一张插满新闻圆点的地图
       信息量约等于零。改用走廊 / 咽喉点态势表：位置信息由命名承载，
       屏幕面积留给真正在变化的量。生产版本应接入真实地理图层。 */
    corridors: [
      { n:"曼德海峡 / 红海", k:"航运", lvl:5, vol:96, note:"战争险附加费率 0.72%，通行量 −52%" },
      { n:"霍尔木兹海峡",   k:"能源", lvl:3, vol:61, note:"通行正常，保险费率小幅上行" },
      { n:"马六甲海峡",     k:"航运", lvl:2, vol:48, note:"绕行分流带来的排队时长上升" },
      { n:"苏伊士运河",     k:"航运", lvl:5, vol:91, note:"日通行 31 艘，为近年低位" },
      { n:"巴拿马运河",     k:"航运", lvl:2, vol:37, note:"水位恢复，配额已回到常态" },
      { n:"黑海粮运走廊",   k:"粮食", lvl:4, vol:73, note:"协议续期窗口临近，表态矛盾" },
      { n:"关键矿产出口链", k:"矿产", lvl:4, vol:82, note:"配额收紧，文本未公布" },
      { n:"跨境海底电缆",   k:"通信", lvl:3, vol:56, note:"事故率统计口径存疑" },
      { n:"北极东北航道",   k:"航运", lvl:1, vol:22, note:"通航季延长，商业性存疑" },
    ],
    /* 升级阶梯：每一级是可观测的行为类型，不是对意图的猜测。
       走廊按当前观测到的最高级别归档。 */
    ladder: [
      { n:5, t:"物理中断",   d:"航道、管线或链路出现实际中断",     items:["曼德海峡 / 红海","苏伊士运河"] },
      { n:4, t:"经济强制",   d:"配额、禁运、二级制裁等已生效措施", items:["关键矿产出口链","黑海粮运走廊"] },
      { n:3, t:"措施预告",   d:"已公开威胁但尚未落地的措施",       items:["霍尔木兹海峡","跨境海底电缆"] },
      { n:2, t:"外交摩擦",   d:"召见、抗议、谈判中止等外交动作",   items:["马六甲海峡","巴拿马运河"] },
      { n:1, t:"表态分歧",   d:"仅停留在公开表态层面的立场差异",   items:["北极东北航道"] },
    ],
  },
  panels: `    <section class="panel c5">
      <header><h2>走廊 / 咽喉点态势</h2><span class="note">9 处 · 按级别排序</span></header>
      <div class="body"><div id="cor" class="cor"></div>
        <div class="lgrow">
          <span><i style="background:var(--s6)"></i>级别 5</span>
          <span><i style="background:var(--s2)"></i>级别 1</span>
          <span style="color:var(--ink-3)">条 = 近 30 天报道体量</span>
        </div></div>
    </section>

    <section class="panel c3">
      <header><h2>升级阶梯</h2><span class="note">按可观测行为归档</span></header>
      <div class="body"><div id="lad"></div></div>
    </section>

    <section class="panel c4">
      <header><h2>分歧矩阵</h2><span class="note">按分歧度排序</span></header>
      <div class="body"><div class="dm" id="dm"></div></div>
    </section>

    <section class="panel c12">
      <header><h2>未解问题</h2><span class="note">41 项 · 显示 6</span></header>
      <div class="body"><div class="oq wide"><ul id="oq"></ul></div></div>
    </section>`,
  extraJS: `
function renderCorridors() {
  $("#cor").innerHTML = [...DATA.corridors].sort((a, b) => b.lvl - a.lvl || b.vol - a.vol)
    .map(c => '<div class="tier"><div class="th">' +
      '<span class="stage" data-s="'+Math.min(4, c.lvl - 1)+'">L'+c.lvl+'</span>' +
      '<b>'+esc(c.n)+'</b><span>'+esc(c.k)+' · 体量 '+c.vol+'</span></div>' +
      '<div class="note">'+esc(c.note)+'</div>' +
      '<span class="meter" tabindex="0" style="display:block" data-tip="'+esc(c.n)+'|级别 L'+c.lvl+
        ' · '+esc(c.k)+'|近 30 天报道体量 '+c.vol+' / 100|'+esc(c.note)+'">' +
      '<i style="width:'+c.vol+'%;background:var(--s'+Math.max(1, c.lvl)+')"></i></span></div>').join("");
}

function renderLadder() {
  $("#lad").innerHTML = DATA.ladder.map(r =>
    '<div class="rung"><div class="n">L'+r.n+'</div><div>' +
    '<div class="t"><b>'+esc(r.t)+'</b><em>'+esc(r.d)+'</em></div>' +
    '<div class="chips">' + r.items.map(i =>
      '<u data-hot="'+Math.min(3, Math.max(1, r.n - 2))+'">'+esc(i)+'</u>').join("") +
    '</div></div></div>').join("");
}`,
  extraBoot: "renderCorridors(); renderLadder();",
  footnote: "　本频道刻意不画世界地图：手绘海岸线无法保证地理准确，而一张插满新闻圆点的地图信息量接近于零。位置信息由走廊 / 咽喉点的命名承载，屏幕面积留给真正在变化的量；生产版本应接入真实地理图层。",
};

export const CHANNEL_CONFIGS = [AI, SEMI, MACRO, GEO];
