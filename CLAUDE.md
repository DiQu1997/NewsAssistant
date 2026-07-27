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

- `docs/architecture.md` — 分层记忆 L0–L3、核心 schema、归并设计、频道=查询
- `docs/views.md` — 编码语法（全局不变量）+ 视图类型库与触发条件
- `docs/sources.md` — 信息源 L1–L7 分类法、源注册表、接入优先级
- `newsassistant/` — Python 包（采集 + 抽取）；迁移在 `migrations/*.sql`
- `sources/seed.yaml` — 种子源（8 个跨层级示例）
- `prototypes/dashboard/` — 前端布局原型（store→查询→结构检测→视图注册表）
- `legacy/` — v1 遗留，只读参考

## 常用命令

```bash
.venv/bin/pytest                 # 12 个测试，全部无外网依赖
na init-db                       # 幂等迁移
na sources sync && na ingest     # 采集一轮（无 LLM）
na extract --limit 20            # 抽取（Claude Agent SDK，走 claude login 订阅）
na stats
# 前端原型：cd prototypes/dashboard && node build.mjs && node build-story.mjs
```

环境变量见 `newsassistant/config.py`（NA_DATABASE_URL / NA_DATA_DIR / …）。
Dashboard 配色改动必须过 dataviz 校验器（CVD 分离度）。

## 当前状态（2026-07-27）

- ✅ 阶段 1 采集层：feed → trafilatura → URL 规范化 / sha256 / simhash 三级去重
  → 内容寻址落盘。端到端测试用本地 HTTP 服务器。
- ✅ 阶段 2 抽取层：Agent SDK，唯一工具 `submit_extraction` 强 schema；
  claims（含本文立场 -2..+2）+ 实体（规范全称）；失败自动重试。
- ⬜ **阶段 3 归并层（下一步，系统的心脏）**：
  1. 召回（纯确定性）：`document_entities` 倒排 + 时间窗 + 文本相似 → top-K 候选故事
  2. 裁决（Agent SDK 单步）："属于故事 X / 新故事 / 分支？" → 判据落 `story_events`
  3. Story 标量增量维护：velocity / breadth（需转述溯源，near_dup_of 已备）/ consensus
  4. 评估集：先攒几天真数据，人工标 ≥200 篇的正确归属，之后所有改动对着测
- ⬜ 之后：合成层（故事页数据真化）、pgvector 向量召回、实体消歧裁决

## 工程约定

- Python 3.11+，psycopg3 直连 + 纯 SQL，无 ORM；测试不碰外网
  （LLM 用 FakeExtractor 协议替身，HTTP 用本地服务器）
- 迁移只追加，不改旧文件；schema 变更走新的 NNN_*.sql
- commit 信息解释"为什么"，不复述 diff；设计决策进 docs/ 不进聊天记录
