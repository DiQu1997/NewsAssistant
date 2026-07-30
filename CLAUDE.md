# NewsAssistant · Claude Code 项目上下文

通用公开信息态势系统：采集公开信息（新闻只是 L5 层）→ agent 处理成有状态的
Story / Claim / Entity → 多频道 dashboard + 带引用的报告。

## 最高原则（违反即错）

1. **硬编码结构，永不硬编码主题。** 代码路径里不允许出现领域词汇；
   频道是保存的查询，视图按数据结构自动选择，新领域由数据涌现。
2. **归档，不是聚类。** 新文档走"召回 + LLM 裁决"进有身份的 Story，
   不做无状态批量聚类（v1 死因，见 legacy/）。
3. **禁止用 LLM 解析 HTML。** 正文抽取用 trafilatura；LLM 只花在理解上。
4. **每次 LLM 调用落 `llm_calls`**（含失败、含完整 usage）。可审计是底线。
5. **综述里无引用支撑的句子不允许出现。**

## 目录

- **`docs/status.md` — 单一事实来源：决策日志（17 条，含理由）、当前进展、
  路线图、TODO、开放问题、风险。新会话先读它。**
- `docs/glossary.md` — 词表：所有名词的中英对照、用途、在项目里的确切含义
- `docs/architecture.md` — 分层记忆 L0–L3、核心 schema、归并设计、频道=查询
- `docs/views.md` — 编码语法（全局不变量）+ 视图类型库与触发条件
- `docs/sources.md` — 信息源 L1–L7 分类法、源注册表、接入优先级
- `newsassistant/` — Python 包（采集 + 抽取）；迁移在 `migrations/*.sql`
- `sources/seed.yaml` — 种子源（8 个跨层级示例）
- `newsassistant/web/` — 真实 dashboard（运行时取数；视图由结构检测自动选择）
- `prototypes/dashboard/` — 前端布局原型（虚构数据，保留作版面参考）
- `legacy/` — v1 遗留，只读参考

## 常用命令

```bash
.venv/bin/pytest                 # 82 个测试，全部无外网依赖
na init-db                       # 幂等迁移
na sources sync && na ingest     # 采集一轮（无 LLM）
na extract --limit 200           # 抽取（Agent SDK 批量 8 篇/调用，走 claude login 订阅）
na assign --model sonnet         # 归并：召回 + 波次批量裁决 → 故事（llm_calls 全审计）
na resolve-entities              # 实体消歧：候选发现 + 裁决 → merged_into/aliases
na syndicate                     # 转述溯源（纯确定性）→ syndication_of，breadth 诚实化
na synthesize --model sonnet     # 合成：综述/时间线/开放问题（每句带 claim 引用）
na lifecycle                     # 故事生命周期：active→dormant→archived
na stories && na story <id> && na stats
na run-cycle [--force|--stage X] # 推进一轮管线（顺序/节奏/失败隔离/整轮互斥）
na channels sync                 # 频道（保存的查询）导入 sources/channels.yaml
na serve                         # 常驻服务：dashboard + 只读 API + 调度器（:8787）
```

环境变量见 `newsassistant/config.py`（NA_DATABASE_URL / NA_DATA_DIR / …）。
Dashboard 配色改动必须过 dataviz 校验器（CVD 分离度）。

## 当前状态（2026-07-29）

- ✅ 阶段 1 采集层：feed → trafilatura → URL 规范化 / sha256 / simhash 三级去重
  → 内容寻址落盘。端到端测试用本地 HTTP 服务器。
- ✅ 阶段 2 抽取层：Agent SDK，唯一工具 `submit_extraction` 强 schema；
  claims（含本文立场 -2..+2）+ 实体（规范全称）；失败自动重试。
- ✅ 阶段 1.5 API 类源：`kind: api` + `adapter`（apisources.py，响应→条目的纯函数，
  下游管线复用）+ 源属性 `fetch_via`（httpx/curl/auto，应对 TLS 指纹拦截）。
  首个适配器 edgar_fulltext（SEC EDGAR 全文检索 JSON）。
- ✅ 阶段 3 归并层：IDF 降权倒排召回（merge.py）+ Agent SDK 波次批量裁决
  → 判据落 `story_events`；标量 velocity/breadth/consensus/stage。
- ✅ 实体消歧（entity_resolve.py）：结构性候选发现 + LLM 同一性裁决 →
  merged_into/aliases（树高 ≤1，路径压缩），召回 COALESCE 穿透。D22。
- ✅ 阶段 4 合成层（synth.py，005）：综述/时间线/开放问题一步产出；
  **引用强制在代码层**（D24）：无引用/假引用句写入前丢弃，全丢则不落库。
  转述溯源（syndicate.py，零 LLM）：near_dup 组内跨源标 syndication_of，
  breadth 改折叠后独立信源数。
- ✅ **阶段 5 前端真化 + 端到端 service**：
  `na serve` = dashboard + 只读 API + 进程内调度器，一个命令启动完整系统。
  管线 7 阶段自动推进（ingest→extract→assign→resolve→syndicate→synthesize→lifecycle）。
  dashboard 从 `/api/*` 实时取数；频道标识色运行时注入；8 个结构检测器自动选视图。
  故事生命周期（lifecycle.py，008）：active→dormant（7天）→archived（30天）。
- ⬜ **下一步**：实体页、频道涌现、pgvector 向量召回

## 工程约定

- Python 3.11+，psycopg3 直连 + 纯 SQL，无 ORM；测试不碰外网
  （LLM 用 FakeExtractor 协议替身，HTTP 用本地服务器）
- 迁移只追加，不改旧文件；schema 变更走新的 NNN_*.sql
- commit 信息解释"为什么"，不复述 diff；设计决策进 docs/ 不进聊天记录
