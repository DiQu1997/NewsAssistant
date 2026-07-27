/* 频道 = 保存的查询（docs/architecture.md §4）。
 *
 * 这里**没有版面、没有面板、没有领域逻辑** —— 只有：
 *   - 一个对通用存储的过滤器（query）
 *   - 频道标识色（两套主题的强调色 + 顺序色阶）
 *
 * 版面由 build.mjs 的选择器按查询结果里检测到的数据结构自动组装。
 * 新频道 = 新增一行查询；不需要写任何新代码。
 *
 * 最后一个频道演示跨主题的"元频道"：不按领域过滤，
 * 只收全库分歧度最高的断言 —— 同样零新代码。
 */

export const CHANNELS = [
  { id: "ai-industry", name: "AI 产业", query: { tag: "ai" },
    dark:  { accent:"#9085e9", ramp:["#2b2555","#3a3273","#4c4292","#6155b3","#7869d0","#9085e9"] },
    light: { accent:"#4a3aa7", ramp:["#ded9f5","#c3baec","#a294dd","#8071c9","#6152b3","#4a3aa7"] } },

  { id: "semiconductor", name: "半导体", query: { tag: "semi" },
    dark:  { accent:"#22bd80", ramp:["#0f4232","#12583f","#15704f","#18885f","#1ba26f","#22bd80"] },
    light: { accent:"#128257", ramp:["#d0eee0","#a8ddc6","#7ac9a8","#4bb388","#279a6d","#128257"] } },

  { id: "macro-markets", name: "宏观市场", query: { tag: "macro" },
    dark:  { accent:"#c98500", ramp:["#3d2c05","#553d07","#6f5009","#8a640b","#a5780d","#c98500"] },
    light: { accent:"#8a6000", ramp:["#f6e6c4","#ecd097","#dcb463","#c4952f","#a67a10","#8a6000"] } },

  { id: "geopolitics", name: "地缘政治", query: { tag: "geo" },
    dark:  { accent:"#d95926", ramp:["#40190d","#5a2412","#753017","#913d1c","#b04920","#d95926"] },
    light: { accent:"#c44f18", ramp:["#fadfd0","#f4c0a4","#ec9d75","#e07d4d","#d2652d","#c44f18"] } },

  /* 元频道：跨全库，按分歧度选断言。没有主题过滤器。 */
  { id: "meta-disagreement", name: "全库分歧", query: { meta: "disagreement" },
    dark:  { accent:"#3987e5", ramp:["#16283f","#1b3a5c","#214d7a","#286098","#2f75b8","#3987e5"] },
    light: { accent:"#2a78d6", ramp:["#d3e4f8","#aecdf2","#86b6ef","#5e9ce4","#3f86d8","#2a78d6"] } },
];
