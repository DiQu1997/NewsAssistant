# NewsAssistant

自动化、AI 驱动的公开信息态势系统：大量获取公开信息（新闻只是其中一层），
agent 处理成有状态的 Story / Claim / Entity，汇总为报告与多频道 dashboard。

**最高原则：硬编码结构，永不硬编码主题。** 系统不预设该关注什么；
频道是保存的查询，视图由数据结构自动选择，新领域由数据涌现。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 分层记忆、核心 schema、归档（非聚类）、频道=查询、计算分层 |
| [docs/views.md](docs/views.md) | 编码语法（全局不变量）+ 视图类型库与自动触发条件 |
| [docs/sources.md](docs/sources.md) | 信息源七级分类法（L1 权威文件 → L7 社群）、源注册表、接入优先级 |

## 阶段 1 · 采集层（可运行）

```bash
# 数据库：本地 Postgres 16+，或 docker compose up -d db
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
export NA_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/newsassistant

na init-db          # 幂等迁移（核心 schema：sources/documents/claims/entities/stories/story_events/llm_calls）
na sources sync     # sources/*.yaml 种子 → 源注册表（8 个跨层级示例源，L1–L5）
na ingest           # 采集一轮：feed → 正文抽取 → 三级去重 → 内容寻址落盘
na stats            # 库存统计
```

采集主干**全程无 LLM**：条件请求（ETag）、robots、trafilatura 正文抽取、
URL 规范化 → sha256 精确去重 → simhash 近重标记（转述候选）。
正文存文件（内容寻址），库里存指针。失败按源隔离，每轮写 fetch_log。

## 阶段 2 · 抽取层（可运行）

```bash
na extract --limit 20 [--model haiku]
```

**Claude Agent SDK**（`claude-agent-sdk`）驱动，走 Claude Code CLI 的登录态 ——
**计费到订阅，不需要 API key**（首次使用先 `claude login`）。

- 强 schema 靠工具调用：模型只有一个 `submit_extraction` 工具（带 JSON schema），
  没有任何文件/网络工具，结构化结果作为工具参数提交，校验发生在工具层
- 产出：claims（text + who/did/whom/when/where + 本文立场 -2..+2 + 置信度）、
  实体（规范全称 + 类型，跨文档按名称去重）、语言、观点/报道判别
- **每次调用（含失败）落 `llm_calls` 审计表**，完整 usage（含缓存命中）入库
- 失败的文档不置 `extracted_at`，下轮自动重试；orchestrator 与 SDK 解耦
  （`Extractor` 协议），测试用 FakeExtractor 不碰网络

测试：`pytest`（10 个纯逻辑单元测试 + 2 个集成测试：采集端到端走本地
HTTP 服务器，抽取 orchestrator 走 FakeExtractor —— 均无外网依赖）。

> 注意：Claude Code 远程环境的网络策略会拦截外部域（代理 403），
> 真实种子源需在放开出站的环境（如本地机器）运行。

## 原型

`prototypes/dashboard/` — 四个频道 + 一个元频道 + 故事详情页的静态布局原型
（`node build.mjs` / `node build-story.mjs` 生成；全部为虚构演示数据）。

## 历史

`legacy/` 是 v1（2024–2025）的遗留：scrapegraphai 抓取 + SQLite + KMeans 聚类。
v1 的失败结论（新闻语义空间无簇结构、事件需要有状态的归档而非聚类）
是 v2 设计的起点。
