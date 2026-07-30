# 信息源分类法与源注册表

> 按**证据层级**分类，因为层级直接决定用法：
> L1 是事实基线（分歧矩阵的锚点），L3 是不说谎的观测，L5 只是时效与解读。

## L1 · 一手权威文件（事实基线）

- 法规与公报：Federal Register、EUR-Lex、各国政府公报
- 立法过程：Congress.gov、欧洲议会、各国议会议案/投票/听证记录
- 监管规则与执法：SEC / FDA / FTC / FCC / EPA 及各国对应机构的规则、处罚、许可
- 央行：声明、纪要、演讲、经济预测、点阵图、资产负债表
- 统计机构：CPI / GDP / 就业 / 贸易 / 工业产出 / 普查
- 海关与贸易流（**镜像贸易差额可识别转口与制裁规避**）
- 政府采购与招投标：USAspending、TED（**订单是最早的战略信号**）
- 制裁与管制清单：OFAC SDN、EU consolidated、UN、BIS Entity List
- 司法：判决、案卷、破产（PACER / CourtListener / 裁判文书）
- 知识产权：USPTO / EPO / WIPO 专利商标
- 专业注册库：临床试验、药品/器械审批、化学品登记、船舶/航空器登记、公司注册与受益所有人
- 许可与审批：建设许可、环评、排放、并网队列、频谱、矿业权
- 事故调查：NTSB 及各国航空/铁路/工业/核安全报告

## L2 · 公司披露（有法律约束的自我陈述）

- 交易所备案：EDGAR（10-K/10-Q/8-K/S-1/13F/13D/Form 4）、HKEX、TSE、LSE RNS
- 法说会 transcript（**问答段比 prepared remarks 信息量大**）
- IR 材料、年报、ESG 报告；债务募集书、契约、评级行动
- 并购/回购/增发公告；月度营收、出货、稼动率、订单积压
- 供应链披露（冲突矿产、供应商名单）；产品发布/停产/召回/安全公告
- 招聘信息（**最早期的战略意图泄漏**）

## L3 · 结构化数值与遥测（不说谎的观测）

- 金融市场：股/债/汇/大宗、隐含波动率、信用利差、期限结构
- 实物价格：存储/稀土/化工现货、运费指数、电力现货、碳价、保险费率
- 链上数据；卫星遥感（FIRMS 火点、夜光、SAR、甲烷/NO₂、形变）
- 轨迹：AIS 船舶、ADS-B 航空；地球物理：USGS 地震、火山、海啸
- 气象水文；空气/水质/辐射
- 基础设施遥测：电网频率负荷、管流、BGP 路由与中断（Cloudflare Radar / IODA）、
  海底电缆状态、证书透明日志

## L4 · 学术与技术产出（领先 6–24 个月）

- arXiv / bioRxiv / medRxiv / SSRN；**引用与合作网络**（比论文本身更有信息量）
- 标准组织：IETF / 3GPP / ISO / W3C 提案与投票
- 代码生态：GitHub 活动、依赖图、包下载与版本
- 漏洞与威胁：CVE/NVD、KEV、厂商公告
- 基准与排行榜；会议议程（**议程即行业注意力分布**）

## L5 · 新闻与专业媒体（时效与解读，不是事实基线）

- 通讯社（路透/AP/法新/彭博/共同）；各国主流媒体 RSS/sitemap
- **行业垂直媒体**（trade press，深度常超综合媒体）
- **本地语种媒体**（很多一手信息只在当地语言里）
- 广播/播客转录；聚合与事件库（GDELT、Event Registry）；事实核查

## L6 · 机构分析与民间监测

智库、行业协会、审计机构（GAO）、NGO 监测（ACLED、Bellingcat）、
OSINT 社区、卖方研究、众包（OSM 变更、投诉库、罢工追踪）

## L7 · 观点与社群（最快、最脏）

机构/官员官方账号（**常先于公报**）、专业论坛（HN、行业版块）、
公开 Telegram/Discord、职业动态、工会公告

---

## 源注册表 schema

每个源是一条有属性的记录，属性直接喂给下游可信度判断：

```
source {
  接入方式:   RSS / API / sitemap / bulk / crawl
              API 类另带 adapter（响应→条目的解析器，newsassistant/apisources.py）
  传输通道:   httpx / curl / auto（部分源在 TLS 指纹层拒绝 httpx）
  载荷位置:   fetch_article —— feed/API 条目本身是否即全部载荷
  证据层级:   L1–L7
  时延特征:   实时 / 日 / 周 / 季 / 不定期
  修订行为:   是否事后修订（统计数据会；判决不会）
  地理与语种覆盖
  法律约束:   许可、robots、速率、可否再分发
  历史回溯深度
  独立性:     是否只是转述另一个源
}
```

**独立性**是广度指标的命门：50 家转发同一通稿，独立信源数是 1。
转述溯源（syndication tracing）必须做。

## 接入优先级

先要**便宜 + 结构化 + 没人认真用**的：

1. RSS/Atom + sitemap 全网订阅（几百源，免费，自带时间戳）
2. L1 干净 API：Federal Register、EDGAR、CourtListener、ClinicalTrials、
   USPTO、USAspending、OFAC
3. L3 免费遥测：USGS、FIRMS、气象、AIS/ADS-B 公开源、Cloudflare Radar
4. L4：arXiv、GitHub、CVE
5. FRED 与各国统计局
6. 最后才是付费市场数据与商业新闻 API
