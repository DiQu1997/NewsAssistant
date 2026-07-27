# NewsAssistant v2 · 架构设计

> 目标：大量获取公开信息 → agent 处理 → 汇总为报告与 dashboard。
> 系统必须是**通用的**：完全根据获取到的信息进行处理，不预设它该关注什么。

## 0. 最高原则：硬编码结构，永不硬编码主题

先验分两种，命运完全不同：

| | 例子 | 处置 |
|---|---|---|
| **结构先验** | 文档里有断言；断言有信源；实体有身份；事件有时间；信源有层级 | **硬编码**。对任何领域都成立，是系统的地基 |
| **主题先验** | "半导体的环节有六个"、"这些公司值得追"、"这些是重要走廊" | **一个都不硬编码**。全部由数据涌现 |

违反这条规则的系统只能看见构建者当初想到的东西：配置里没有"光刻胶"，
它就永远发现不了光刻胶断供。

## 1. 分层记忆

| 层 | 内容 | 特性 |
|---|---|---|
| **L0** | 原始文档 + 元数据（正文存文件，库里存指针） | 不可变，可重放 |
| **L1** | 结构化抽取：claims / entities / 时间锚点 / 立场 | 可复用原子；换模型可整层重跑 |
| **L2** | **Story 状态**：running summary、时间线、参与实体、开放问题、来源分歧 | 有状态、增量维护、**event-sourcing**（append-only 更新日志） |
| **L3** | 合成产物：日报、深度报告、dashboard 快照 | 廉价可再生 |

每次 LLM 调用的输入输出全部落库。系统必须能回答：
"为什么这篇被归到这个故事"、"这个结论由哪几篇支撑"。
可审计不是加分项，是底线（对应产品目标里的"可靠来源"）。

## 2. 核心对象 schema（结构先验的全部内容）

```
source {
  id, 接入方式(RSS/API/sitemap/bulk/crawl),
  证据层级 L1–L7（见 sources.md）,
  时延特征, 修订行为, 地理与语种,
  法律约束(许可/robots/速率/再分发),
  独立性: 是否只是转述另一个源     ← 喂给"广度"指标
}

document {
  id, source_id, url(canonical), fetched_at, published_at,
  content_ref(文件指针), simhash, syndication_of(document_id | null)
}

claim {                                  ← 差异化的核心
  id, document_id, story_id,
  text, who/did/to-whom/when/where,
  stance(-2..+2), confidence, extracted_at, model_ver
}

entity {
  id, canonical_name, kind(org/person/product/place/…),
  aliases[], embeddings, merged_from[]     ← 消歧走 召回+LLM 裁决
}

story {
  id, state(active/dormant/archived),
  summary, open_questions[], timeline[],
  members[document_id], entities[],
  更新日志: append-only events(created/absorbed/split/merged/updated)
  派生标量: velocity / breadth / consensus / novelty / uncertainty / stage
}
```

派生标量是 dashboard 的燃料，**dashboard 的需求倒推进抽取 schema**。
其中 breadth（独立信源数）必须做转述溯源：50 家转发同一通稿，广度是 1 不是 50。

## 3. 归档，不是聚类

新文档进来：

1. **抽取**（便宜模型 + 强 schema，Batch API）→ claims / entities / 时间锚点
2. **召回**（纯确定性）：向量相似 + 实体倒排 + 时间窗 → top-K 候选故事
3. **裁决**（好模型，单步）："属于故事 X / 新故事 / X 的分支？"
4. **更新**：增量更新 Story 状态，写一条 event

不做全量聚类。事件是有身份、会持续演化、会分裂合并的对象；
无状态的批量聚类建模不了它（v1 的死因）。

## 4. 频道 = 保存的查询，不是分区

- 底下只有**一个通用存储**；所有源、所有领域共用
- 频道 = 过滤器（实体集 / 主题向量 / 标签 / 时间窗）+ 视图配置
- 一个故事可以同时出现在多个频道（出口管制既是半导体也是地缘也是宏观）
- 视图由**检测到的数据结构**自动选择（见 views.md），新频道不需要新代码

### 涌现：系统自己提议频道

当聚类中出现一团**持续、密集、跨源、且不属于任何现有频道**的故事，
系统提出："这里在长出一个新领域，要不要建频道。"
这是防止系统被自己的分类困住的机制——发现新领域的能力不能依赖人事先列全。

### 跨领域元频道（不按主题切）

- **Watchlist**：以一份人/公司/机构清单为核心，跨全库追踪
- **全库分歧**：只收分歧度最高的断言，纯"元"视角
- **新兴**：只收"正在成形、未归属"的故事簇
- **静默**：数值源在动但叙事没跟上的标的

## 5. 计算分层（agent 用在哪）

| 层 | 每日量级 | 用什么 |
|---|---|---|
| 采集 | ~10⁴ 文档 | 无 LLM：RSS/API/sitemap + trafilatura，URL canonical + simhash 去重 |
| 抽取 | ~10⁴ 次 | 便宜模型 + 强 schema，Batch API |
| 归并 | ~10⁴ 次 | 召回（免费）+ 好模型单步裁决 |
| 合成 | ~10² 次 | 强模型 agent loop：更新时间线、标注分歧、列未解问题、主动补查 |
| 报告 | ~10⁰ 次 | 强模型 agent：选题、排序、写 brief、生成 dashboard 快照 |

主干是可重放、可缓存的 pipeline；agent 只挂在需要判断力的节点。
禁止用 LLM 解析 HTML（v1 教训：scrapegraphai 逐页跑 GPT 是数量级的浪费）。

## 6. 技术栈

- **Postgres + pgvector**：关系 + 全文 + 向量 + JSONB 一个库
- Python + FastAPI；调度先 cron/APScheduler
- LLM：Anthropic SDK 直连，structured output 走 tool-calling 强制 schema
- 前端：先静态生成（见 prototypes/），交互需求明确后再上框架
- Dashboard 数据走物化视图/快照表，前端只渲染

## 7. 评估

上线前先人工标一个小评估集（≥200 篇 + 正确的故事归属 / 实体消歧答案），
之后所有改动对着它测。没有它，一切调优都是凭感觉（v1 教训）。
