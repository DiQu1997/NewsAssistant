// 图元实验台（#/vizlab，不挂导航）。样例数据全部手写，不连接口 ——
// 用来在没有真实 views 的时候校对每种图型的排版、密度与标注层。
// 改 charts.jsx 后应该先在这里过一遍。
import { EventViews, FactStrip } from "../charts.jsx";

const FACTS = [
  {
    key: "death_toll", label: "死亡人数", kind: "disputed", unit: "人",
    gap_label: "高于官方通报的部分", as_of: "2026-08-09",
    scope_excludes: "未计入失踪人员与灾后疫病死亡",
    estimates: [
      { value: 143, source: "菲律宾国家减灾委", method: "官方登记" },
      { value: 271, source: "红十字会", method: "各省报数汇总" },
    ],
    claim_ids: [1],
  },
  { key: "displaced", label: "紧急撤离", kind: "single", value: 412000,
    unit: "人", as_of: "2026-08-08", claim_ids: [1] },
  { key: "wind_peak", label: "中心最大风力", kind: "single", value: 17,
    unit: "级", claim_ids: [1] },
  { key: "econ_loss", label: "直接经济损失", kind: "unknown", claim_ids: [1] },
];

const VIEWS = [
  {
    type: "numbers", intent: "量级", unit: "人",
    title: "官方通报与红会统计相差近一倍，差额本身尚无解释",
    note: "两个口径并列，未做平均；差额单列",
    fact_keys: ["death_toll", "displaced", "wind_peak", "econ_loss"],
    annotations: [{ at: "口径", text: "官方只计已确认遗体，红会含各省上报的失联推定" }],
    claim_ids: [1],
  },
  {
    type: "revision", intent: "随时间变化", unit: "人",
    title: "死亡数字四天里被上修了三次，累计翻了近五倍",
    note: "每次发布均为官方通报口径",
    points: [
      { x: "8月5日 14:00", y: 31, source: "国家减灾委" },
      { x: "8月6日 09:00", y: 67, source: "国家减灾委" },
      { x: "8月7日 18:00", y: 118, source: "国家减灾委" },
      { x: "8月9日 08:00", y: 143, source: "国家减灾委" },
    ],
    annotations: [{ at: "8月6日", text: "宿务省道路抢通后首次报出内陆伤亡" }],
    claim_ids: [1],
  },
  {
    type: "bars_rolling", intent: "随时间变化", unit: "人次",
    title: "撤离在登陆前一天冲到峰值，登陆后转为救援",
    note: "各省民防办每日通报，含重复登记",
    points: [
      { x: "8月1日", y: 3200 }, { x: "8月2日", y: 8100 },
      { x: "8月3日", y: 15400 }, { x: "8月4日", y: 42300 },
      { x: "8月5日", y: 96500 }, { x: "8月6日", y: 71200 },
      { x: "8月7日", y: 38400 }, { x: "8月8日", y: 19800 },
      { x: "8月9日", y: 11200 },
    ],
    claim_ids: [1],
  },
  {
    type: "line_baseline", intent: "偏离", unit: "毫米",
    title: "单日降雨量是往年同期均值的六倍",
    baseline: 42, baseline_label: "近五年八月同期均值",
    note: "马尼拉观测站；基准取 2021-2025 同期",
    points: [
      { x: "8月3日", y: 51 }, { x: "8月4日", y: 88 }, { x: "8月5日", y: 264 },
      { x: "8月6日", y: 197 }, { x: "8月7日", y: 96 }, { x: "8月8日", y: 47 },
    ],
    annotations: [{ at: "8月5日", text: "登陆当日，超过基准 6.3 倍" }],
    claim_ids: [1],
  },
  {
    type: "waffle", intent: "部分与整体", unit: "人",
    title: "已确认遇难者中三分之二来自两个内陆省份",
    note: "1 个人形代表 1 人；总数取官方口径 143",
    unit_icon: "person", unit_each: 1,
    items: [
      { label: "宿务省", value: 61 }, { label: "内格罗斯省", value: 34 },
      { label: "其他省份", value: 48 },
    ],
    claim_ids: [1],
  },
  {
    type: "swimlane", intent: "随时间变化",
    title: "气象台升级预警到地方下达强制撤离，中间隔了 19 小时",
    note: "各方公开通报时间；瞬时事件画点，持续状态画条",
    lanes: [
      { actor: "气象台", events: [
        { start: "8月3日", label: "升为超强台风" },
        { start: "8月4日", end: "8月6日", label: "红色预警持续" }] },
      { actor: "国家减灾委", events: [
        { start: "8月4日", label: "启动二级响应" },
        { start: "8月5日", label: "升为一级响应" }] },
      { actor: "地方政府", events: [
        { start: "8月5日", end: "8月7日", label: "强制撤离令" }] },
      { actor: "军方", events: [
        { start: "8月6日", end: "8月9日", label: "投入搜救" }] },
    ],
    annotations: [{ at: "8月4-5日", text: "预警与撤离令之间的空隙是问责焦点" }],
    claim_ids: [1],
  },
  {
    type: "stepper", intent: "随时间变化",
    title: "救灾进入第三阶段，重建资金尚未拨付",
    steps: [
      { label: "预警与撤离", status: "done", at: "8月3-5日" },
      { label: "搜救与医疗", status: "done", at: "8月5-8日" },
      { label: "安置与供水恢复", status: "current", at: "8月8日起" },
      { label: "重建资金拨付", status: "pending" },
    ],
    claim_ids: [1],
  },
  {
    type: "slope", intent: "排名", unit: "%",
    title: "加税后，四类商品里只有钢铁的税率没有回落",
    x_labels: ["加税前", "本轮调整后"],
    note: "以最惠国税率为基准",
    items: [
      { label: "钢铁", value: 7.5, value2: 25 },
      { label: "铝材", value: 10, value2: 15 },
      { label: "光伏组件", value: 12, value2: 8 },
      { label: "锂电池", value: 7.5, value2: 6 },
    ],
    annotations: [{ at: "钢铁", text: "唯一上行的一类，且幅度最大" }],
    claim_ids: [1],
  },
  {
    type: "matrix", intent: "量级", unit: "%",
    title: "报复性关税集中在三组双边关系上",
    note: "行=征收方，列=被征收方；负值为下调",
    matrix: {
      rows: ["美国", "欧盟", "中国"],
      cols: ["美国", "欧盟", "中国"],
      cells: [
        { r: "美国", c: "欧盟", v: 10 }, { r: "美国", c: "中国", v: 34 },
        { r: "欧盟", c: "美国", v: 8 }, { r: "欧盟", c: "中国", v: 21 },
        { r: "中国", c: "美国", v: 34 }, { r: "中国", c: "欧盟", v: -3 },
      ],
    },
    claim_ids: [1],
  },
  {
    type: "dumbbell", intent: "排名", unit: "亿美元",
    title: "承诺援助与实际到位之间，最大的一笔差了 12 亿",
    x_labels: ["已承诺", "已到位"],
    items: [
      { label: "世界银行", value: 18, value2: 6 },
      { label: "亚开行", value: 12, value2: 9 },
      { label: "日本", value: 7, value2: 6.5 },
      { label: "欧盟", value: 5, value2: 1.2 },
    ],
    claim_ids: [1],
  },
  {
    type: "bars", intent: "排名", unit: "%",
    title: "农业与旅游业受冲击最重，制造业基本未受影响",
    items: [
      { label: "农业", value: -31 }, { label: "旅游业", value: -24 },
      { label: "渔业", value: -18 }, { label: "零售", value: -6 },
      { label: "制造业", value: -1 }, { label: "建材", value: 14 },
    ],
    annotations: [{ at: "建材", text: "唯一上行行业，重建预期带动" }],
    claim_ids: [1],
  },
  {
    type: "stacked", intent: "部分与整体", unit: "亿比索",
    title: "重建预算的一半将投向道路与桥梁",
    items: [
      { label: "道路桥梁", value: 240, group: "基建" },
      { label: "供电供水", value: 120, group: "基建" },
      { label: "住房", value: 95, group: "民生" },
      { label: "农业复产", value: 60, group: "民生" },
      { label: "其他", value: 35, group: "其他" },
    ],
    claim_ids: [1],
  },
  {
    type: "beeswarm", intent: "分布", unit: "%",
    title: "多数省份受灾率在 5% 以下，两个省是明显离群",
    note: "受灾人口占全省人口比例",
    items: [
      ...Array.from({ length: 22 }, (_, i) => ({
        label: `省份${i + 1}`, value: +(Math.abs(Math.sin(i * 1.7)) * 5.5).toFixed(1),
      })),
      { label: "宿务省", value: 18.4 }, { label: "内格罗斯省", value: 15.1 },
    ],
    annotations: [
      { at: "宿务省", text: "受灾率 18.4%，全国最高" },
      { at: "内格罗斯省", text: "紧随其后，两省合计占全国伤亡三分之二" },
    ],
    claim_ids: [1],
  },
];

export default function VizLab() {
  return (
    <div className="page">
      <div className="panel panel-pad">
        <div className="uplabel">图元实验台 · 样例数据 · 不连接口</div>
        <div style={{ fontSize: 12, color: "var(--ink-4)", marginTop: 6 }}>
          十三种图元的排版校对页。真实数据由 synth 阶段产出，
          经规则层门槛过滤后才会出现在故事页。
        </div>
      </div>
      <FactStrip facts={FACTS} views={VIEWS} />
      <EventViews views={VIEWS} facts={FACTS} />
    </div>
  );
}
