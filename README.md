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

## 原型

`prototypes/dashboard/` — 四个频道 + 一个元频道的静态布局原型
（`node build.mjs` 生成；全部为虚构演示数据）。

## 历史

`Design.md` / `Database.md` 与根目录的 Python 文件是 v1（2024–2025）的遗留：
scrapegraphai 抓取 + SQLite + KMeans 聚类。v1 的失败结论
（新闻语义空间无簇结构、事件需要有状态的归档而非聚类）是 v2 设计的起点。
