# 词表 · Glossary

> 这个项目里反复出现的名词：中英对照、具体用途、在本项目里的确切含义。
> 遇到"这个词到底指什么"就查这里。带 `代码` 标记的是真实存在的表名/字段名/
> 函数名，可以直接 grep；带 Dnn 的指 `status.md` 决策日志的编号。

---

## 1. 最高原则

| 中文 | English | 在本项目里的意思 |
|---|---|---|
| **结构先验** | structural prior | 对任何领域都成立的假设：文档里有断言、断言有信源、实体有身份、事件有时间、信源有层级。**这些硬编码**，是系统地基（D2） |
| **主题先验** | topical prior | "半导体有六个环节"、"这些公司重要"这类领域知识。**一个都不硬编码**，全部由数据涌现。代码路径里出现领域词汇即违规 |
| **涌现** | emergence | 系统没被告知某个主题，却因为数据里的结构（实体反复共现、断言反复指向同一事件）而自己长出对它的表示 |
| **归档** | archival | 新文档进入**有身份的** Story，与"聚类"相对。v1 死于无状态聚类（D1） |
| **聚类** | clustering | 无状态地把一批文档分组。本项目**不用**：事件是有身份、会分裂合并的持续对象，批量聚类建模不了 |

---

## 2. 分层记忆 · Layered memory（L0–L3）

注意：这套 L0–L3 说的是**系统内部的加工层次**，与下面第 7 节的信源
L1–L7 是**两套完全不同的编号**，别混。

| 层 | English | 内容 | 特性 |
|---|---|---|---|
| **L0** | raw | 原始文档 + 元数据（正文存文件，库里存指针） | 不可变、可重放 |
| **L1** | extraction | 结构化抽取：claims / entities / 时间锚点 / 立场 | 可复用原子；换模型可整层重跑 |
| **L2** | story state | Story 状态：综述、时间线、参与实体、开放问题、来源分歧 | 有状态、增量维护、event-sourcing |
| **L3** | synthesis | 合成产物：报告、dashboard 快照 | 廉价可再生 |

---

## 3. 核心数据对象（都是真实的表）

| 中文 | English / 表名 | 是什么 | 作用 |
|---|---|---|---|
| **信息源** | source · `sources` | 一个可反复拉取的信息来源（RSS/API/sitemap/bulk/crawl） | 带证据层级、拉取节奏、法律约束、独立性。加源是加一行数据 |
| **文档** | document · `documents` | 一篇抓回来的原文 | L0 的单位。正文按 sha256 内容寻址落盘，库里只存指针 |
| **断言** | claim · `claims` | 从文档里抽出的**一句可验证的陈述** | **系统的差异化核心**。综述的每句话都必须引用它；分歧、立场、引用全部建立在它上面 |
| **实体** | entity · `entities` | 有身份的名词（组织/人/产品/地点） | 归并召回的钥匙；消歧后同一实体只有一条规范记录 |
| **故事** | story · `stories` | 一个**持续事件或进程**的有状态对象 | L2 的单位。文档归档进它，它维护综述/时间线/标量 |
| **故事事件** | story event · `story_events` | 故事状态变更的 append-only 日志（created/absorbed/split） | event-sourcing：回答"为什么这篇被归到这个故事" |
| **LLM 调用记录** | LLM call · `llm_calls` | 每一次模型调用的输入/输出/用量/错误 | 可审计的底线（D11）。失败也必须落库 |
| **频道** | channel · `channels` | **一条保存的查询**，不是一个页面 | D3/D28。新频道 = 插一行，代码零改动 |
| **管线运行记录** | pipeline run · `pipeline_runs` | 每个阶段每次执行的开始/结束/统计/报错 | 节奏判定与运维可见性的依据（D26） |
| **抓取日志** | fetch log · `fetch_log` | 每次拉源的结果 | 源级故障隔离与排查 |

---

## 4. 关键字段

### documents

| 字段 | English | 含义 |
|---|---|---|
| `url_canonical` | canonical URL | 保守规范化后的 URL。**一级去重**的键；规范化过度会把不同文章折叠成一条，比漏合并更糟（D8） |
| `content_ref` | content-addressed ref | sha256 内容寻址的文件指针。**二级去重**天然由 sha256 完成 |
| `simhash` | SimHash | 正文指纹。**三级去重**：汉明距离 ≤3 标为近重候选 |
| `near_dup_of` | near-duplicate of | 指向近重组的源头文档。只标候选，不下转述判决 |
| `syndication_of` | syndication of | **转述溯源**：跨源近重 = 通稿转发，指向原发。同源近重是更新，不标（D24） |
| `status` | — | ok / dup_exact / near_dup / fetch_failed / extract_failed |
| `fetch_article` | — | 源属性：feed 条目本身即全部载荷时不再抓页面（防反爬拦截页污染语料） |
| `fetch_via` | — | 源属性：httpx / curl / auto。应对 TLS 指纹拦截（D19） |
| `adapter` | — | 源属性：API 类源的"响应→条目"纯函数名（D18） |

### claims

| 字段 | English | 含义 |
|---|---|---|
| `text` | — | 断言原文 |
| `struct` | structured frame | `{who, did, whom, when, where}`。**有向链路视图就是从 who→whom 长出来的**（D29） |
| `stance` | stance | −2…+2，**本文对该断言的立场**，不是事实判断。分歧矩阵的燃料 |
| `confidence` | confidence | 抽取置信度 |
| `story_id` | — | 归档后指向所属故事 |

### entities

| 字段 | English | 含义 |
|---|---|---|
| `canonical_name` | canonical name | 规范全称 |
| `merged_into` | merged into | 消歧合并指向。**树高 ≤1**（路径压缩），读取端一律 `COALESCE(merged_into, id)` 穿透（D22） |
| `aliases` | aliases | 别名数组，append-only 可回滚 |

### stories

| 字段 | English | 含义 |
|---|---|---|
| `state` | — | active / dormant / archived（后两个状态的自动降级**尚未实现**） |
| `summary` | running summary | jsonb：`[{text, claim_ids}]`。**每句必带引用**，无引用的句子写入前丢弃（D23/D24） |
| `timeline` | timeline | 时间锚定的状态变化，同样带引用 |
| `open_questions` | open questions | 尚未有答案的问题 |
| `synthesized_at` | — | 与 `updated_at` 比较决定是否需要重新合成 |
| `scalars` | scalars | 派生标量，见下 |

### scalars（故事标量 —— dashboard 的燃料）

| 中文 | English | 定义 |
|---|---|---|
| **速度** | velocity | 近 3 天 vs 前 3 天文档数变化率（%）。方向在界面上由 ▲▼ 承载，不用颜色 |
| **广度** | breadth | **转述折叠后**的独立信源数。50 家转发同一通稿，广度是 1 不是 50（D12） |
| **一致度** | consensus | 100×(1−立场标准差/2)。低 = 信源在打架 |
| **阶段** | stage | 1–4，由 velocity 分档。故事的热度档位 |
| **文档数** | docs | 已归档文档数 |

---

## 5. 管线阶段（每个都是一条 CLI 命令，也是服务里的一个 stage）

| 中文 | 命令 | 做什么 | 用不用 LLM |
|---|---|---|---|
| **采集** | `na ingest` | 拉源 → 抓正文（trafilatura）→ 三级去重 → 内容寻址落盘 | 否 |
| **抽取** | `na extract` | 文档 → claims + entities（Agent SDK，强 schema） | 是 |
| **归并** | `na assign` | 新文档 → 召回候选故事 → 裁决 → 归档 | 是 |
| **实体消歧** | `na resolve-entities` | 候选发现（结构性）+ 同一性裁决 → merged_into | 是 |
| **转述溯源** | `na syndicate` | 近重组内跨源标 syndication_of | **否**（纯确定性） |
| **合成** | `na synthesize` | 故事 → 综述/时间线/开放问题（每句带引用） | 是 |
| **快照** | `na snapshot` | Postgres → JSON 派生产物 | 否 |
| **一轮管线** | `na run-cycle` | 按依赖顺序推进以上全部，整轮互斥 | — |
| **常驻服务** | `na serve` | dashboard + 只读 API + 进程内调度器 | — |
| **频道同步** | `na channels sync` | YAML 里的保存查询导入库 | 否 |

---

## 6. 归并层专有概念（系统的心脏）

| 中文 | English | 含义 |
|---|---|---|
| **召回** | recall | 纯确定性、零 LLM 成本地为新文档取候选故事：实体倒排 × IDF 加权 × 活跃时间窗 |
| **裁决** | adjudication / judge | LLM 单步判断"属于故事 X / 新故事"，判据落 `story_events` |
| **候选** | candidate | 召回给出的故事，裁决只能在候选里选（选了候选外的 id 一律降级为 new） |
| **IDF 降权** | IDF weighting | 出现率 >5% 的泛化实体不参与召回，其余按 1/df 加权。共享「Bite of Seattle」远比共享「United States」值钱（D21） |
| **合格实体 / 显著实体** | salient entity | 通过 IDF 阈值、**能进召回**的实体。波次划分的判据（D25） |
| **波次** | wave | 一次 SDK 调用里打包裁决的一组文档，条件是它们的合格实体**两两不相交**。相交即冲刷（D25） |
| **冲刷** | flush | 把当前波先落库再继续召回，保证后一篇看得见前一篇新建的故事 |
| **catch-all 故事** | catch-all story | 真实事故：泛化实体等权召回让一个故事滚雪球式吸收无关文档。局部每步合理，全局全错 |
| **漂移** | drift | 故事偏离它标题所述的核心事件。D21 的三条规则就是防它 |
| **分裂 / 合并** | split / merge | 故事级别的纠错，走 `story_events` 留痕 |
| **底盘** | chassis | 每次 Agent SDK `query()` 附带的系统提示 + 工具定义开销（~8k tokens）。批量打包就是为了摊薄它（D20/D25） |

---

## 7. 信息源分类 L1–L7 · Evidence tier

**证据层级**，数字越小越接近事实基线。与第 2 节的 L0–L3 无关。

| 层 | English | 是什么 | 例子 |
|---|---|---|---|
| **L1** | primary authoritative | 一手权威文件（事实基线） | 法规、判决、政府公告 |
| **L2** | corporate disclosure | 有法律约束的自我陈述 | SEC 备案、财报 |
| **L3** | structured telemetry | 结构化数值与遥测（不说谎的观测） | 地震台网、价格、传感器 |
| **L4** | academic / technical | 学术与技术产出（领先 6–24 个月） | 论文、预印本 |
| **L5** | news media | 新闻与专业媒体（时效与解读，**不是事实基线**） | 通讯社、报纸 |
| **L6** | institutional analysis | 机构分析与民间监测 | 智库、OSINT 团体 |
| **L7** | opinion / community | 观点与社群（最快、最脏） | 论坛、社交媒体 |

---

## 8. 前端与视图

| 中文 | English | 含义 |
|---|---|---|
| **编码语法** | encoding grammar | 全局不变量：色阶=密度、▲▼=方向、蓝↔红+字符=立场、状态色只表越阈、形状=实体类型。**换频道也不变意思**，变了产品就废（D5） |
| **保存的查询** | saved query | 频道的实体。结构键（实体命中/文本/标量阈值/时间窗/排序）+ 主题值。请求时执行 |
| **结构检测** | structure detection | 对一个切片跑一组检测器，回答"这里有什么结构"，视图由答案选（D4/D29） |
| **主舞台** | main stage | 检测到的结构中权重最高者占据的主面板 |
| **分位分档** | quantile bucketing | 密度色阶按分位切档而非线性/对数；**阈值必须写进图例**，否则非线性间距会误导（D15） |
| **共现网络** | co-occurrence network | 实体间无向关系稠密时触发 |
| **有向链路** | directed chain | who→whom 稳定边可拓扑排序时触发。半导体供应链、审批流程、司法审级同构 |
| **有序阶梯** | ordered ladder | 实体在少数有序状态间移动时触发（尚未实现） |
| **共轴时间带** | co-axial time band | 存在可与叙事对齐的外生数值序列时触发（缺 observations 表，未实现） |
| **背离榜** | divergence board | 叙事强度与外生幅度按标的配对时触发（同上未实现） |
| **热力矩阵** | heat matrix | 两个离散维度 + 强度（如 源×日） |
| **构成条** | composition bar | 单维度按份额分解，份额和 ≈100% |
| **分歧矩阵** | disagreement matrix | 同一断言多源立场不一。**通用，核心资产** —— 参照项目做不出来，因为它们的数据没有 claim 层 |
| **未解问题** | open questions | 恒在，位置靠后 |
| **密度带** | density strip | 故事流每行那条 14 天逐日吸收量的色格 |
| **CVD 分离度** | CVD separation | 色觉缺陷下相邻色对的可分辨程度。配色改动必须过 dataviz 校验器（D16） |

---

## 9. 工程与审计

| 中文 | English | 含义 |
|---|---|---|
| **内容寻址** | content-addressed storage | 按 sha256 存文件、库里存指针。天然做精确去重 |
| **event-sourcing** | event sourcing | 状态变更以 append-only 事件记录，而非只留最新值。"为什么"永远可追 |
| **幂等** | idempotent | 同一操作重复执行结果不变。采集、消歧、转述溯源、频道同步都是 |
| **强 schema / 工具调用** | tool-call schema enforcement | 模型只有一个提交工具，校验发生在工具层，比"请输出 JSON"可靠（D10） |
| **引用强制** | citation enforcement | 综述句无引用或假引用**在写入端丢弃**，全丢则不落库。不靠提示词自觉（D23/D24） |
| **审计表** | audit table | `llm_calls`。含失败与完整 usage —— 只存两个 token 数字会完全误判成本（D11） |
| **失败隔离** | failure isolation | 一个源/一个阶段失败不拖垮整轮，错误落库不吞 |
| **互斥锁** | advisory lock | Postgres 会话级锁，保证同一时刻只有一轮管线在跑；进程崩溃自动释放（D26） |
| **节奏** | cadence | 每个阶段的 min_interval，判定依据查 `pipeline_runs`（落库而非内存，重启不丢） |
| **协议替身** | protocol double | 测试里替换 LLM 的 Fake 实现（FakeExtractor/FakeJudge/…）。测试不碰外网 |
| **决策日志** | decision log | `docs/status.md` 第 1 节，Dnn 编号。**推翻任何一条前先读它的理由** |
